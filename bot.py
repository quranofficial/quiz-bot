# -*- coding: utf-8 -*-
"""خاڵی دەستپێکی بۆتی کویز — کاری خۆی دەست پێدەکات، دوای POLL_SECONDS چرکە
بە شێوەیەکی ساغلام دەوەستێت (بۆ GitHub Actions کە هەر ٥ خولەک جارێک دووبارە
دەست پێدەکاتەوە و داتاکان لە ڕیپۆکەدا پارێزراون)."""

import asyncio
import inspect
import logging
import os
import sys

from telegram import BotCommand, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import config
import handlers_admin
import handlers_user
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
        await app.bot.set_my_commands([
            BotCommand("start", "دەستپێکردن"),
            BotCommand("admin", "پانێڵی ئادمین"),
            BotCommand("help", "ڕێنمایی"),
        ])
    except Exception as e:
        log.warning("set_my_commands: %s", e)
    log.info("بۆت ئامادەیە ✅")


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
        # ---------- گشتی ----------
        if data == "noop":
            return
        if data == "home":
            return await handlers_user.cb_home(q, context)
        if data.startswith("nav:"):
            return await handlers_user.cb_nav(q, context, data[4:])
        if data.startswith("quiz:"):
            return await handlers_user.cb_quiz(q, context, data[5:])
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

        # ---------- ئادمین ----------
        if not storage.is_admin(q.from_user.id):
            return await handlers_user.alert(q, T.ADMIN_ONLY)

        if data == "adm":
            return await handlers_admin.cb_home(q, context)

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

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.from_user:
        return
    storage = context.bot_data["storage"]
    try:
        text = msg.text or ""

        if storage.is_admin(msg.from_user.id):
            w = storage.get_wizard(msg.chat_id)
            if w:
                return await handlers_admin.route_wizard(update, context, w)

        if text:
            return await msg.reply_text(T.HINT_START)
        return await msg.reply_text(T.HINT_START)
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

    app = (Application.builder()
           .token(config.BOT_TOKEN)
           .post_init(_post_init)
           .post_shutdown(_on_shutdown)
           .build())

    app.bot_data["storage"] = storage
    app.bot_data["gitsync"] = gitsync
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

    app.job_queue.run_once(_auto_stop, when=config.POLL_SECONDS)
    log.info("بۆت کاری خۆی دەست پێکرد (POLL_SECONDS=%s چرکە)...", config.POLL_SECONDS)
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
