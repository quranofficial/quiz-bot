# -*- coding: utf-8 -*-
"""خاڵی دەستپێکی بۆتی تاقیکردنەوە — ٢٤/٧ پۆڵینگ دەکات (لە GitHub Actions بۆ ٥ کاتژمێر و ٥٠
خولەک بەبێ پشوو، پاشان دانیشتی داهاتوو جێگەی دەگرێتەوە).

تایبەتمەندییەکان:
• Defaults(protect_content=True) — پەیامەکانی بۆ بەکارهێنەرانی ئاسایی ناتوانرێت
  forward یان save یان copy بکرێت؛ تەنها ئادمینەکان ئازادن (پەیامەکانی بۆ ئادمین
  بە protect_content=False دەنێردرێن).
• concurrent_updates(True) — چەندین بەکارهێنەر لە هەمان کاتدا وەڵام وەردەگرن.
• خشتەی تاقیکردنەوەی شەوانە — هەر ٢٠ چرکە پشکنین، لە کۆتاییدا ڕیزبەندی بۆ بەژداران.
"""

import asyncio
import inspect
import logging
import os
import sys

from telegram import BotCommand, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, Defaults, MessageHandler, filters)
from telegram.request import HTTPXRequest

import config
import events as evmod
import handlers_admin
import handlers_user
import keyboards as K
import storage as st
import texts as T
from gitsync import GitSync
from storage import Storage

log = logging.getLogger("bot")


# ---------------- ژمێریاری کات و داخستن ----------------

async def _auto_stop(context: ContextTypes.DEFAULT_TYPE) -> None:
    log.info("کاتی ئەم دانیشتە تەواو بوو — داخستنی ساغلام (GitHub دووبارە دەستی پێدەکاتەوە)...")
    result = context.application.stop_running()
    if inspect.isawaitable(result):
        await result


async def _on_shutdown(app: Application) -> None:
    gs = app.bot_data.get("gitsync")
    if gs:
        try:
            await asyncio.to_thread(gs.flush)
        except Exception as e:
            log.warning("flush لە کاتی داخستن: %s", e)
    log.info("بۆت داخرا.")


async def _post_init(app: Application) -> None:
    try:
        # بۆ هەموو بەکارهێنەران: تەنها /start و /help
        await app.bot.set_my_commands([
            BotCommand("start", "دەستپێکردن"),
            BotCommand("help", "ڕێنمایی"),
        ])
    except Exception as e:
        log.warning("set_my_commands: %s", e)
    # بۆ ئادمینەکان: /admin + /start + /help
    storage = app.bot_data.get("storage")
    if storage:
        import handlers_admin
        for aid in storage.all_admin_ids():
            await handlers_admin.ensure_admin_commands(app.bot, aid)
    log.info("بۆت ئامادەیە ✅ (protect_content=ON بۆ بەکارهێنەران / OFF بۆ ئادمین و خاوەن, "
             "concurrent_updates=ON)")


async def _error(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if err and "Conflict" in repr(err):
        # دانیشتنێکی تر پۆڵینگ دەکات — دەستبەجێ دەچینە دەرەوە، دانیشتی داهاتوو جێگەی دەگرێتەوە
        log.warning("getUpdates Conflict — داخستن بۆ دانیشتنی نوێ.")
        gs = context.bot_data.get("gitsync")
        if gs:
            try:
                await asyncio.to_thread(gs.flush)
            except Exception:
                pass
        os._exit(0)
    log.error("هەڵەیەک ڕوویدا: %s", err, exc_info=err)


# ---------------- پاراستنی ناوەڕۆک: تەنها ئادمین forward/save/copy بکات ----------------

# خاڵەکانی API ی ناردنی ناوەڕۆک — protect_content یان هەیە (ناوی endpoint بە camelCase)
_PROTECT_ENDPOINTS = ("sendmessage", "sendphoto", "senddocument", "sendvideo",
                      "sendanimation", "sendaudio", "sendvoice", "sendvideonote",
                      "sendsticker", "sendmediagroup", "sendpoll", "sendlocation",
                      "sendvenue", "sendcontact", "sendinvoice", "sendgame",
                      "senddice", "copymessage", "forwardmessage", "sendpaidmedia")


def exempt_admin_sends(app: Application, storage: Storage) -> None:
    """قفڵی ناوەڕۆک بە دوو ئاست کار دەکات، بە جۆرێک کە هەمیشە بێ شکست بێت:

    • بەکارهێنەری ئاسایی: Defaults(protect_content=True) هەموو پەیامەکان دەقفڵێنێت
      (forward/save/copy/screenshot lock).
    • خاوەن و ئادمین: لە خاڵی کۆتایی ناردندا (Bot._do_post — دوای ئەوەی Defaults
      جێبەجێ کراوە) protect_content لادەبرێت — بۆیە ئادمین ئازادە پەیامەکانی
      بۆتەکە forward/save/copy بکات، بێ گوێپێبستن لە ڕێگەی ناردنەکە.

    _do_post دەرگا کۆتاییەکەیە کە هەموو پەیامێک بەناودا تێدەپەڕێت — ئەگەر هەر
    ڕێگەیەکی ناردن لە پێشدا تێپەڕ بێت یان patch نەبێت، ئەمە هەمووی دەگرێتەوە."""
    bot_cls = type(app.bot)

    def _to_int(chat_id):
        try:
            return int(getattr(chat_id, "chat_id", chat_id))
        except (TypeError, ValueError):
            return None

    orig_do_post = bot_cls._do_post

    async def _do_post(self, endpoint, data, **kwargs):
        try:
            if isinstance(data, dict) and endpoint.lower().replace("_", "") in _PROTECT_ENDPOINTS:
                cid = _to_int(data.get("chat_id"))
                if cid is not None and storage.is_admin(cid):
                    # ئادمین/خاوەن — هەرگیز قفڵ نەکرێت: forward/save/copy بۆ ئازادە
                    if data.pop("protect_content", None) is not False:
                        log.debug("protect_content لابرا بۆ ئادمین %s (%s)", cid, endpoint)
                elif cid is not None and "protect_content" not in data:
                    # بەکارهێنەری ئاسایی — زامنی قفڵ (پاشەکەوتی Defaults)
                    data["protect_content"] = True
        except Exception:
            pass
        return await orig_do_post(self, endpoint, data, **kwargs)

    bot_cls._do_post = _do_post


# ---------------- خشتەی تاقیکردنەوەی شەوانە ----------------

async def _event_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """هەر ٢٠ چرکە: لە کۆتایی تاقیکردنەوەی شەوانە ڕیزبەندی بۆ بەژداران دەنێردرێت."""
    try:
        storage = context.bot_data["storage"]
        ev = storage.get_event()
        if not ev or not ev.get("enabled"):
            return
        date = evmod.today_str()
        if (ev.get("announced") or {}).get(date):
            return
        if evmod.status(ev) != evmod.STATUS_OVER:
            return
        day = (ev.get("results") or {}).get(date) or {}
        if not day:
            ev.setdefault("announced", {})[date] = True
            evmod.cleanup(ev)
            storage.save_event(ev)
            return
        rows = evmod.leaderboard(day)
        text = evmod.fmt_leaderboard(rows, ev.get("title", "تاقیکردنەوەی شەوانە"))
        # ناردن بۆ هەموو بەژداران
        for uid, _ in rows:
            try:
                await context.bot.send_message(int(uid), text, parse_mode="HTML")
            except Exception:
                pass
        # ناردن بۆ ئادمینەکان
        for aid in storage.all_admin_ids():
            try:
                await context.bot.send_message(aid, text, parse_mode="HTML")
            except Exception:
                pass
        ev.setdefault("announced", {})[date] = True
        evmod.cleanup(ev)
        storage.save_event(ev)
        log.info("ڕیزبەندی تاقیکردنەوەی شەوانە بڵاوکرایەوە (%s بەژدار).", len(rows))
    except Exception as e:
        log.error("event_tick: %s", e, exc_info=True)


# ---------------- مسڕەری دوگمەکان (Callback router) ----------------

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or not q.data:
        return
    storage = context.bot_data["storage"]
    data = q.data
    try:
        await q.answer()
    except Exception:
        pass

    try:
        # ---------- دەرگای باند: بەکارهێنەری باندکراو هیچ ناتوانێت ----------
        if await handlers_user.reject_banned(update, context):
            return

        # ---------- گشتی ----------
        if data == "noop":
            return
        if data == "home":
            return await handlers_user.cb_home(q, context)
        if data.startswith("nav:"):
            return await handlers_user.cb_nav(q, context, data[4:])
        if data.startswith("quiz:"):
            return await handlers_user.cb_quiz(q, context, data[5:])
        if data.startswith("qs:"):
            parts = data.split(":")
            if len(parts) == 3:
                return await handlers_user.cb_qs(q, context, parts[1], parts[2])
            return
        if data.startswith("ans:"):
            parts = data.split(":")
            if len(parts) == 3:
                try:
                    idx = int(parts[2])
                except ValueError:
                    return
                return await handlers_user.cb_answer(q, context, parts[1], idx)
            return
        if data == "pgs":
            return await handlers_user.cb_pages(q, context)
        if data.startswith("pg:"):
            return await handlers_user.cb_page(q, context, data[3:])

        # ---------- تۆمارکردن و پرسیار بکە (لای بەکارهێنەر) ----------
        if data == "ask" or data.startswith("ask:"):
            return await handlers_user.cb_ask(q, context, data)
        if data.startswith("reg:"):
            return await handlers_user.cb_reg(q, context, data[4:])

        # ---------- پرسیارەکانم / ڕاپۆرتەکانم / نامە هاتووەکان (لای بەکارهێنەر) ----------
        if data == "myq":
            return await handlers_user.cb_myq(q, context)
        if data.startswith("myqv:"):
            return await handlers_user.cb_myq_view(q, context, data[5:])
        if data == "myrp":
            return await handlers_user.cb_myrp(q, context)
        if data.startswith("myrpv:"):
            return await handlers_user.cb_myrp_view(q, context, data[6:])
        if data == "myinbox":
            return await handlers_user.cb_myinbox(q, context)
        if data.startswith("myinv:"):
            return await handlers_user.cb_myinbox_view(q, context, data[6:])
        if data.startswith("cx:"):
            # بەشە زیادکراوەکانی مینیو — پەڕەیەکی زانیاری دەکەنەوە
            return await handlers_user.cb_page(q, context, data[3:])

        # ---------- تاقیکردنەوەی تایبەت / ڕاپۆرت / فڵاشکارت / شەوانە / ئامار ----------
        if data == "mq" or data.startswith("mq:"):
            return await handlers_user.cb_mq(q, context, data)
        if data == "rp" or data.startswith("rp:pick:") or data == "rp:skip":
            return await handlers_user.cb_report(q, context, data)
        if data == "fc" or data.startswith("fc:"):
            return await handlers_user.cb_fc(q, context, data)
        if data == "qn" or data.startswith("qn:play") or data == "qn:results":
            return await handlers_user.cb_qn(q, context, data)
        if data == "mystats":
            return await handlers_user.cb_mystats(q, context)

        # ---------- ئادمین ----------
        if not storage.is_admin(q.from_user.id):
            return await handlers_user.alert(q, T.ADMIN_ONLY)

        if data == "adm":
            return await handlers_admin.cb_home(q, context)

        if data == "admtk":
            return await handlers_admin.cb_tickets(q, context)
        if data.startswith("tk:"):
            return await handlers_admin.cb_ticket(q, context, data[3:])
        if data == "impfile":
            return await handlers_admin.cb_impfile(q, context)
        if data == "impok":
            return await handlers_admin.cb_impok(q, context)
        if data.startswith("impf:"):
            return await handlers_admin.cb_impf(q, context, data)
        if data.startswith("impx:"):
            return await handlers_admin.cb_imp_sample(q, context)
        if data == "pendq":
            return await handlers_admin.cb_pending(q, context)
        if data.startswith("pqset:") or data in ("pqskip", "pqdone"):
            return await handlers_admin.cb_pq(q, context, data)
        if data == "menu":
            return await handlers_admin.cb_menu(q, context)
        if data.startswith("menu:"):
            return await handlers_admin.cb_menu_label(q, context, data[5:])
        if data == "menureset":
            return await handlers_admin.cb_menu_reset(q, context)
        if data == "menuex":
            return await handlers_admin.cb_menu_extra(q, context)
        if data.startswith("menuexpick:"):
            return await handlers_admin.cb_menu_extra_pick(q, context, data[11:])
        if data.startswith("menuexdel:"):
            return await handlers_admin.cb_menu_extra_del(q, context, data[10:])

        # ---------- ڕاپۆرتەکان (ئادمین) ----------
        if data == "admrp":
            return await handlers_admin.cb_reports(q, context)
        if data == "rp:clear":
            return await handlers_admin.cb_report_clear(q, context)
        if data.startswith("rp:"):
            return await handlers_admin.cb_report(q, context, data[3:])

        # ---------- بەکارهێنەران (ئادمین) ----------
        if data == "usr":
            return await handlers_admin.cb_users(q, context)
        if data.startswith("usr:page:"):
            try:
                page = int(data[9:])
            except ValueError:
                page = 1
            return await handlers_admin.cb_users(q, context, page)
        if data.startswith("usr:view:"):
            return await handlers_admin.cb_user_view(q, context, data[9:])
        if data == "usr:search":
            return await handlers_admin.start_user_search(q, context)
        if data.startswith("usrmsg:"):
            return await handlers_admin.start_user_msg(q, context, data[7:])
        if data.startswith("usr:ban:"):
            return await handlers_admin.start_user_ban(q, context, data[8:])
        if data.startswith("usr:unban:"):
            return await handlers_admin.cb_user_unban(q, context, data[10:])
        if data.startswith("usr:del:"):
            return await handlers_admin.cb_user_del(q, context, data[8:])
        if data.startswith("usr:delok:"):
            return await handlers_admin.cb_user_del_ok(q, context, data[10:])

        # ---------- تاقیکردنەوەی شەوانە (ئادمین) ----------
        if data == "qnev":
            return await handlers_admin.cb_qnev(q, context)
        if data == "qn:new":
            return await handlers_admin.qn_new(q, context)
        if data == "qn:toggle":
            return await handlers_admin.cb_qn_toggle(q, context)
        if data == "qn:edittime":
            return await handlers_admin.qn_edit_time(q, context)
        if data == "qn:editsrc":
            return await handlers_admin.qn_edit_src(q, context)
        if data == "qn:srcfolder":
            return await handlers_admin.qn_edit_src_folder(q, context)
        if data == "qn:srcbank":
            return await handlers_admin.cb_qn_bank(q, context)
        if data == "qn:bankadd":
            return await handlers_admin.cb_qn_bank_add(q, context)
        if data == "qn:bankdel":
            return await handlers_admin.cb_qn_bank_del(q, context)
        if data == "qn:bankdone":
            return await handlers_admin.cb_qnev(q, context)
        if data == "qn:del":
            return await handlers_admin.cb_qn_delete(q, context)
        if data == "qn:delok":
            return await handlers_admin.cb_qn_delete_ok(q, context)
        if data == "qnv:results":
            return await handlers_admin.cb_qn_results(q, context)
        if data == "qn:cancelwiz":
            return await handlers_admin.cb_qn_cancel_wiz(q, context)
        if data == "qn:countall":
            return await handlers_admin.cb_qn_count(q, context, True)
        if data.startswith("qn:countn:"):
            try:
                n = int(data[10:])
            except ValueError:
                return
            return await handlers_admin.cb_qn_count_num(q, context, n)
        if data.startswith("ebcorr:"):
            try:
                idx = int(data[7:])
            except ValueError:
                return
            return await handlers_admin.eb_correct(q, context, idx)
        if data.startswith("qnf:"):
            return await handlers_admin.cb_qn_folder(q, context, data)

        # ---------- نامەی گشتی ----------
        if data == "bcast" or data.startswith("bcast:"):
            return await handlers_admin.cb_bcast(q, context, data)

        if data == "admpgs":
            return await handlers_admin.cb_pages(q, context)
        if data == "ampnew":
            return await handlers_admin.start_new_page(q, context)
        if data.startswith("ampdelok:"):
            return await handlers_admin.confirm_delete_page(q, context, data[9:])
        if data.startswith("ampdelli:"):
            return await handlers_admin.delete_last_item(q, context, data[9:])
        if data.startswith("ampadd:"):
            return await handlers_admin.start_add_item(q, context, data[7:])
        if data.startswith("ampdel:"):
            return await handlers_admin.ask_delete_page(q, context, data[7:])
        if data.startswith("ampg:"):
            return await handlers_admin.cb_page(q, context, data[5:])

        if data == "admadm":
            return await handlers_admin.cb_admins(q, context)
        if data == "admadd":
            return await handlers_admin.start_add_admin(q, context)
        if data.startswith("admdel:"):
            return await handlers_admin.remove_admin(q, context, data[7:])
        if data.startswith("admdeleteok:"):
            return await handlers_admin.cb_admin_delete_ok(q, context, data[12:])
        if data.startswith("admdelete:"):
            return await handlers_admin.cb_admin_delete(q, context, data[10:])
        if data.startswith("admban:"):
            return await handlers_admin.start_admin_ban(q, context, data[7:])

        if data.startswith("amqdelok:"):
            return await handlers_admin.confirm_delete_question(q, context, data[9:])
        if data.startswith("amqdel:"):
            return await handlers_admin.ask_delete_question(q, context, data[7:])
        if data.startswith("amqtext:"):
            return await handlers_admin.start_edit_text(q, context, data[8:])
        if data.startswith("amqimgdel:"):
            return await handlers_admin.remove_image(q, context, data[10:])
        if data.startswith("amqimg:"):
            return await handlers_admin.start_edit_image(q, context, data[7:])
        if data.startswith("amqopt:"):
            parts = data.split(":")
            if len(parts) == 3:
                try:
                    idx = int(parts[2])
                except ValueError:
                    return
                return await handlers_admin.start_edit_option(q, context, parts[1], idx)
            return
        if data.startswith("amqcorrp:"):
            return await handlers_admin.cb_correct_pick(q, context, data[9:])
        if data.startswith("amqcorrset:"):
            parts = data.split(":")
            if len(parts) == 3:
                try:
                    idx = int(parts[2])
                except ValueError:
                    return
                return await handlers_admin.cb_correct_set(q, context, parts[1], idx)
            return
        if data.startswith("amq:"):
            return await handlers_admin.cb_question(q, context, data[4:])

        if data.startswith("amdelyes:"):
            return await handlers_admin.confirm_delete_folder(q, context, data[9:])
        if data.startswith("amdel:"):
            return await handlers_admin.ask_delete_folder(q, context, data[6:])
        if data.startswith("amnew:"):
            return await handlers_admin.start_new_folder(q, context, data[6:])
        if data.startswith("amren:"):
            return await handlers_admin.start_rename(q, context, data[6:])
        if data.startswith("amadd:"):
            return await handlers_admin.start_add_question(q, context, data[6:])
        if data.startswith("am:"):
            return await handlers_admin.cb_folder(q, context, data[3:])

        if data == "setview":
            return await handlers_admin.cb_settings(q, context)
        if data == "setall":
            return await handlers_admin.set_all(q, context)
        if data == "setnum":
            return await handlers_admin.start_set_num(q, context)
        if data == "stats":
            return await handlers_admin.cb_stats(q, context)

        if data == "wx:skipimg":
            return await handlers_admin.wx_skipimg(q, context)
        if data == "wx:done":
            return await handlers_admin.wx_done(q, context)
        if data == "wx:cancel":
            return await handlers_admin.wx_cancel(q, context)
        if data.startswith("wxcorr:"):
            try:
                idx = int(data[7:])
            except ValueError:
                return
            return await handlers_admin.wx_correct(q, context, idx)

        return
    except Exception as e:
        log.error("callback error (%s): %s", data, e, exc_info=True)
        try:
            await handlers_user.alert(q, T.ERR)
        except Exception:
            pass


# ---------------- مسڕەری پەیامەکان ----------------

# فڵۆوەکانی ئادمین — تەنها بۆ ئادمینەکان
ADMIN_FLOWS = {"addq", "qnbank", "newfolder", "rename", "newpage", "additem",
               "addadmin", "setnum", "editqtext", "editqimg", "editqopt", "tkreply",
               "impfile", "rpreply", "usrsearch", "qnev", "qntime", "qnsrc", "usrmsg",
               "usrban", "bcast", "menulabel", "menuextra", "pqrev"}

# فڵۆوەکان کە لە route_wizard_extra دا مامەڵەیان لەگەڵ دەکرێت
ADMIN_EXTRA_FLOWS = {"rpreply", "usrsearch", "qnev", "qntime", "qnsrc", "usrmsg",
                     "usrban", "bcast"}

# فڵۆوەکانی بەکارهێنەری ئاسایی
USER_FLOWS = {"reg", "ask", "quiznum", "report", "fcadd", "mq"}


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.from_user:
        return
    storage = context.bot_data["storage"]
    try:
        # ---------- دەرگای باند: بەکارهێنەری باندکراو هیچ ناتوانێت ----------
        if await handlers_user.reject_banned(update, context):
            return

        w = storage.get_wizard(msg.chat_id)
        if w:
            flow = w.get("flow")
            # فلۆوی بەکارهێنەر
            if flow in USER_FLOWS:
                return await handlers_user.route_wizard(update, context, w)
            # فلۆوی ئادمین — کلاسیک یان زیادکراو
            if flow in ADMIN_FLOWS and storage.is_admin(msg.from_user.id):
                if flow in ADMIN_EXTRA_FLOWS:
                    return await handlers_admin.route_wizard_extra(update, context, w)
                return await handlers_admin.route_wizard(update, context, w)

        if msg.text:
            return await msg.reply_text(T.HINT_START, reply_markup=K.home_only())
        return await msg.reply_text(T.HINT_START, reply_markup=K.home_only())
    except Exception as e:
        log.error("message error: %s", e, exc_info=True)
        try:
            await msg.reply_text(T.ERR)
        except Exception:
            pass


# ---------------- خاڵی دەستپێک ----------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    missing = config.validate()
    if missing:
        log.error("ئەم گۆڕاوە ژینگەییانە سن نەنراون: %s", ", ".join(missing))
        log.error("لە GitHub Actions: Settings → Secrets and variables → Actions")
        sys.exit(1)

    storage = Storage(config.DB_PATH)
    gitsync = GitSync(config.PROJECT_DIR, config.GIT_PUSH_DEBOUNCE)
    storage.on_change = gitsync.notify

    # پاراستنی ناوەڕۆک: هیچ پەیامێک ناتوانرێت forward/save بکرێت
    defaults = Defaults(protect_content=True)

    # خێرایی: pool ی گەورەتر بۆ وەڵامدانەوەی چەندین بەکارهێنەر لە یەک چرکەدا
    request = HTTPXRequest(connection_pool_size=64, pool_timeout=10.0,
                           connect_timeout=15.0, read_timeout=20.0,
                           write_timeout=20.0, media_write_timeout=120.0)

    app = (Application.builder()
           .token(config.BOT_TOKEN)
           .defaults(defaults)
           .request(request)
           .concurrent_updates(True)
           .post_init(_post_init)
           .post_shutdown(_on_shutdown)
           .build())

    app.bot_data["storage"] = storage
    app.bot_data["gitsync"] = gitsync
    # تەنها ئادمین بتوانێت forward/save/copy بکات — پەیامەکانی ئادمین پارێزراو نین
    exempt_admin_sends(app, storage)
    app.add_error_handler(_error)

    app.add_handler(CommandHandler(["start", "menu"], handlers_user.cmd_start))
    app.add_handler(CommandHandler(["help"], handlers_user.cmd_help))
    app.add_handler(CommandHandler(["admin"], handlers_admin.cmd_admin))
    app.add_handler(CommandHandler(["cancel"], handlers_admin.cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ((filters.TEXT & ~filters.COMMAND)
                                    | filters.PHOTO | filters.Document.ALL),
        on_message))

    # خشتەی تاقیکردنەوەی شەوانە — هەر ٢٠ چرکە
    if app.job_queue:
        app.job_queue.run_repeating(_event_tick, interval=20, first=10)

    app.job_queue.run_once(_auto_stop, when=config.POLL_SECONDS)
    log.info("بۆت کاری خۆی دەست پێکرد (POLL_SECONDS=%s چرکە — مۆدی ٢٤/٧)...",
             config.POLL_SECONDS)
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
