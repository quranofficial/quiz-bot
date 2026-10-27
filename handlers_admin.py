# -*- coding: utf-8 -*-
"""پانێڵی ئادمین: بەڕێوەبردنی بەش/پرسیار (بێ سنووری نەوە)، پەڕەکانی زانیاری (کەش)،
ئادمینەکان و ڕێکخستنەکان — دۆخی ویزارد لە داتادا هەڵدەگیرێت تا لەگەڵ
دووبارە دەستپێکردنەکانی GitHub Actions نەمایەوە."""

import asyncio
import html as _html
import logging
import os
import time

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
import fmtutil as fmt
import handlers_user
import keyboards as K
import storage as st
import texts as T

log = logging.getLogger("admin")

# سنوورەکانی هێنانی JSON
JSON_MAX_BYTES = 15 * 1024 * 1024   # ١٥ مێگابایت
JSON_MAX_QUESTIONS = 150


def _storage(context) -> st.Storage:
    return context.bot_data["storage"]


# ---------------- واژۆی ناوی ئادمین (پاش ٢ چرکە) ----------------

def _schedule_admin_sign(bot, chat_id, message_id, base_text: str,
                         admin_name: str, delay: float = 2.0,
                         html_mode: bool = True, caption: bool = False):
    """پاش ٢ چرکە ناوی ئادمین لە خوارەوەی پەیامەکە زیاد دەکات (بە بێ بلۆککردن).
    html_mode: ئەگەر دەقە سەرەتاییەکە بە HTML نێردرابێت.
    caption: ئەگەر پەیامەکە وێنە بێت (کاپشن)."""
    async def _job():
        try:
            await asyncio.sleep(delay)
            name = (_html.escape(admin_name or "") if html_mode
                    else (admin_name or ""))
            text = (base_text or "") + T.ADMIN_SIGN.format(name=name)
            parse = "HTML" if html_mode else None
            if caption:
                await bot.edit_message_caption(chat_id=chat_id,
                                               message_id=message_id,
                                               caption=text, parse_mode=parse)
            else:
                await bot.edit_message_text(chat_id=chat_id,
                                            message_id=message_id,
                                            text=text, parse_mode=parse)
        except Exception:
            pass
    try:
        asyncio.create_task(_job())
    except Exception:
        pass


# ---------------- فەرمانەکان ----------------

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage = _storage(context)
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    if not storage.is_admin(user.id):
        await msg.reply_text(T.ADMIN_ONLY)
        return
    if update.effective_chat:
        storage.clear_wizard(update.effective_chat.id)
    # دوگمەکانی فەرمان بۆ ئادمین: /admin + /start + /help (یەک جار بۆ هەر چاتێک)
    if not context.bot_data.get("cmds_set_{}".format(user.id)):
        await ensure_admin_commands(context.bot, user.id)
        context.bot_data["cmds_set_{}".format(user.id)] = True
    await msg.reply_text(
        T.ADMIN_HOME.format(users=st.knum(storage.count_users()),
                            tickets=st.knum(storage.count_open_tickets()),
                            reports=st.knum(storage.count_open_reports())),
        reply_markup=K.admin_main(storage.count_open_tickets(),
                                  storage.count_open_reports(),
                                  storage.count_users(),
                                  storage.count_pending_questions()))


async def ensure_admin_commands(bot, chat_id):
    """دوگمەکانی فەرمان بۆ چاتی ئادمین — /admin + /start + /help."""
    try:
        await bot.set_my_commands(
            [BotCommand("admin", "پانێڵی ئادمین"),
             BotCommand("start", "دەستپێکردن"),
             BotCommand("help", "ڕێنمایی")],
            scope=BotCommandScopeChat(chat_id))
    except Exception:
        pass


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handlers_user.reject_banned(update, context):
        return
    storage = _storage(context)
    chat, msg = update.effective_chat, update.effective_message
    if not chat or not msg:
        return
    if storage.get_wizard(chat.id):
        storage.clear_wizard(chat.id)
        await msg.reply_text(T.WIZ_CANCELLED)
    else:
        await msg.reply_text(T.HINT_START)


# ---------------- بینینی پانێڵ و بەشەکان ----------------

async def cb_home(query, context):
    storage = _storage(context)
    await handlers_user.edit_message(
        query,
        T.ADMIN_HOME.format(users=st.knum(storage.count_users()),
                            tickets=st.knum(storage.count_open_tickets()),
                            reports=st.knum(storage.count_open_reports())),
        K.admin_main(storage.count_open_tickets(),
                     storage.count_open_reports(),
                     storage.count_users(),
                     storage.count_pending_questions()))


async def cb_folder(query, context, fid: str):
    storage = _storage(context)
    tree = storage.db()["tree"]
    if fid in ("", "root"):
        folders = st.count_folders_in(tree)
        total = sum(st.count_questions(n) for n in tree)
        text = (T.A_TREE_ROOT + "\n\n"
                + T.A_TREE_STATS.format(f=st.knum(folders), q=st.knum(total)))
        kb = K.admin_folder(None, None, tree)
    else:
        folder = st.find_node(tree, fid)
        if not folder or folder.get("type") != "folder":
            return await handlers_user.alert(query, T.GONE)
        parent = st.find_parent_folder_id(tree, fid)
        children = folder.get("children", [])
        subs = sum(1 for c in children if c.get("type") == "folder")
        direct = sum(1 for c in children if c.get("type") == "question")
        text = T.A_FOLDER_VIEW.format(
            title=folder.get("title", "?"),
            subs=st.knum(subs), direct=st.knum(direct),
            total=st.knum(st.count_questions(folder)))
        kb = K.admin_folder(folder, None if parent in (None, "root") else parent, tree)
    await handlers_user.edit_message(query, text, kb)


async def cb_question(query, context, qid: str):
    storage = _storage(context)
    tree = storage.db()["tree"]
    q = st.find_node(tree, qid)
    if not q or q.get("type") != "question":
        return await handlers_user.alert(query, T.Q_GONE)
    parent = st.find_parent_folder_id(tree, qid) or "root"
    opt_rows = []
    corr = T.CORRECT_NONE
    for i, o in enumerate(q.get("options", [])):
        opt_rows.append("{}) {} {}".format(st.LETTERS[i], o.get("text", ""),
                                           "✅" if o.get("correct") else "⬜"))
        if o.get("correct"):
            corr = st.LETTERS[i]
    text = T.Q_VIEW.format(
        text=q.get("text") or T.RESULT_IMG,
        img=("بەڵێ ✅" if q.get("image") else "نەخێر ❌"),
        opts="\n".join(opt_rows) or "—",
        corr=corr)
    await handlers_user.edit_message(query, text, K.admin_question(q, parent))


# ---------------- سڕینەوەکان ----------------

async def ask_delete_folder(query, context, fid: str):
    storage = _storage(context)
    tree = storage.db()["tree"]
    folder = st.find_node(tree, fid)
    if not folder or folder.get("type") != "folder":
        return await handlers_user.alert(query, T.GONE)
    parent = st.find_parent_folder_id(tree, fid)
    text = T.CONFIRM_DEL_FOLDER.format(
        title=folder.get("title", "?"),
        subs=st.knum(st.count_folders_in([folder])),
        qs=st.knum(st.count_questions(folder)))
    await handlers_user.edit_message(
        query, text, K.confirm_kb("amdelyes:{}".format(fid), "am:{}".format(parent or "root")))


async def confirm_delete_folder(query, context, fid: str):
    _storage(context).delete_folder(fid)
    await handlers_user.alert(query, T.DELETED)
    await cb_folder(query, context, "root")


async def ask_delete_question(query, context, qid: str):
    storage = _storage(context)
    tree = storage.db()["tree"]
    q = st.find_node(tree, qid)
    if not q:
        return await handlers_user.alert(query, T.Q_GONE)
    parent = st.find_parent_folder_id(tree, qid) or "root"
    await handlers_user.edit_message(
        query, T.CONFIRM_DEL_QUESTION,
        K.confirm_kb("amqdelok:{}".format(qid), "am:{}".format(parent)))


async def confirm_delete_question(query, context, qid: str):
    storage = _storage(context)
    parent = st.find_parent_folder_id(storage.db()["tree"], qid) or "root"
    storage.delete_question(qid)
    await handlers_user.alert(query, T.DELETED)
    await cb_folder(query, context, parent)


async def ask_delete_page(query, context, pid: str):
    page = next((p for p in _storage(context).db()["pages"] if p.get("id") == pid), None)
    if not page:
        return await handlers_user.alert(query, T.PAGE_GONE)
    await handlers_user.edit_message(
        query, T.CONFIRM_DEL_PAGE.format(title=page.get("title", "?")),
        K.confirm_kb("ampdelok:{}".format(pid), "ampg:{}".format(pid)))


async def confirm_delete_page(query, context, pid: str):
    _storage(context).delete_page(pid)
    await handlers_user.alert(query, T.DELETED)
    await cb_pages(query, context)


async def delete_last_item(query, context, pid: str):
    storage = _storage(context)
    storage.delete_last_item(pid)
    await cb_page(query, context, pid)


# ---------------- پەڕەکان (ئادمین) ----------------

async def cb_pages(query, context):
    await handlers_user.edit_message(query, T.A_PAGES, K.admin_pages(_storage(context).db()["pages"]))


async def cb_page(query, context, pid: str):
    pages = _storage(context).db()["pages"]
    page = next((p for p in pages if p.get("id") == pid), None)
    if not page:
        return await handlers_user.alert(query, T.PAGE_GONE)
    items = page.get("items", [])
    if items:
        type_names = {"text": T.ITEM_TEXT, "photo": T.ITEM_PHOTO, "document": T.ITEM_DOC}
        lines = []
        for i, it in enumerate(items, 1):
            snippet = st.trunc(it.get("content", ""), 30) if it.get("type") == "text" else ""
            lines.append("{}. {} {}".format(st.knum(i), type_names.get(it.get("type"), "?"), snippet))
        items_txt = "\n".join(lines)
    else:
        items_txt = T.PAGE_ITEMS_EMPTY
    text = T.PAGE_VIEW.format(title=page.get("title", "?"),
                              n=st.knum(len(items)), items=items_txt)
    await handlers_user.edit_message(query, text, K.admin_page(page))


# ---------------- ئادمینەکان / ڕێکخستن / ئامار ----------------

async def cb_admins(query, context):
    storage = _storage(context)
    admins = storage.db()["admins"]
    lines = []
    if config.OWNER_ID is not None:
        u = storage.get_user(config.OWNER_ID) or {}
        name = st.trunc(u.get("name") or T.ADMIN_NAME_UNKNOWN, 26)
        lines.append(T.ADMIN_ROW_OWNER.format(name=name, uid=config.OWNER_ID))
    others = [a for a in admins if a != config.OWNER_ID]
    if others:
        for a in others:
            u = storage.get_user(a) or {}
            name = st.trunc(u.get("name") or T.ADMIN_NAME_UNKNOWN, 26)
            lines.append(T.ADMIN_ROW.format(uid=a, name=name))
    elif config.OWNER_ID is None:
        lines.append(T.ADMIN_ROW_NONE)
    await handlers_user.edit_message(
        query, T.A_ADMINS.format(list="\n".join(lines)), K.admins_kb(admins, config.OWNER_ID))


async def remove_admin(query, context, uid_raw: str):
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    if uid is None:
        return
    if config.OWNER_ID is not None and uid == config.OWNER_ID:
        return await handlers_user.alert(query, T.A_ONLY_OWNER)
    storage.remove_admin(uid)
    await handlers_user.alert(query, T.ADMIN_REMOVED)
    await cb_admins(query, context)


async def cb_settings(query, context):
    storage = _storage(context)
    qpq = storage.db()["settings"].get("questions_per_quiz", 0) or 0
    val = T.SET_ALL_VALUE if qpq <= 0 else st.knum(qpq)
    text = T.A_SETTINGS.format(v=val)
    await handlers_user.edit_message(query, text, K.settings_kb())


async def set_all(query, context):
    _storage(context).set_questions_per_quiz(0)
    await handlers_user.alert(query, T.SET_ALL_SAVED)
    await cb_settings(query, context)


async def cb_stats(query, context):
    storage = _storage(context)
    db = storage.db()
    folders, questions = st.tree_stats(db["tree"])
    n_admins = len(db["admins"]) + (1 if config.OWNER_ID is not None else 0)
    text = T.A_STATS.format(
        folders=st.knum(folders), questions=st.knum(questions),
        pages=st.knum(len(db["pages"])), admins=st.knum(n_admins),
        users=st.knum(storage.count_users()),
        tickets=st.knum(storage.count_open_tickets()),
        sessions=st.knum(len(db["sessions"])))
    await handlers_user.edit_message(query, text, K.back_to_panel_kb())


# ---------------- ویزارد: دەستپێکردنەکان ----------------

async def _edit_prompt(context, chat_id, w, text, kb):
    """پەیامی ڕێنمایی ویزارد دەنێرێت/نوێی دەکاتەوە و ID ی هەڵدەگرێت."""
    storage = _storage(context)
    mid = (w.get("data") or {}).get("prompt")
    if mid:
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=mid,
                                                text=text, reply_markup=kb)
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
        except Exception:
            pass
    try:
        m = await context.bot.send_message(chat_id, text, reply_markup=kb)
    except Exception as e:
        log.warning("ناردنی prompt سەرکەوتوو نەبوو: %s", e)
        return
    w.setdefault("data", {})["prompt"] = m.message_id
    storage.set_wizard(chat_id, w)


def _set_step(storage, chat, w, step):
    w["step"] = step
    storage.set_wizard(chat, w)


async def start_add_question(query, context, fid: str):
    storage = _storage(context)
    if fid in ("", "root"):
        return await handlers_user.alert(query, T.NEED_FOLDER_FIRST)
    if not st.find_node(storage.db()["tree"], fid):
        return await handlers_user.alert(query, T.GONE)
    chat = query.message.chat_id
    w = {"flow": "addq", "step": "image",
         "data": {"folder_id": fid, "image": None, "text": "", "options": []}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_Q_IMAGE, K.wiz_image_kb())


async def start_new_folder(query, context, parent: str):
    storage = _storage(context)
    chat = query.message.chat_id
    w = {"flow": "newfolder", "step": "title", "data": {"parent": parent or "root"}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_NEW_FOLDER, K.wiz_cancel_kb())


async def start_rename(query, context, fid: str):
    storage = _storage(context)
    if not st.find_node(storage.db()["tree"], fid):
        return await handlers_user.alert(query, T.GONE)
    chat = query.message.chat_id
    w = {"flow": "rename", "step": "title", "data": {"fid": fid}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_RENAME, K.wiz_cancel_kb())


async def start_new_page(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    w = {"flow": "newpage", "step": "title", "data": {}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_NEW_PAGE, K.wiz_cancel_kb())


async def start_add_item(query, context, pid: str):
    storage = _storage(context)
    if not any(p.get("id") == pid for p in storage.db()["pages"]):
        return await handlers_user.alert(query, T.PAGE_GONE)
    chat = query.message.chat_id
    w = {"flow": "additem", "step": "content", "data": {"pid": pid}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_ADD_ITEM, K.wiz_cancel_kb())


async def start_add_admin(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    w = {"flow": "addadmin", "step": "id", "data": {}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_ADD_ADMIN, K.wiz_cancel_kb())


async def start_set_num(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    w = {"flow": "setnum", "step": "num", "data": {}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_SETNUM, K.wiz_cancel_kb())


async def start_edit_text(query, context, qid: str):
    storage = _storage(context)
    if not st.find_node(storage.db()["tree"], qid):
        return await handlers_user.alert(query, T.Q_GONE)
    chat = query.message.chat_id
    w = {"flow": "editqtext", "step": "text", "data": {"qid": qid}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_EDIT_TEXT, K.wiz_cancel_kb())


async def start_edit_image(query, context, qid: str):
    storage = _storage(context)
    if not st.find_node(storage.db()["tree"], qid):
        return await handlers_user.alert(query, T.Q_GONE)
    chat = query.message.chat_id
    w = {"flow": "editqimg", "step": "image", "data": {"qid": qid}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_EDIT_IMG, K.wiz_editimg_kb(qid))


async def start_edit_option(query, context, qid: str, idx: int):
    """دەستکاری دەقی هەڵبژاردەیەک (A/B/C/D) لە پرسیارێکدا."""
    storage = _storage(context)
    q = st.find_node(storage.db()["tree"], qid)
    if not q or q.get("type") != "question":
        return await handlers_user.alert(query, T.Q_GONE)
    options = q.get("options") or []
    if idx < 0 or idx >= len(options):
        return await handlers_user.alert(query, T.Q_GONE)
    chat = query.message.chat_id
    w = {"flow": "editqopt", "step": "text",
         "data": {"qid": qid, "idx": idx}}
    storage.set_wizard(chat, w)
    await _edit_prompt(
        context, chat, w,
        T.WIZ_EDIT_OPT.format(letter=st.LETTERS[idx],
                              cur=st.trunc(options[idx].get("text", ""), 120)),
        K.wiz_cancel_kb())


async def cb_correct_pick(query, context, qid: str):
    """شاشەی هەڵبژاردنی وەڵامی ڕاست بۆ پرسیارێک."""
    storage = _storage(context)
    q = st.find_node(storage.db()["tree"], qid)
    if not q or q.get("type") != "question":
        return await handlers_user.alert(query, T.Q_GONE)
    corr = next((st.LETTERS[i] for i, o in enumerate(q.get("options") or [])
                 if o.get("correct")), T.CORRECT_NONE)
    await handlers_user.edit_message(
        query, T.CORRECT_PICK_VIEW.format(cur=corr), K.correct_pick_kb(q))


async def cb_correct_set(query, context, qid: str, idx: int):
    """دیاریکردنی وەڵامی ڕاست — هەموو ئەوانی تر ناڕاست دەبن."""
    storage = _storage(context)
    q = st.find_node(storage.db()["tree"], qid)
    if not q or q.get("type") != "question":
        return await handlers_user.alert(query, T.Q_GONE)
    options = q.get("options") or []
    if idx < 0 or idx >= len(options):
        return await handlers_user.alert(query, T.WIZ_INVALID_NUM)
    storage.set_question_correct(qid, idx)
    await handlers_user.alert(query, T.CORRECT_SAVED.format(letter=st.LETTERS[idx]))
    await cb_question(query, context, qid)


async def remove_image(query, context, qid: str):
    storage = _storage(context)
    storage.set_question_image(qid, None)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if w and w.get("flow") == "editqimg":
        storage.clear_wizard(chat)
    await handlers_user.alert(query, T.WIZ_IMG_REMOVED)
    await cb_question(query, context, qid)


# ---------------- ویزارد: وەڵامدانەوەی پەیامەکان ----------------

def _opts_list(options) -> str:
    if not options:
        return T.WIZ_Q_OPTIONS_EMPTY
    return "\n".join("{}) {}".format(st.LETTERS[i], o.get("text", ""))
                     for i, o in enumerate(options))


async def route_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, w: dict):
    msg = update.message
    if not msg or not msg.from_user:
        return
    storage = _storage(context)
    if not storage.is_admin(msg.from_user.id):
        return
    chat = msg.chat_id
    flow, step = w.get("flow"), w.get("step")
    data = w.setdefault("data", {})

    if flow == "addq":
        if step == "image":
            if msg.photo:
                data["image"] = msg.photo[-1].file_id
                cap = (msg.caption or "").strip()
                if cap:
                    data["text"] = cap[:3500]
                    _set_step(storage, chat, w, "options")
                    await _edit_prompt(context, chat, w,
                                       T.WIZ_Q_OPTIONS.format(opts=T.WIZ_Q_OPTIONS_EMPTY),
                                       K.wiz_options_kb(0))
                else:
                    _set_step(storage, chat, w, "text")
                    await _edit_prompt(context, chat, w, T.WIZ_Q_TEXT, None)
            else:
                await msg.reply_text(T.WIZ_NEED_PHOTO)
        elif step == "text":
            if msg.text and msg.text.strip():
                data["text"] = msg.text.strip()[:3500]
                _set_step(storage, chat, w, "options")
                await _edit_prompt(context, chat, w,
                                   T.WIZ_Q_OPTIONS.format(opts=T.WIZ_Q_OPTIONS_EMPTY),
                                   K.wiz_options_kb(0))
            else:
                await msg.reply_text(T.WIZ_NEED_TEXT)
        elif step == "options":
            if msg.text and msg.text.strip():
                data["options"].append({"text": msg.text.strip()[:200], "correct": False})
                if len(data["options"]) >= 4:
                    _set_step(storage, chat, w, "correct")
                    await _edit_prompt(context, chat, w, T.WIZ_Q_CORRECT,
                                       K.wiz_correct_kb(data["options"]))
                else:
                    storage.set_wizard(chat, w)
                    await _edit_prompt(context, chat, w,
                                       T.WIZ_Q_OPTIONS.format(opts=_opts_list(data["options"])),
                                       K.wiz_options_kb(len(data["options"])))
            else:
                await msg.reply_text(T.WIZ_NEED_TEXT)
        else:
            await msg.reply_text(T.WIZ_USE_BUTTONS)
        return

    if flow == "qnbank":
        # ویزاردی پرسیاری نوێ بۆ بەنکۆی تاقیکردنەوەی شەوانە — وەک addq بەڵام دەچێتە ev["bank"]
        if step == "image":
            if msg.photo:
                data["image"] = msg.photo[-1].file_id
                cap = (msg.caption or "").strip()
                if cap:
                    data["text"] = cap[:3500]
                    _set_step(storage, chat, w, "options")
                    await _edit_prompt(context, chat, w,
                                       T.WIZ_Q_OPTIONS.format(opts=T.WIZ_Q_OPTIONS_EMPTY),
                                       K.wiz_options_kb(0))
                else:
                    _set_step(storage, chat, w, "text")
                    await _edit_prompt(context, chat, w, T.WIZ_Q_TEXT, None)
            else:
                await msg.reply_text(T.WIZ_NEED_PHOTO)
        elif step == "text":
            if msg.text and msg.text.strip():
                data["text"] = msg.text.strip()[:3500]
                _set_step(storage, chat, w, "options")
                await _edit_prompt(context, chat, w,
                                   T.WIZ_Q_OPTIONS.format(opts=T.WIZ_Q_OPTIONS_EMPTY),
                                   K.wiz_options_kb(0))
            else:
                await msg.reply_text(T.WIZ_NEED_TEXT)
        elif step == "options":
            if msg.text and msg.text.strip():
                data["options"].append({"text": msg.text.strip()[:200], "correct": False})
                if len(data["options"]) >= 4:
                    _set_step(storage, chat, w, "correct")
                    await _edit_prompt(context, chat, w, T.WIZ_Q_CORRECT,
                                       K.eb_correct_kb(data["options"]))
                else:
                    storage.set_wizard(chat, w)
                    await _edit_prompt(context, chat, w,
                                       T.WIZ_Q_OPTIONS.format(opts=_opts_list(data["options"])),
                                       K.wiz_options_kb(len(data["options"])))
            else:
                await msg.reply_text(T.WIZ_NEED_TEXT)
        else:
            await msg.reply_text(T.WIZ_USE_BUTTONS)
        return

    if flow == "newfolder":
        if not (msg.text and msg.text.strip()):
            return await msg.reply_text(T.WIZ_NEED_TEXT)
        title = st.trunc(msg.text, 60)
        parent = data.get("parent") or "root"
        storage.add_folder(parent, title)
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_ADDED_FOLDER.format(title=title),
                             reply_markup=K.after_folder_saved_kb(parent))
        return

    if flow == "rename":
        if not (msg.text and msg.text.strip()):
            return await msg.reply_text(T.WIZ_NEED_TEXT)
        title = st.trunc(msg.text, 60)
        fid = data.get("fid")
        storage.rename_folder(fid, title)
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_RENAMED.format(title=title),
                             reply_markup=K.back_to_folder_kb(fid))
        return

    if flow == "newpage":
        if not (msg.text and msg.text.strip()):
            return await msg.reply_text(T.WIZ_NEED_TEXT)
        title = st.trunc(msg.text, 60)
        page = storage.add_page(title)
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_ADDED_PAGE.format(title=title),
                             reply_markup=K.after_page_saved_kb(page["id"]))
        return

    if flow == "additem":
        pid = data.get("pid")
        if msg.text and msg.text.strip():
            storage.add_page_item(pid, "text", msg.text.strip()[:3500])
        elif msg.photo:
            storage.add_page_item(pid, "photo", msg.photo[-1].file_id,
                                  (msg.caption or "").strip() or None)
        elif msg.document:
            storage.add_page_item(pid, "document", msg.document.file_id,
                                  (msg.caption or "").strip() or None)
        else:
            return await msg.reply_text(T.WIZ_NEED_ITEM)
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_ADDED_ITEM, reply_markup=K.after_item_saved_kb(pid))
        return

    if flow == "addadmin":
        if not msg.text:
            return await msg.reply_text(T.WIZ_INVALID_NUM)
        uid = st.to_int(msg.text)
        if uid is None or uid <= 0:
            return await msg.reply_text(T.WIZ_INVALID_NUM)
        added = storage.add_admin(uid)
        storage.clear_wizard(chat)
        if added:
            await ensure_admin_commands(context.bot, uid)
        text = T.WIZ_ADMIN_ADDED.format(uid=uid) if added else T.WIZ_ADMIN_EXISTS
        await msg.reply_text(text, reply_markup=K.back_to_panel_kb())
        return

    if flow == "setnum":
        if not msg.text:
            return await msg.reply_text(T.WIZ_INVALID_NUM)
        n = st.to_int(msg.text)
        if n is None or n < 1 or n > 100:
            return await msg.reply_text(T.WIZ_INVALID_NUM)
        storage.set_questions_per_quiz(n)
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_SAVED_NUM.format(n=st.knum(n)),
                             reply_markup=K.back_to_panel_kb())
        return

    if flow == "editqtext":
        if not (msg.text and msg.text.strip()):
            return await msg.reply_text(T.WIZ_NEED_TEXT)
        storage.set_question_text(data.get("qid"), msg.text.strip()[:3500])
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_TEXT_SAVED,
                             reply_markup=K.back_to_question_kb(data.get("qid")))
        return

    if flow == "editqimg":
        if msg.photo:
            storage.set_question_image(data.get("qid"), msg.photo[-1].file_id)
            storage.clear_wizard(chat)
            await msg.reply_text(T.WIZ_IMG_SAVED,
                                 reply_markup=K.back_to_question_kb(data.get("qid")))
        else:
            await msg.reply_text(T.WIZ_NEED_PHOTO)
        return

    if flow == "tkreply":
        return await _finish_ticket_reply(update, context, w, data)

    if flow == "impfile":
        if step == "file":
            return await _route_impfile(update, context, w, data, msg)
        await msg.reply_text(T.WIZ_USE_BUTTONS)
        return

    if flow == "pqrev":
        # لەم فلۆوەدا تەنها دوگمەکان بەکاردێن — وەڵامی ڕاست بە دوگمە هەڵدەبژێردرێت
        await msg.reply_text(T.PQ_USE_BUTTONS)
        return

    if flow == "editqopt":
        if not (msg.text and msg.text.strip()):
            return await msg.reply_text(T.WIZ_NEED_TEXT)
        try:
            idx = int(data.get("idx", -1))
        except (TypeError, ValueError):
            idx = -1
        ok = storage.set_question_option(data.get("qid"), idx, msg.text.strip()[:200])
        storage.clear_wizard(chat)
        if not ok:
            return await msg.reply_text(T.Q_GONE)
        letter = st.LETTERS[idx] if 0 <= idx < len(st.LETTERS) else "؟"
        await msg.reply_text(T.OPT_SAVED.format(letter=letter),
                             reply_markup=K.back_to_question_kb(data.get("qid")))
        return

    if flow == "menulabel":
        return await _finish_menu_label(update, context, w)

    if flow == "menuextra":
        if step == "title":
            return await _finish_menu_extra(update, context, w)
        await msg.reply_text(T.WIZ_USE_BUTTONS)
        return

    # هیچ لقێک وەڵامی نەدەوە — بێدەنگ مەبە (چارەسەری بڕوان)
    await msg.reply_text(T.WIZ_NEED_TEXT)


# ---------------- ویزارد: دوگمەکان ----------------

def _wiz_of(query, context):
    storage = _storage(context)
    try:
        chat = query.message.chat_id
    except Exception:
        return storage, None, None
    return storage, chat, storage.get_wizard(chat)


async def _wiz_gone(query):
    await handlers_user.alert(query, T.WIZ_GONE)


async def wx_skipimg(query, context):
    storage, chat, w = _wiz_of(query, context)
    if not w or w.get("flow") not in ("addq", "qnbank") or w.get("step") != "image":
        return await _wiz_gone(query)
    _set_step(storage, chat, w, "text")
    await _edit_prompt(context, chat, w, T.WIZ_Q_TEXT, None)


async def wx_done(query, context):
    storage, chat, w = _wiz_of(query, context)
    if not w or w.get("flow") not in ("addq", "qnbank") or w.get("step") != "options":
        return await _wiz_gone(query)
    if len(w["data"].get("options", [])) < 4:
        try:
            await query.message.reply_text(T.WIZ_NEED_FOUR)
        except Exception:
            pass
        return
    _set_step(storage, chat, w, "correct")
    opts = w["data"]["options"]
    kb = K.eb_correct_kb(opts) if w.get("flow") == "qnbank" else K.wiz_correct_kb(opts)
    await _edit_prompt(context, chat, w, T.WIZ_Q_CORRECT, kb)


async def wx_cancel(query, context):
    storage, chat, w = _wiz_of(query, context)
    if not w:
        return await _wiz_gone(query)
    data = w.get("data") or {}
    fid = data.get("folder_id") or data.get("parent") or data.get("fid")
    storage.clear_wizard(chat)
    kb = K.back_to_folder_kb(fid) if fid else K.admin_main()
    try:
        await query.message.reply_text(T.WIZ_CANCELLED, reply_markup=kb)
    except Exception:
        pass


async def wx_correct(query, context, idx: int):
    storage, chat, w = _wiz_of(query, context)
    if not w or w.get("flow") != "addq" or w.get("step") != "correct":
        return await _wiz_gone(query)
    options = w["data"].get("options", [])
    if idx < 0 or idx >= len(options):
        return await _wiz_gone(query)
    options[idx]["correct"] = True
    fid = w["data"].get("folder_id")
    folder = st.find_node(storage.db()["tree"], fid)
    storage.add_question(fid, w["data"].get("text") or "", w["data"].get("image"), options)
    storage.clear_wizard(chat)
    await query.message.reply_text(
        T.WIZ_Q_SAVED.format(folder=(folder or {}).get("title", "-")),
        reply_markup=K.after_question_saved_kb(fid))


async def eb_correct(query, context, idx: int):
    """هەڵبژاردنی وەڵامی ڕاست بۆ پرسیاری بەنکۆی شەوانە — پاشەکەوت لە ev["bank"]."""
    storage, chat, w = _wiz_of(query, context)
    if not w or w.get("flow") != "qnbank" or w.get("step") != "correct":
        return await _wiz_gone(query)
    options = w["data"].get("options", [])
    if idx < 0 or idx >= len(options):
        return await _wiz_gone(query)
    options[idx]["correct"] = True
    q = {"id": st.new_id("eb"), "type": "question",
         "text": w["data"].get("text") or "",
         "image": w["data"].get("image"),
         "options": options}
    n = storage.add_event_bank_question(q)
    storage.clear_wizard(chat)
    await query.message.reply_text(
        T.A_QN_BANK_SAVED.format(n=st.knum(n)),
        reply_markup=K.after_bank_saved_kb())


# ---------------- پرسیارەکانی بەکارهێنەران (پرسیار بکە) ----------------

def _ticket_status_text(ticket) -> str:
    if ticket.get("status") == "closed":
        return T.TK_STATUS_CLOSED
    if ticket.get("status") == "replied":
        return T.TK_STATUS_REPLIED.format(n=st.knum(len(ticket.get("replies", []))))
    return T.TK_STATUS_OPEN


def _ticket_admin_text(ticket) -> str:
    return (T.TICKET_ADMIN.format(
        id=st.knum(ticket.get("id", 0)),
        name=ticket.get("name") or "—",
        username=ticket.get("username") or "—",
        uid=ticket.get("uid") or "—",
        teacher=ticket.get("_teacher_name") or "—",
        is_t=("بەڵێ ✅" if ticket.get("teacher") else "نەخێر ❌"),
        path=" › ".join(ticket.get("path") or []) or "—",
        text=ticket.get("text") or T.RESULT_IMG)
        + "\n\n" + _ticket_status_text(ticket))


def _ticket_caption(ticket) -> str:
    return (T.TICKET_ADMIN.format(
        id=st.knum(ticket.get("id", 0)),
        name=ticket.get("name") or "—",
        username=ticket.get("username") or "—",
        uid=ticket.get("uid") or "—",
        teacher=ticket.get("_teacher_name") or "—",
        is_t=("بەڵێ ✅" if ticket.get("teacher") else "نەخێر ❌"),
        path=" › ".join(ticket.get("path") or []) or "—",
        text="") + "\n\n" + _ticket_status_text(ticket))


async def notify_new_ticket(context: ContextTypes.DEFAULT_TYPE, ticket: dict):
    """پرسیاری نوێ بۆ هەموو ئادمینەکان دەنێرێت و ID ی پەیامەکان هەڵدەگرێت."""
    storage = _storage(context)
    ticket["_teacher_name"] = storage.get_teacher_name()
    text = _ticket_admin_text(ticket)
    kb = K.ticket_kb(ticket["id"])
    photo = ticket.get("photo")
    for aid in storage.all_admin_ids():
        try:
            sent = None
            if photo and len(text) <= 900:
                sent = await fmt.send_photo_html(context.bot, aid, photo, text,
                                                 reply_markup=kb)
            else:
                sent = await fmt.send_html(context.bot, aid, text, reply_markup=kb)
                if photo:
                    try:
                        await context.bot.send_photo(aid, photo,
                                                     caption="🖼 وێنەی پرسیار #{})".format(
                                                         st.knum(ticket["id"])))
                    except Exception:
                        pass
            if sent:
                ticket.setdefault("admin_msgs", {})[str(aid)] = {
                    "chat": aid, "mid": sent.message_id, "photo": bool(photo and len(text) <= 900),
                }
        except Exception as e:
            log.warning("ناردنی تیکی بۆ ئادمینی %s سەرکەوتوو نەبوو: %s", aid, e)
    ticket.pop("_teacher_name", None)
    storage.save_ticket(ticket)


async def _refresh_admin_msgs(context: ContextTypes.DEFAULT_TYPE, ticket: dict):
    """دۆخی پرسیارەکە لە پەیامە ئادمینەکاندا نوێ دەکاتەوە."""
    storage = _storage(context)
    ticket["_teacher_name"] = storage.get_teacher_name()
    text = _ticket_admin_text(ticket)
    kb = K.ticket_kb(ticket["id"])
    for key in list((ticket.get("admin_msgs") or {}).keys()):
        info = ticket["admin_msgs"][key]
        try:
            if info.get("photo"):
                await context.bot.edit_message_caption(
                    chat_id=info["chat"], message_id=info["mid"],
                    caption=text, reply_markup=kb)
            else:
                await context.bot.edit_message_text(
                    chat_id=info["chat"], message_id=info["mid"],
                    text=text, reply_markup=kb)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                log.info("نوێکردنەوەی پەیامی ئادمین نەکرا: %s", e)
        except Exception:
            pass
    ticket.pop("_teacher_name", None)
    storage.save_ticket(ticket)


async def cb_tickets(query, context):
    storage = _storage(context)
    tickets = storage.open_tickets()
    if not tickets:
        return await handlers_user.alert(query, T.A_TICKETS_EMPTY, K.back_to_panel_kb())
    await handlers_user.edit_message(
        query, T.A_TICKETS_TITLE.format(n=st.knum(len(tickets))),
        K.tickets_list_kb(tickets))


async def _send_ticket_view(query, context, ticket: dict):
    storage = _storage(context)
    ticket["_teacher_name"] = storage.get_teacher_name()
    text = _ticket_admin_text(ticket)
    kb = K.ticket_kb(ticket["id"])
    photo = ticket.get("photo")
    ticket.pop("_teacher_name", None)
    try:
        if photo and len(text) <= 900:
            await fmt.send_photo_html(context.bot, query.message.chat_id, photo, text,
                                      reply_markup=kb)
        else:
            await fmt.send_html(context.bot, query.message.chat_id, text, reply_markup=kb)
            if photo:
                try:
                    await context.bot.send_photo(
                        query.message.chat_id, photo,
                        caption="🖼 وێنەی پرسیار #{})".format(st.knum(ticket["id"])))
                except Exception:
                    pass
    except Exception:
        pass


async def cb_ticket(query, context, payload: str):
    storage = _storage(context)
    parts = payload.split(":")
    if len(parts) != 2 or parts[0] not in ("view", "reply", "close"):
        return
    action, tid_raw = parts[0], parts[1]
    tid = st.to_int(tid_raw)
    ticket = storage.get_ticket(tid) if tid is not None else None
    if not ticket:
        return await handlers_user.alert(query, T.TK_GONE)

    if action == "view":
        return await _send_ticket_view(query, context, ticket)

    if action == "close":
        ticket["status"] = "closed"
        storage.save_ticket(ticket)
        await handlers_user.alert(query, T.TK_CLOSED_MSG)
        await _refresh_admin_msgs(context, ticket)
        return

    if action == "reply":
        chat = query.message.chat_id
        storage.set_wizard(chat, {"flow": "tkreply", "step": "msg",
                                  "data": {"tid": tid}})
        await handlers_user.alert(query, T.TK_REPLY_PROMPT.format(id=st.knum(tid)))


async def _finish_ticket_reply(update, context, w: dict, data: dict):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    tid = data.get("tid")
    ticket = storage.get_ticket(tid)
    if not ticket:
        storage.clear_wizard(chat)
        return await msg.reply_text(T.TK_GONE)

    text = (msg.text or msg.caption or "").strip()
    photo = msg.photo[-1].file_id if msg.photo else None
    if not text and not photo:
        return await msg.reply_text(T.WIZ_NEED_TEXT)

    admin_name = (msg.from_user.first_name or "ئادمین").strip()
    # پرسیارەکەی بەکارهێنەر لە سەرەتای وەڵامەکە دەنووسرێت
    qtext = fmt.plain(ticket.get("text") or "")
    q_label = st.trunc(qtext, 600) if qtext else (
        "🖼 (وێنە)" if ticket.get("photo") else "—")
    reply_part = (fmt.apply(text) if text else ("🖼 (وێنە)" if photo else "—"))
    head = T.USER_REPLY_HEAD.format(id=st.knum(tid), q=fmt.apply(q_label),
                                    reply=reply_part)
    if len(head) > 1000:
        head = T.USER_REPLY_HEAD.format(id=st.knum(tid),
                                        q=fmt.apply(st.trunc(qtext, 120)),
                                        reply=reply_part)
    delivered = False
    sent_msg = None
    try:
        if photo:
            sent_msg = await fmt.send_photo_html(context.bot, ticket.get("uid"), photo,
                                                 head or "🖼", )
        else:
            sent_msg = await fmt.send_html(context.bot, ticket.get("uid"), head)
        delivered = True
    except Exception as e:
        log.warning("ناردنی وەڵام بۆ بەکارهێنەر: %s", e)
    if delivered and sent_msg:
        # پاش ٢ چرکە ناوی ئادمین لە خوارەوەی وەڵامەکە دەنووسرێت
        _schedule_admin_sign(context.bot, ticket.get("uid"), sent_msg.message_id,
                             head or "🖼", admin_name, caption=bool(photo))

    ticket.setdefault("replies", []).append({
        "by": msg.from_user.id, "name": admin_name,
        "text": text, "photo": photo, "at": int(time.time()),
    })
    ticket["status"] = "replied"
    storage.clear_wizard(chat)
    storage.save_ticket(ticket)
    await _refresh_admin_msgs(context, ticket)

    if delivered:
        await msg.reply_text(T.TK_DELIVERED.format(name=ticket.get("name") or "—"),
                             reply_markup=K.back_to_panel_kb())
    else:
        await msg.reply_text(T.TK_USER_GONE)


# ---------------- هێنانی پرسیار بە JSON ----------------

async def cb_impfile(query, context):
    """دەستپێکردنی هێنان: سەرەتا بەش و کەرتەکە هەڵبژێرە کە پرسیارەکانی بۆ زیاد دەکرێت."""
    storage = _storage(context)
    chat = query.message.chat_id
    tree = storage.db()["tree"]
    if not tree:
        return await handlers_user.alert(query, T.NO_SECTIONS)
    storage.set_wizard(chat, {"flow": "impfile", "step": "folder",
                              "data": {"path": []}})
    children = [n for n in tree if n.get("type") == "folder"]
    await handlers_user.edit_message(
        query, T.IMP2_PICK,
        K.folder_picker_kb(children, 0, "impf:", "wx:cancel", T.A_QN_BTN_PICK_THIS))


async def cb_impf(query, context, data: str):
    """ڕاوکردنی بەش/کەرت بۆ هێنان: impf:go:<fid> / impf:back / impf:ok"""
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "impfile":
        return await handlers_user.alert(query, T.WIZ_GONE, K.back_to_panel_kb())
    tree = storage.db()["tree"]
    d = w.setdefault("data", {})
    path = d.get("path") or []

    if data == "impf:back":
        if path:
            path.pop()
            d["path"] = path
            storage.set_wizard(chat, w)
        return await _imp_render_folder(query, context, w)

    if data == "impf:ok":
        if not path:
            return await handlers_user.alert(query, T.ASK_NEED_PICK)
        fid = path[-1]
        folder = st.find_node(tree, fid)
        if not folder:
            return await handlers_user.alert(query, T.GONE)
        d["folder_id"] = fid
        d["folder_title"] = folder.get("title", "?")
        w["step"] = "file"
        storage.set_wizard(chat, w)
        # نیشاندانی نموونەی JSON + ناردنی فایلی نموونە — بۆ ئەوەی بەکارهێنەر بزانێت
        # جەمسەرەکە چۆن دەبێت
        try:
            await context.bot.send_document(
                chat, _json_sample_bytes(), filename="sample_questions.json",
                caption=T.IMP2_SAMPLE_FILE)
        except Exception as e:
            log.warning("ناردنی نموونەی JSON: %s", e)
        return await handlers_user.edit_message(query, T.IMP2_SEND, K.imp_json_kb(),
                                                html=True)

    if data.startswith("impf:go:"):
        fid = data[8:]
        node = st.find_node(tree, fid)
        if not node or node.get("type") != "folder":
            return await handlers_user.alert(query, T.GONE)
        path.append(fid)
        d["path"] = path
        storage.set_wizard(chat, w)
        return await _imp_render_folder(query, context, w)


async def _imp_render_folder(query, context, w):
    storage = _storage(context)
    tree = storage.db()["tree"]
    path = (w.get("data") or {}).get("path") or []
    if path:
        node = st.find_node(tree, path[-1])
        children = [c for c in node.get("children", []) if c.get("type") == "folder"]
    else:
        children = [n for n in tree if n.get("type") == "folder"]
    await handlers_user.edit_message(
        query, T.IMP2_PICK,
        K.folder_picker_kb(children, len(path), "impf:", "wx:cancel",
                           T.A_QN_BTN_PICK_THIS))


async def cb_imp_sample(query, context):
    """ناردنەوەی فایلی نموونەی JSON."""
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "impfile":
        return await handlers_user.alert(query, T.WIZ_GONE, K.back_to_panel_kb())
    try:
        await context.bot.send_document(
            chat, _json_sample_bytes(), filename="sample_questions.json",
            caption=T.IMP2_SAMPLE_FILE)
    except Exception as e:
        log.warning("ناردنی نموونەی JSON: %s", e)
    await handlers_user.alert(query, T.IMP2_SAMPLE_SENT)


def _json_sample_bytes() -> bytes:
    """ناوەڕۆکی فایلی نموونەی JSON — بە هەمان شێوازێک کە بەکارهێنەر حەزی لێیە."""
    sample = [
        {"id": 31,
         "question": "جوڵاندنی ئێسک بە کام کۆئەندام دەبێت؟",
         "A": "هەناسە",
         "B": "هەرس",
         "C": "سوڕان",
         "D": "ماسولکە",
         "answer": "C"},
        {"id": 32,
         "question": "گەورەترین ئەندامی لەش مرۆڤ کامەیە؟",
         "A": "جگەر",
         "B": "دەم",
         "C": "گورچیلە",
         "D": "دڵ",
         "answer": "A"},
        {"id": 33,
         "question": "پرسیاری نموونە بێ وەڵام — وەڵامەکە دواتر بە دەست دیاری بکە",
         "A": "بژاردەی یەکەم",
         "B": "بژاردەی دووەم",
         "C": "بژاردەی سێیەم",
         "D": "بژاردەی چوارەم"},
    ]
    import json as _json
    return _json.dumps(sample, ensure_ascii=False, indent=2).encode("utf-8")


def _json_to_questions(data) -> list:
    """گۆڕینی JSON ی خوێندراو بۆ لیستی پرسیار لە هەمان شێوەی pdfimport دا:
    {"text", "options": [{"text", "correct"}], "answered"}
    شێوازەکە: [{"id", "question", "A", "B", "C", "D", "answer"}]
    • بە تەنها ئۆبجێکت یان {"questions": [...]} یان لیست قبوڵ دەکات
    • answer: "A"-"D" یان دەقی تەواوی بژاردەکە؛ ئەگەر نەبوو → بێ وەڵام (پێداچوونەوەی دەستی)"""
    items = data
    if isinstance(items, dict):
        if isinstance(items.get("questions"), list):
            items = items["questions"]
        else:
            items = [items]
    if not isinstance(items, list):
        return []

    out = []
    for it in items[:JSON_MAX_QUESTIONS]:
        if not isinstance(it, dict):
            continue
        qtext = str(it.get("question") or it.get("q") or it.get("text") or "").strip()
        if not qtext:
            continue
        opts = []
        for L in "ABCD":
            val = it.get(L)
            if val is None:
                val = it.get(L.lower())
            if val is None and L == "A":
                val = it.get("option_a") or it.get("option_A")
            if val is None and L == "B":
                val = it.get("option_b") or it.get("option_B")
            if val is None and L == "C":
                val = it.get("option_c") or it.get("option_C")
            if val is None and L == "D":
                val = it.get("option_d") or it.get("option_D")
            o = str(val).strip() if val is not None else ""
            if o:
                opts.append(o[:300])
        if len(opts) < 2:
            continue
        options = [{"text": o, "correct": False} for o in opts]
        answered = False
        ans = it.get("answer")
        if ans is None:
            ans = it.get("correct") or it.get("key") or it.get("وەڵام")
        if ans is not None:
            s = str(ans).strip()
            idx = None
            if s:
                up = s.upper()
                first = up[0]
                if first in "ABCD":
                    cand = "ABCD".index(first)
                    # ژمارەی بژاردەکان لەبەرچاو بگرە — "D" بە تەنها کاتێک دروستە کە بژاردەی D هەبێت
                    if cand < len(options):
                        idx = cand
                if idx is None:
                    # گەڕان بە دەقی تەواوی بژاردەکە
                    for i, o in enumerate(options):
                        if o["text"].strip() == s:
                            idx = i
                            break
            if idx is not None:
                options[idx]["correct"] = True
                answered = True
        out.append({"text": qtext[:3500], "options": options, "answered": answered})
    return out


async def _route_impfile(update, context, w, data, msg):
    """هەنگاوی ناردنی فایل: JSON (Document) یان پەیامی تێکست کە بە [ یان { دەست پێبکات."""
    storage = _storage(context)
    chat = msg.chat_id
    doc, text = msg.document, (msg.text or msg.caption or "")

    raw_json = None
    if doc is not None:
        name = (doc.file_name or "").lower()
        mime = doc.mime_type or ""
        if not (name.endswith((".json", ".txt")) or "json" in mime or mime.startswith("text/")):
            return await msg.reply_text(T.IMP2_BAD_FILE)
        if (doc.file_size or 0) > JSON_MAX_BYTES:
            return await msg.reply_text(T.IMP2_TOO_BIG)
        await msg.reply_text(T.IMP2_PARSING)
        import json as _json
        path = os.path.join(config.DATA_DIR, "imp_{}.json".format(chat))
        try:
            tg_file = await doc.get_file()
            await tg_file.download_to_drive(path)
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                raw_json = f.read()
        except Exception as e:
            log.warning("داگرتنی فایلی JSON: %s", e)
            return await msg.reply_text(T.IMP2_BAD_FILE)
        finally:
            try:
                os.remove(path)
            except Exception:
                pass
    elif text.strip().startswith(("[", "{")):
        raw_json = text
    else:
        return await msg.reply_text(T.IMP2_BAD_FILE)

    import json as _json
    try:
        data_json = _json.loads(raw_json)
    except Exception as e:
        return await msg.reply_text(
            T.IMP2_JSON_ERR.format(err=_html.escape(str(e)[:120])),
            parse_mode="HTML")

    questions = _json_to_questions(data_json)
    if not questions:
        return await msg.reply_text(T.IMP2_NONE, parse_mode="HTML")

    d = w.setdefault("data", {})
    d["questions"] = questions
    w["step"] = "confirm"
    storage.set_wizard(chat, w)
    n_ans = sum(1 for q in questions if q["answered"])
    await msg.reply_text(
        T.IMP2_CONFIRM.format(q=st.knum(len(questions)), a=st.knum(n_ans),
                              p=st.knum(len(questions) - n_ans),
                              folder=d.get("folder_title") or "—"),
        reply_markup=K.imp_confirm_kb())


async def cb_impok(query, context):
    """دووپاتکردنەوەی زیادکردنی پرسیارە پارسکراوەکان بۆ بەشەکە."""
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "impfile" or w.get("step") != "confirm":
        return await handlers_user.alert(query, T.WIZ_GONE, K.back_to_panel_kb())
    d = w.get("data") or {}
    questions = d.get("questions") or []
    fid = d.get("folder_id")
    folder = st.find_node(storage.db()["tree"], fid)
    folder_title = (folder or {}).get("title") or d.get("folder_title") or "—"
    pending = []
    for q in questions:
        node = storage.add_question(fid, q["text"], None, q["options"])
        if not q["answered"]:
            pending.append(node["id"])
    storage.clear_wizard(chat)
    n = len(questions)
    await query.message.reply_text(
        T.IMP2_DONE.format(folder=folder_title, q=st.knum(n),
                           a=st.knum(n - len(pending)), p=st.knum(len(pending))),
        reply_markup=K.after_import_kb(fid))
    if pending:
        storage.set_wizard(chat, {"flow": "pqrev", "step": "go",
                                  "data": {"qids": pending}})
        try:
            await context.bot.send_message(
                chat, T.IMP2_REVIEW_HEAD.format(n=st.knum(len(pending))))
        except Exception:
            pass
        await _pq_send(context, chat, storage.get_wizard(chat))


# ---------------- دیاریکردنی وەڵامی ڕاست بە دەست (پرسیاری بێ وەڵام) ----------------

async def cb_pending(query, context):
    """دەستپێکردنی پێداچوونەوە بۆ هەموو پرسیارە بێ وەڵامەکانی دارچینەکە."""
    storage = _storage(context)
    chat = query.message.chat_id
    qids = storage.pending_question_ids(limit=150)
    if not qids:
        return await handlers_user.alert(query, T.PENDING_NONE, K.back_to_panel_kb())
    storage.set_wizard(chat, {"flow": "pqrev", "step": "go", "data": {"qids": qids}})
    await handlers_user.alert(query, T.IMP2_REVIEW_HEAD.format(n=st.knum(len(qids))))
    await _pq_send(context, chat, storage.get_wizard(chat))


async def _pq_send(context, chat, w):
    """پرسیاری ئێستای پێداچوونەوە دەنێرێت — دوگمەکانی A-D بۆ دیاریکردنی وەڵامی ڕاست."""
    storage = _storage(context)
    if not w or w.get("flow") != "pqrev":
        return
    qids = (w.get("data") or {}).get("qids") or []
    if not qids:
        storage.clear_wizard(chat)
        try:
            await context.bot.send_message(chat, T.PQ_ALL_DONE)
        except Exception:
            pass
        return
    q = st.find_node(storage.db()["tree"], qids[0])
    if not q:
        w["data"]["qids"] = qids[1:]
        storage.set_wizard(chat, w)
        return await _pq_send(context, chat, w)
    text = T.PENDING_VIEW.format(left=st.knum(len(qids)),
                                 text=fmt.plain(q.get("text") or T.RESULT_IMG))
    try:
        await context.bot.send_message(
            chat, text, reply_markup=K.pq_review_kb(q.get("options") or []))
    except Exception:
        pass


async def cb_pq(query, context, data: str):
    """pqset:<idx> / pqskip / pqdone — پێداچوونەوەی پرسیارە بێ وەڵامەکان."""
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "pqrev":
        return await handlers_user.alert(query, T.WIZ_GONE, K.back_to_panel_kb())
    qids = w.get("data", {}).get("qids") or []

    if data == "pqdone":
        left = len(qids)
        storage.clear_wizard(chat)
        msg = T.PQ_ALL_DONE if not left else T.PQ_DONE_LEFT.format(left=st.knum(left))
        return await handlers_user.alert(query, msg, K.back_to_panel_kb())

    if not qids:
        storage.clear_wizard(chat)
        return await handlers_user.alert(query, T.PQ_ALL_DONE, K.back_to_panel_kb())

    qid = qids[0]

    if data == "pqskip":
        qids.pop(0)
        w["data"]["qids"] = qids
        storage.set_wizard(chat, w)
        await handlers_user.alert(query, T.PQ_SKIPPED)
        return await _pq_send(context, chat, w)

    if data.startswith("pqset:"):
        try:
            idx = int(data[6:])
        except ValueError:
            return
        q = st.find_node(storage.db()["tree"], qid)
        if not q:
            qids.pop(0)
            w["data"]["qids"] = qids
            storage.set_wizard(chat, w)
            return await _pq_send(context, chat, w)
        options = q.get("options") or []
        if idx < 0 or idx >= len(options):
            return await handlers_user.alert(query, T.WIZ_INVALID_NUM)
        storage.set_question_correct(qid, idx)
        qids.pop(0)
        w["data"]["qids"] = qids
        storage.set_wizard(chat, w)
        await handlers_user.alert(query, T.PQ_SAVED)
        return await _pq_send(context, chat, w)


# ---------------- بەڕێوەبردنی مینیوی سەرەکی ----------------

async def cb_menu(query, context):
    storage = _storage(context)
    items = "\n".join("• " + K.menu_label(storage, key) for key in K.MENU_KEYS)
    extras = storage.menu_extras()
    extras_txt = ("\n".join("• " + (x.get("label") or "؟") for x in extras)
                  if extras else T.MENU_EXTRAS_EMPTY)
    await handlers_user.edit_message(
        query, T.MENU_VIEW.format(items=items, extras=extras_txt),
        K.menu_admin_kb(storage))


async def cb_menu_label(query, context, key: str):
    storage = _storage(context)
    if key not in K.MENU_KEYS:
        return
    chat = query.message.chat_id
    cur = K.menu_label(storage, key)
    storage.set_wizard(chat, {"flow": "menulabel", "step": "label",
                              "data": {"key": key}})
    await handlers_user.edit_message(query, T.WIZ_MENU_LABEL.format(cur=cur),
                                     K.wiz_cancel_kb())


async def _finish_menu_label(update, context, w):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    label = (msg.text or "").strip()
    if not label:
        return await msg.reply_text(T.WIZ_NEED_TEXT)
    key = (w.get("data") or {}).get("key")
    if key not in K.MENU_KEYS:
        storage.clear_wizard(chat)
        return await msg.reply_text(T.ERR)
    if label == "-":
        storage.set_menu_label(key, "")
    else:
        storage.set_menu_label(key, label)
    storage.clear_wizard(chat)
    await msg.reply_text(T.MENU_LABEL_SAVED.format(label=K.menu_label(storage, key)))


async def cb_menu_reset(query, context):
    storage = _storage(context)
    storage.reset_menu_labels()
    await handlers_user.alert(query, T.MENU_RESET_DONE)
    await cb_menu(query, context)


async def cb_menu_extra(query, context):
    storage = _storage(context)
    if not storage.db()["pages"]:
        return await handlers_user.alert(query, T.MENU_NEED_PAGE, K.back_to_panel_kb())
    chat = query.message.chat_id
    storage.set_wizard(chat, {"flow": "menuextra", "step": "title", "data": {}})
    await handlers_user.edit_message(query, T.WIZ_MENU_EXTRA, K.wiz_cancel_kb())


async def _finish_menu_extra(update, context, w):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    label = (msg.text or "").strip()
    if not label:
        return await msg.reply_text(T.WIZ_NEED_TEXT)
    pages = storage.db()["pages"]
    if not pages:
        storage.clear_wizard(chat)
        return await msg.reply_text(T.MENU_NEED_PAGE)
    w["step"] = "page"
    w.setdefault("data", {})["label"] = st.trunc(label, 40)
    storage.set_wizard(chat, w)
    await msg.reply_text(T.WIZ_MENU_EXTRA_PICK,
                         reply_markup=K.menu_extra_pick_kb(pages))


async def cb_menu_extra_pick(query, context, pid: str):
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "menuextra" or w.get("step") != "page":
        return await handlers_user.alert(query, T.WIZ_GONE, K.back_to_panel_kb())
    page = next((p for p in storage.db()["pages"] if p.get("id") == pid), None)
    if not page:
        return await handlers_user.alert(query, T.PAGE_GONE)
    label = (w.get("data") or {}).get("label") or page.get("title") or "📄"
    storage.add_menu_extra(label, pid)
    storage.clear_wizard(chat)
    await handlers_user.alert(query, T.MENU_EXTRA_SAVED.format(label=label))
    await cb_menu(query, context)


async def cb_menu_extra_del(query, context, extra_id: str):
    storage = _storage(context)
    storage.del_menu_extra(extra_id)
    await handlers_user.alert(query, T.MENU_EXTRA_DELETED)
    await cb_menu(query, context)


# ============================================================================
# ڕاپۆرتەکانی کێشە (لای ئادمین)
# ============================================================================

def _report_admin_text(r: dict) -> str:
    status = {"open": T.TK_STATUS_OPEN, "replied": T.TK_STATUS_REPLIED.format(
        n=st.knum(len(r.get("replies", [])))), "closed": T.TK_STATUS_CLOSED}.get(
        r.get("status"), "")
    return (T.RP_ADMIN.format(
        id=st.knum(r.get("id", 0)),
        name=r.get("name") or "—",
        username=r.get("username") or "—",
        uid=r.get("uid") or "—",
        quiz=r.get("quiz") or "—",
        qtext=r.get("qtext") or "—",
        comment=r.get("comment") or "—")
        + "\n\n" + status)


async def notify_new_report(context: ContextTypes.DEFAULT_TYPE, report: dict):
    """ڕاپۆرتی نوێ بۆ هەموو ئادمینەکان دەنێرێت و ID ی پەیامەکان هەڵدەگرێت."""
    storage = _storage(context)
    text = _report_admin_text(report)
    kb = K.report_kb(report["id"], report.get("status", "open"))
    for aid in storage.all_admin_ids():
        try:
            sent = await fmt.send_html(context.bot, aid, text, reply_markup=kb)
            if sent:
                report.setdefault("admin_msgs", {})[str(aid)] = {
                    "chat": aid, "mid": sent.message_id}
        except Exception as e:
            log.warning("ناردنی ڕاپۆرت بۆ ئادمینی %s سەرکەوتوو نەبوو: %s", aid, e)
    storage.save_report(report)


async def _refresh_report_msgs(context: ContextTypes.DEFAULT_TYPE, report: dict):
    text = _report_admin_text(report)
    kb = K.report_kb(report["id"], report.get("status", "open"))
    for key in list((report.get("admin_msgs") or {}).keys()):
        info = report["admin_msgs"][key]
        try:
            await context.bot.edit_message_text(
                chat_id=info["chat"], message_id=info["mid"],
                text=text, reply_markup=kb)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                log.info("نوێکردنەوەی پەیامی ڕاپۆرت نەکرا: %s", e)
        except Exception:
            pass
    storage.save_report(report)


async def cb_reports(query, context):
    storage = _storage(context)
    reports = storage.open_reports()
    if not reports:
        return await handlers_user.alert(query, T.A_RP_EMPTY, K.back_to_panel_kb())
    await handlers_user.edit_message(
        query, T.A_RP_TITLE.format(n=st.knum(len(reports))),
        K.reports_list_kb(reports))


async def cb_report(query, context, payload: str):
    """rp:view:<id> / rp:reply:<id> / rp:close:<id> / rp:del:<id> / rp:delok:<id>"""
    parts = payload.split(":")
    if len(parts) != 2 or parts[0] not in ("view", "reply", "close", "del", "delok"):
        return
    action, rid_raw = parts[0], parts[1]
    storage = _storage(context)
    report = storage.get_report(rid_raw)
    if not report:
        return await handlers_user.alert(query, T.RP_GONE)

    if action == "view":
        text = _report_admin_text(report)
        kb = K.report_kb(report["id"], report.get("status", "open"))
        chat = query.message.chat_id
        try:
            await context.bot.send_message(chat, text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
        return

    if action == "close":
        report["status"] = "closed"
        storage.save_report(report)
        await handlers_user.alert(query, T.RP_CLOSED_MSG)
        await _refresh_report_msgs(context, report)
        return

    if action == "del":
        await handlers_user.edit_message(
            query, T.CONFIRM_DEL_QUESTION,
            K.report_del_kb(report["id"]))
        return

    if action == "delok":
        storage.delete_report(report["id"])
        await handlers_user.alert(query, T.RP_DELETED)
        return

    if action == "reply":
        chat = query.message.chat_id
        storage.set_wizard(chat, {"flow": "rpreply", "step": "msg",
                                  "data": {"rid": report["id"]}})
        await handlers_user.alert(
            query, T.RP_REPLY_PROMPT.format(id=st.knum(report.get("id", 0))))


async def cb_report_clear(query, context):
    """سڕینەوەی هەموو ڕاپۆرتە داخراوەکان — ڕێگری لە کەڵەکەبوون."""
    storage = _storage(context)
    n = storage.clear_closed_reports()
    await handlers_user.alert(query, T.RP_CLEAR_DONE.format(n=st.knum(n)))
    await cb_reports(query, context)


async def _finish_report_reply(update, context, w: dict, data: dict):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    report = storage.get_report(data.get("rid"))
    if not report:
        storage.clear_wizard(chat)
        return await msg.reply_text(T.RP_GONE)

    text = (msg.text or msg.caption or "").strip()
    photo = msg.photo[-1].file_id if msg.photo else None
    if not text and not photo:
        return await msg.reply_text(T.WIZ_NEED_TEXT)

    admin_name = (msg.from_user.first_name or "ئادمین").strip()
    # پرسیارە ڕاپۆرتکراوەکە لە سەرەتای وەڵامەکە دەنووسرێت
    reply_part = (fmt.apply(text) if text else ("🖼 (وێنە)" if photo else "—"))
    q_label = fmt.plain(report.get("qtext") or "") or "—"
    head = T.RP_USER_HEAD.format(id=st.knum(report.get("id", 0)),
                                 q=q_label, reply=reply_part)
    if len(head) > 1000:
        head = T.RP_USER_HEAD.format(id=st.knum(report.get("id", 0)),
                                     q=st.trunc(q_label, 120), reply=reply_part)
    delivered = False
    sent_msg = None
    try:
        if photo:
            sent_msg = await fmt.send_photo_html(context.bot, report.get("uid"), photo, head or "🖼")
        else:
            sent_msg = await fmt.send_html(context.bot, report.get("uid"), head)
        delivered = True
    except Exception as e:
        log.warning("ناردنی وەڵامی ڕاپۆرت: %s", e)
    if delivered and sent_msg:
        # پاش ٢ چرکە ناوی ئادمین لە خوارەوەی وەڵامەکە دەنووسرێت
        _schedule_admin_sign(context.bot, report.get("uid"), sent_msg.message_id,
                             head or "🖼", admin_name, caption=bool(photo))

    report.setdefault("replies", []).append({
        "by": msg.from_user.id, "name": admin_name,
        "text": text, "photo": photo, "at": int(time.time()),
    })
    report["status"] = "replied"
    storage.clear_wizard(chat)
    storage.save_report(report)
    await _refresh_report_msgs(context, report)

    if delivered:
        await msg.reply_text(T.RP_DELIVERED.format(name=report.get("name") or "—"),
                             reply_markup=K.back_to_panel_kb())
    else:
        await msg.reply_text(T.RP_USER_GONE)


# ============================================================================
# بەکارهێنەران و ئامارەکانیان (لای ئادمین)
# ============================================================================

def _user_row(u: dict) -> str:
    return "👤 {} ({}) — ID: {}".format(
        u.get("name") or "—", u.get("username") or "—", u.get("uid") or "—")


async def cb_users(query, context, page: int = 1):
    storage = _storage(context)
    # هەموو بەکارهێنەرانی تۆمارکراو پیشان دەدرێت — ژمارەکە لە هەموو شوێنێکدا یەکسانە
    # (پانێڵ، دوگمە، لیست، ئامار، نامەی گشتی = هەمووی count_users())
    users = storage.users_sorted()
    if not users:
        return await handlers_user.alert(query, T.A_USR_EMPTY, K.back_to_panel_kb())
    total = len(users)
    students, others = storage.count_teacher_users()
    pages_n = max(1, (total + K.USERS_PER_PAGE - 1) // K.USERS_PER_PAGE)
    page = max(1, min(page, pages_n))
    chunk = users[(page - 1) * K.USERS_PER_PAGE: page * K.USERS_PER_PAGE]
    await handlers_user.edit_message(
        query, T.A_USR_TITLE.format(n=st.knum(total), t=st.knum(students),
                                    nt=st.knum(others),
                                    p=st.knum(page), pp=st.knum(pages_n)),
        K.users_list_kb(chunk, page, total))


async def cb_user_view(query, context, uid_raw: str):
    storage = _storage(context)
    try:
        uid = int(st.to_int(uid_raw))
    except (TypeError, ValueError):
        return await handlers_user.alert(query, T.A_USR_NOT_FOUND)
    u = storage.get_user(uid)
    if not u:
        return await handlers_user.alert(query, T.A_USR_NOT_FOUND)

    stats = u.get("stats") or {}
    total = int(stats.get("total", 0))
    correct = int(stats.get("correct", 0))
    pct = int(round(correct * 100.0 / total)) if total else 0
    by = stats.get("by_folder") or {}
    if by:
        lines = []
        for title, cell in list(by.items())[:8]:
            p2 = int(round(cell["c"] * 100.0 / cell["q"])) if cell.get("q") else 0
            lines.append("• {} — {} / {} ({}٪)".format(
                st.trunc(title, 30), st.knum(cell.get("c", 0)),
                st.knum(cell.get("q", 0)), st.knum(p2)))
        byfolder = "\n".join(lines)
    else:
        byfolder = T.A_USR_NOFOLDER

    # ئەنجامەکانی تاقیکردنەوەی شەوانە (دوا ٥ ڕۆژ)
    ev = storage.get_event()
    qn_lines = []
    if ev:
        for date in sorted((ev.get("results") or {}).keys(), reverse=True)[:5]:
            entry = ev["results"][date].get(str(uid))
            if entry:
                qn_lines.append("• {} — {} / {} ({}٪)".format(
                    date, st.knum(entry.get("score", 0)),
                    st.knum(entry.get("total", 0)), st.knum(entry.get("pct", 0))))
    qn_txt = "\n".join(qn_lines) if qn_lines else T.A_USR_NOQN

    ban_info = storage.get_ban_info(uid)
    if ban_info:
        reason = (ban_info.get("reason") or "").strip()
        status = (T.A_USR_STATUS_BANNED +
                  (" — " + st.trunc(reason, 60) if reason else ""))
    else:
        status = T.A_USR_STATUS_OK

    text = T.A_USR_VIEW.format(
        name=u.get("name") or "—",
        username=u.get("username") or "—",
        uid=u.get("uid") or "—",
        teacher=storage.get_teacher_name(),
        is_t=("بەڵێ ✅" if u.get("teacher") else
              ("نەخێر ❌" if u.get("teacher") is not None else "—")),
        status=status,
        joined=handlers_user.fmt_ts(u.get("joined")),
        last=handlers_user.fmt_ts(stats.get("last_quiz_at") or u.get("joined")),
        quizzes=st.knum(stats.get("quizzes", 0)),
        total=st.knum(total), correct=st.knum(correct), pct=st.knum(pct),
        byfolder=byfolder, qn=qn_txt)
    await handlers_user.edit_message(query, text, K.user_view_kb(uid, bool(ban_info)))


async def start_user_msg(query, context, uid_raw: str):
    """نامەی تایبەت بۆ یەک بەکارهێنەر لە بەشی بەکارهێنەرانەوە."""
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    u = storage.get_user(uid) if uid is not None else None
    if not u:
        return await handlers_user.alert(query, T.A_USR_NOT_FOUND)
    chat = query.message.chat_id
    storage.set_wizard(chat, {"flow": "usrmsg", "step": "msg",
                              "data": {"uid": uid, "name": u.get("name") or ""}})
    text = T.WIZ_USR_MSG.format(name=st.trunc(u.get("name") or "", 30))
    await handlers_user.edit_message(query, text, K.wiz_cancel_kb())


async def _finish_user_msg(update, context, w: dict):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    d = w.get("data") or {}
    uid = d.get("uid")
    u = storage.get_user(uid)
    if not u:
        storage.clear_wizard(chat)
        return await msg.reply_text(T.A_USR_NOT_FOUND)

    text = (msg.text or msg.caption or "").strip()
    photo = msg.photo[-1].file_id if msg.photo else None
    if not text and not photo:
        return await msg.reply_text(T.WIZ_NEED_ITEM)

    head = T.USR_MSG_HEAD.format(reply=fmt.apply(text) if text else "")
    admin_name = (msg.from_user.first_name or "ئادمین").strip()
    sent_msg = None
    try:
        if photo:
            sent_msg = await fmt.send_photo_html(context.bot, uid, photo, head or "📩")
        else:
            sent_msg = await fmt.send_html(context.bot, uid, head)
    except Exception as e:
        log.warning("ناردنی نامەی تایبەت بۆ %s: %s", uid, e)
        storage.clear_wizard(chat)
        return await msg.reply_text(T.USR_MSG_GONE)
    if sent_msg:
        # پاش ٢ چرکە ناوی ئادمین لە خوارەوەی نامەکە دەنووسرێت
        _schedule_admin_sign(context.bot, uid, sent_msg.message_id,
                             head or "📩", admin_name, caption=bool(photo))
        # نامەکە دەچێتە «نامە هاتووەکان» ی بەکارهێنەرەوە
        try:
            storage.add_inbox_msg(uid, text, photo, msg.from_user.id, admin_name)
        except Exception:
            pass

    storage.clear_wizard(chat)
    await msg.reply_text(
        T.USR_MSG_SENT.format(name=u.get("name") or "—"),
        reply_markup=K.back_to_panel_kb())


async def start_user_search(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    storage.set_wizard(chat, {"flow": "usrsearch", "step": "q", "data": {}})
    await handlers_user.edit_message(query, T.WIZ_USR_SEARCH, K.wiz_cancel_kb())


async def _finish_user_search(update, context, w: dict):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    if not msg.text or not msg.text.strip():
        await msg.reply_text(T.WIZ_NEED_TEXT)
        return
    results = storage.find_users(msg.text or "")
    storage.clear_wizard(chat)
    if not results:
        return await msg.reply_text(T.A_USR_SEARCH_EMPTY, reply_markup=K.back_to_panel_kb())
    # ئەنجامەکان وەک لیست — هەر یەکێک دوگمەی خۆی
    rows = [[K.btn("👤 " + st.trunc(u.get("name") or str(u.get("uid")), 30),
                   "usr:view:{}".format(u.get("uid")))] for u in results[:20]]
    rows.append([K.btn(T.A_BTN_BACK_PANEL, "adm")])
    from telegram import InlineKeyboardMarkup
    students, others = storage.count_teacher_users()
    await msg.reply_text(T.A_USR_TITLE.format(
        n=st.knum(len(results)), t=st.knum(students), nt=st.knum(others),
        p=st.knum(1), pp=st.knum(1)),
        reply_markup=InlineKeyboardMarkup(rows))


# ---------------- باندکردن و سڕینەوەی هەژمار (لای ئادمین) ----------------

async def start_user_ban(query, context, uid_raw: str):
    """دەستپێکردنی فلۆوی باندکردن — داواکردنی هۆکار لە ئادمین."""
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    u = storage.get_user(uid) if uid is not None else None
    if not u:
        return await handlers_user.alert(query, T.A_USR_NOT_FOUND)
    if storage.is_banned(uid):
        return await handlers_user.alert(query, T.A_USR_ALREADY_BANNED)
    chat = query.message.chat_id
    storage.set_wizard(chat, {"flow": "usrban", "step": "reason",
                              "data": {"uid": uid,
                                       "name": u.get("name") or ""}})
    text = T.WIZ_BAN_REASON.format(name=st.trunc(u.get("name") or "—", 30))
    await handlers_user.edit_message(query, text, K.wiz_cancel_kb())


async def _finish_user_ban(update, context, w: dict):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    d = w.get("data") or {}
    uid = d.get("uid")
    u = storage.get_user(uid)
    if not u:
        storage.clear_wizard(chat)
        return await msg.reply_text(T.A_USR_NOT_FOUND)
    if config.OWNER_ID is not None and uid == config.OWNER_ID:
        storage.clear_wizard(chat)
        return await msg.reply_text(T.A_ONLY_OWNER)
    reason = (msg.text or "").strip()
    if not reason:
        return await msg.reply_text(T.WIZ_NEED_TEXT)
    was_admin = storage.is_admin(uid)
    storage.ban_user(uid, reason, by=str(msg.from_user.id))
    if was_admin:
        # باندکردنی ئادمین = لابردن لە ئادمین + باندکردنی هەژمارەکەی
        storage.remove_admin(uid)
    storage.clear_wizard(chat)   # فلۆوی ئادمین
    storage.clear_wizard(uid)    # هەر ویزاردێکی چالاکى بەکارهێنەرەکە بوەستێت
    name = st.trunc(u.get("name") or "—", 30)
    done = T.ADMIN_BAN_DONE if was_admin else T.BAN_DONE
    await msg.reply_text(done.format(name=name),
                         reply_markup=K.back_to_panel_kb())
    # ئاگادارکردنەوەی ڕاستەوخۆی بەکارهێنەرەکە بە هۆکارەکەوە
    try:
        await context.bot.send_message(
            int(uid), T.BAN_NOTICE.format(reason=(reason or "")[:300]))
    except Exception as e:
        log.info("نەتوانرا ئاگاداری باند بۆ %s بنێردرێت: %s", uid, e)


async def cb_user_unban(query, context, uid_raw: str):
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    u = storage.get_user(uid) if uid is not None else None
    if not u:
        return await handlers_user.alert(query, T.A_USR_NOT_FOUND)
    storage.unban_user(uid)
    await handlers_user.alert(query, T.UNBAN_DONE.format(
        name=st.trunc(u.get("name") or "—", 30)))
    await cb_user_view(query, context, uid_raw)


async def cb_user_del(query, context, uid_raw: str):
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    u = storage.get_user(uid) if uid is not None else None
    if not u:
        return await handlers_user.alert(query, T.A_USR_NOT_FOUND)
    await handlers_user.edit_message(
        query, T.CONFIRM_DEL_USER.format(name=st.trunc(u.get("name") or "—", 30)),
        K.user_del_confirm_kb(uid))


async def cb_user_del_ok(query, context, uid_raw: str):
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    u = storage.get_user(uid) if uid is not None else None
    if not u:
        return await handlers_user.alert(query, T.A_USR_NOT_FOUND)
    name = st.trunc(u.get("name") or "—", 30)
    storage.clear_wizard(uid)
    storage.delete_user(uid)
    await handlers_user.alert(query, T.DEL_USER_DONE.format(name=name))
    await cb_users(query, context)


# ---------------- بەڕێوەبردنی ئادمینەکان: باندکردن و سڕینەوە ----------------

async def start_admin_ban(query, context, uid_raw: str):
    """باندکردنی ئادمین لە بەشی ئادمینەکان — هۆکار داوا دەکات و لە ئادمین لابردرێت."""
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    if uid is None:
        return
    if config.OWNER_ID is not None and uid == config.OWNER_ID:
        return await handlers_user.alert(query, T.A_ONLY_OWNER)
    u = storage.get_user(uid)
    if not u:
        return await handlers_user.alert(query, T.A_USR_NOT_FOUND)
    if storage.is_banned(uid):
        return await handlers_user.alert(query, T.A_USR_ALREADY_BANNED)
    chat = query.message.chat_id
    storage.set_wizard(chat, {"flow": "usrban", "step": "reason",
                              "data": {"uid": uid,
                                       "name": u.get("name") or str(uid)}})
    text = T.WIZ_BAN_REASON.format(
        name=st.trunc(u.get("name") or str(uid), 30))
    await handlers_user.edit_message(query, text, K.wiz_cancel_kb())


async def cb_admin_delete(query, context, uid_raw: str):
    """دڵنیایی لە سڕینەوەی هەژماری ئادمین (لابردن لە ئادمین + سڕینەوەی زانیارییەکان)."""
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    if uid is None:
        return
    if config.OWNER_ID is not None and uid == config.OWNER_ID:
        return await handlers_user.alert(query, T.A_ONLY_OWNER)
    u = storage.get_user(uid)
    name = st.trunc((u or {}).get("name") or str(uid), 30)
    await handlers_user.edit_message(
        query, T.CONFIRM_DEL_ADMIN.format(name=name),
        K.admin_del_confirm_kb(uid))


async def cb_admin_delete_ok(query, context, uid_raw: str):
    storage = _storage(context)
    uid = st.to_int(uid_raw)
    if uid is None:
        return
    if config.OWNER_ID is not None and uid == config.OWNER_ID:
        return await handlers_user.alert(query, T.A_ONLY_OWNER)
    u = storage.get_user(uid)
    name = st.trunc((u or {}).get("name") or str(uid), 30)
    storage.remove_admin(uid)
    storage.clear_wizard(uid)
    storage.delete_user(uid)
    await handlers_user.alert(query, T.DEL_USER_DONE.format(name=name))
    await cb_admins(query, context)


# ============================================================================
# تاقیکردنەوەی شەوانە (لای ئادمین)
# ============================================================================

def _event_state_text(storage, ev: dict) -> str:
    import events as evmod
    state_map = {"wait": T.A_QN_STATE_WAIT, "open": T.A_QN_STATE_OPEN,
                 "over": T.A_QN_STATE_OVER}
    state = state_map.get(evmod.status(ev), "—")
    src = ev.get("src") or {}
    if (src.get("type") or "folder") == "bank":
        src_title = T.A_QN_SRC_BANK_NAME
        n = len(ev.get("bank") or [])
    else:
        folder = st.find_node(storage.db()["tree"], src.get("folder_id"))
        src_title = (folder or {}).get("title") or "—"
        n = st.count_questions(folder) if folder else 0
        if src.get("count"):
            n = src["count"]
    date = evmod.today_str()
    n_played = len((ev.get("results") or {}).get(date) or {})
    return T.A_QN_VIEW.format(
        title=ev.get("title", "—"),
        start=evmod.clock_k(ev.get("start", "—")),
        end=evmod.clock_k(ev.get("end", "—")),
        src=src_title,
        n=st.knum(n),
        shown=(T.A_QN_SHOWN_YES if ev.get("enabled") else T.A_QN_SHOWN_NO),
        state=state, p=st.knum(n_played))


async def cb_qnev(query, context):
    storage = _storage(context)
    ev = storage.get_event()
    if not ev:
        await handlers_user.edit_message(query, T.A_QN_NONE, K.qn_none_kb())
    else:
        kb = K.qn_view_kb(bool(ev.get("enabled")))
        await handlers_user.edit_message(query, _event_state_text(storage, ev), kb)


async def cb_qn_toggle(query, context):
    storage = _storage(context)
    ev = storage.get_event()
    if not ev:
        return await cb_qnev(query, context)
    ev["enabled"] = not ev.get("enabled")
    storage.save_event(ev)
    await cb_qnev(query, context)


async def cb_qn_delete(query, context):
    await handlers_user.edit_message(query, T.CONFIRM_DEL_FOLDER.replace(
        "{title}", "تاقیکردنەوەی شەوانە").replace(
        "{subs}", "٠").replace("{qs}", "٠"),
        K.qn_confirm_del_kb())


async def cb_qn_delete_ok(query, context):
    storage = _storage(context)
    storage.save_event(None)
    await handlers_user.alert(query, T.A_QN_DELETED)
    await cb_qnev(query, context)


async def cb_qn_results(query, context):
    storage = _storage(context)
    ev = storage.get_event()
    if not ev:
        return await cb_qnev(query, context)
    import events as evmod
    date = evmod.today_str()
    day = (ev.get("results") or {}).get(date) or {}
    if not day:
        return await handlers_user.alert(query, T.A_QN_NO_RESULTS, K.back_to_panel_kb())
    rows = evmod.leaderboard(day)
    text = evmod.fmt_leaderboard(rows, ev.get("title", "—"))
    try:
        await context.bot.send_message(query.message.chat_id, text,
                                       reply_markup=K.back_to_panel_kb(),
                                       parse_mode="HTML")
    except Exception:
        pass


# --- ویزاردی دروستکردن/دەستکاری ئیڤێنت ---

async def qn_new(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    storage.set_wizard(chat, {"flow": "qnev", "step": "title",
                              "data": {"edit": False}})
    await handlers_user.edit_message(query, T.WIZ_QN_TITLE, K.wiz_cancel_kb())


async def qn_edit_time(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    storage.set_wizard(chat, {"flow": "qntime", "step": "start", "data": {}})
    await handlers_user.edit_message(query, T.WIZ_QN_START, K.wiz_cancel_kb())


async def qn_edit_src(query, context):
    """سەرچاوەی پرسیارەکان: لە بەشەکان وەربگرە یان پرسیاری نوێ بنووسە."""
    storage = _storage(context)
    if not storage.get_event():
        return await handlers_user.alert(query, T.A_QN_BANK_NEED_EVENT, K.back_to_panel_kb())
    await handlers_user.edit_message(query, T.A_QN_SRC_ASK, K.qn_src_kb())


async def qn_edit_src_folder(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    tree = storage.db()["tree"]
    if not tree:
        return await handlers_user.alert(query, T.NO_SECTIONS)
    storage.set_wizard(chat, {"flow": "qnsrc", "step": "folder",
                              "data": {"path": []}})
    kb = K.qn_folder_kb([n for n in tree if n.get("type") == "folder"], 0)
    await handlers_user.edit_message(query, T.WIZ_QN_PICK, kb)


# --- بەنکۆی پرسیارە نوێکانی تاقیکردنەوەی شەوانە ---

async def cb_qn_bank(query, context):
    """شاشەی بەڕێوەبردنی بەنکۆی پرسیارەکان — هەروەها بەنکۆ وەک سەرچاوە دان دەنێت."""
    storage = _storage(context)
    ev = storage.get_event()
    if not ev:
        return await handlers_user.alert(query, T.A_QN_BANK_NEED_EVENT, K.back_to_panel_kb())
    # هەڵبژاردنی «پرسیاری نوێ» → سەرچاوەکە دەبێتە بەنکۆ
    if (ev.get("src") or {}).get("type") != "bank":
        ev["src"] = {"type": "bank"}
        storage.save_event(ev)
    n = len(ev.get("bank") or [])
    await handlers_user.edit_message(query, T.A_QN_BANK_TITLE.format(n=st.knum(n)),
                                     K.qn_bank_kb(n))


async def cb_qn_bank_add(query, context):
    storage = _storage(context)
    if not storage.get_event():
        return await handlers_user.alert(query, T.A_QN_BANK_NEED_EVENT, K.back_to_panel_kb())
    chat = query.message.chat_id
    w = {"flow": "qnbank", "step": "image",
         "data": {"image": None, "text": "", "options": []}}
    storage.set_wizard(chat, w)
    await _edit_prompt(context, chat, w, T.WIZ_Q_IMAGE, K.wiz_image_kb())


async def cb_qn_bank_del(query, context):
    storage = _storage(context)
    n = storage.pop_event_bank_question()
    if not n:
        return await handlers_user.alert(query, T.A_QN_BANK_EMPTY)
    await handlers_user.alert(query, T.A_QN_BANK_DEL_DONE.format(n=st.knum(n)))
    await cb_qn_bank(query, context)


def _ev_wizard_common(storage, ev: dict, data: dict):
    """دروستکردنی ئۆبجێکتی ئیڤێنت لە داتای ویزارد."""
    ev = ev or {"id": st.new_id("e"), "title": "تاقیکردنەوەی شەوانە",
                "start": "21:00", "end": "21:30", "enabled": True,
                "announced": {}, "results": {}}
    if data.get("title"):
        ev["title"] = data["title"]
    if data.get("start"):
        ev["start"] = data["start"]
    if data.get("end"):
        ev["end"] = data["end"]
    if data.get("src"):
        ev["src"] = data["src"]
    return ev


async def _route_qnev(update, context, w: dict):
    """ویزاردی دروستکردنی ئیڤێنت: title → start → end → (بەشەکان بە دوگمە) → (ژمارە بە دوگمە)"""
    import events as evmod
    storage = _storage(context)
    msg = update.message
    if not msg or not msg.text:
        return
    chat = msg.chat_id
    step = w.get("step")
    data = w.setdefault("data", {})
    txt = msg.text.strip()

    if step == "title":
        data["title"] = st.trunc(txt, 60)
        w["step"] = "start"
        storage.set_wizard(chat, w)
        await msg.reply_text(T.WIZ_QN_START)
        return

    if step == "start":
        t = evmod.parse_hhmm(txt)
        if not t:
            return await msg.reply_text(T.WIZ_QN_TIME_BAD)
        data["start"] = t
        w["step"] = "end"
        storage.set_wizard(chat, w)
        await msg.reply_text(T.WIZ_QN_END)
        return

    if step == "end":
        t = evmod.parse_hhmm(txt)
        if not t:
            return await msg.reply_text(T.WIZ_QN_TIME_BAD)
        data["end"] = t
        # بەردەوام بۆ هەڵبژاردنی بەشی سەرچاوەی پرسیارەکان
        w["flow"] = "qnsrc"
        w["step"] = "folder"
        w["data"] = {"path": [], "title": data.get("title"),
                     "start": data.get("start"), "end": t}
        storage.set_wizard(chat, w)
        tree = storage.db()["tree"]
        kb = K.qn_folder_kb([n for n in tree if n.get("type") == "folder"], 0)
        await msg.reply_text(T.WIZ_QN_PICK, reply_markup=kb)
        return


async def cb_qn_folder(query, context, payload: str):
    """ڕاوکردنی بەش بۆ سەرچاوەی پرسیارەکان: qnf:go:<fid> / qnf:back / qnf:ok"""
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "qnsrc":
        return await handlers_user.alert(query, T.WIZ_GONE, K.back_to_panel_kb())
    tree = storage.db()["tree"]
    d = w.setdefault("data", {})
    path = d.get("path") or []

    if payload == "qnf:back":
        if path:
            path.pop()
            d["path"] = path
            storage.set_wizard(chat, w)
        return await _qn_render_folder(query, context, w)

    if payload == "qnf:ok":
        if not path:
            return await handlers_user.alert(query, T.ASK_NEED_PICK)
        fid = path[-1]
        folder = st.find_node(tree, fid)
        n = st.count_questions(folder)
        if not n:
            return await handlers_user.alert(query, T.NO_QUESTIONS)
        d["folder_id"] = fid
        d["n"] = n
        w["step"] = "count"
        storage.set_wizard(chat, w)
        await handlers_user.edit_message(
            query, T.WIZ_QN_COUNT.format(n=st.knum(n)), K.qn_count_kb())
        return

    if payload.startswith("qnf:go:"):
        fid = payload[7:]
        node = st.find_node(tree, fid)
        if not node or node.get("type") != "folder":
            return await handlers_user.alert(query, T.GONE)
        path.append(fid)
        d["path"] = path
        storage.set_wizard(chat, w)
        return await _qn_render_folder(query, context, w)


async def _qn_render_folder(query, context, w):
    storage = _storage(context)
    tree = storage.db()["tree"]
    path = (w.get("data") or {}).get("path") or []
    if path:
        node = st.find_node(tree, path[-1])
        children = [c for c in node.get("children", []) if c.get("type") == "folder"]
    else:
        children = [n for n in tree if n.get("type") == "folder"]
    await handlers_user.edit_message(query, T.WIZ_QN_PICK,
                                     K.qn_folder_kb(children, len(path)))


async def cb_qn_count(query, context, all_flag: bool):
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "qnsrc":
        return await handlers_user.alert(query, T.WIZ_GONE, K.back_to_panel_kb())
    d = w.get("data") or {}
    return await _save_event_count(query, context, w, 0 if all_flag else -1)


async def cb_qn_count_num(query, context, n: int):
    """دوگمەی خێرا: ١٠ یان ٢٠ پرسیار."""
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "qnsrc" or w.get("step") != "count":
        return await handlers_user.alert(query, T.WIZ_GONE, K.back_to_panel_kb())
    if n < 1:
        return await handlers_user.alert(query, T.WIZ_INVALID_NUM)
    return await _save_event_count(query, context, w, n)


async def _save_event_count(query, context, w: dict, count: int):
    """count = 0 → هەمووی؛ count = -1 → وەک خۆی لە داتاوە (بۆ ناردن بە ژمارە)."""
    storage = _storage(context)
    chat = query.message.chat_id
    d = w.get("data") or {}
    chosen = 0 if count == 0 else max(1, int(d.get("count") or 1)) if count < 0 else count
    ev = storage.get_event()
    src = {"type": "folder", "folder_id": d.get("folder_id"), "count": chosen}
    ev = _ev_wizard_common(storage, ev, {
        "title": d.get("title"), "start": d.get("start"),
        "end": d.get("end"), "src": src})
    storage.save_event(ev)
    storage.clear_wizard(chat)
    folder = st.find_node(storage.db()["tree"], d.get("folder_id"))
    src_title = (folder or {}).get("title") or "—"
    n = src["count"] or st.count_questions(folder)
    await handlers_user.alert(
        query, T.A_QN_SRC_SAVED.format(src=src_title, n=st.knum(n)))
    await cb_qnev(query, context)


async def cb_qn_cancel_wiz(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    storage.clear_wizard(chat)
    await handlers_user.alert(query, T.WIZ_CANCELLED, K.back_to_panel_kb())


# ============================================================================
# نامەی گشتی (Notification) بۆ هەموو بەکارهێنەران
# ============================================================================

async def cb_bcast(query, context, data: str):
    storage = _storage(context)
    chat = query.message.chat_id

    if data == "bcast":
        storage.set_wizard(chat, {"flow": "bcast", "step": "msg", "data": {}})
        await handlers_user.edit_message(query, T.WIZ_BCAST, K.wiz_cancel_kb())
        return

    if data == "bcast:no":
        storage.clear_wizard(chat)
        await handlers_user.alert(query, T.BCAST_CANCELLED, K.back_to_panel_kb())
        return

    if data == "bcast:go":
        w = storage.get_wizard(chat)
        d = (w or {}).get("data") or {}
        storage.clear_wizard(chat)
        text = d.get("text") or ""
        photo = d.get("photo")
        users = storage.users_sorted()
        admin_name = (query.from_user.first_name or "ئادمین").strip()
        sent_list = []
        ok_n = fail_n = 0
        BATCH = 20
        for i in range(0, len(users), BATCH):
            batch = users[i:i + BATCH]

            async def _send_one(u):
                try:
                    if photo:
                        m = await fmt.send_photo_html(context.bot, u.get("uid"), photo,
                                                      text or None)
                    else:
                        m = await context.bot.send_message(u.get("uid"), text)
                    if m is not None:
                        sent_list.append((u.get("uid"), m.message_id))
                    return True
                except Exception:
                    return False

            results = await asyncio.gather(*[_send_one(u) for u in batch])
            ok_n += sum(1 for r in results if r)
            fail_n += sum(1 for r in results if not r)
            if i + BATCH < len(users):
                await asyncio.sleep(1.0)

        # پاش ٢ چرکە ناوی ئادمین لە خوارەوەی هەموو نامەکان دەنووسرێت
        async def _sign_all():
            await asyncio.sleep(2.0)
            for cid, mid in sent_list:
                try:
                    if photo:
                        cap = (text or "") + T.ADMIN_SIGN_BCAST.format(name=admin_name)
                        await context.bot.edit_message_caption(
                            chat_id=cid, message_id=mid, caption=cap,
                            parse_mode="HTML")
                    else:
                        await context.bot.edit_message_text(
                            chat_id=cid, message_id=mid,
                            text=text + T.ADMIN_SIGN_BCAST.format(name=admin_name))
                except Exception:
                    pass
        if sent_list:
            asyncio.create_task(_sign_all())

        out = T.BCAST_DONE.format(ok=st.knum(ok_n))
        if fail_n:
            out += "\n" + T.BCAST_FAIL.format(fail=st.knum(fail_n))
        await context.bot.send_message(chat, out, reply_markup=K.back_to_panel_kb())


async def _route_bcast(update, context, w: dict):
    storage = _storage(context)
    msg = update.message
    if not msg:
        return
    chat = msg.chat_id
    d = w.setdefault("data", {})
    text = (msg.text or msg.caption or "").strip()
    photo = msg.photo[-1].file_id if msg.photo else None
    if not text and not photo:
        return await msg.reply_text(T.WIZ_NEED_ITEM)
    d["text"] = text
    d["photo"] = photo
    w["step"] = "confirm"
    storage.set_wizard(chat, w)
    n = storage.count_users()
    preview = st.trunc(text or "🖼", 300)
    await msg.reply_text(T.BCAST_CONFIRM.format(n=st.knum(n), preview=preview),
                         reply_markup=K.bcast_confirm_kb(n))


# ============================================================================
# ڕێگەری ویزاردی ئادمین (زیادکراو)
# ============================================================================

async def route_wizard_extra(update: Update, context: ContextTypes.DEFAULT_TYPE, w: dict):
    """فلۆوە نوێکانی ئادمین: rpreply / usrsearch / qnev / qntime / qnsrc / bcast / usrmsg"""
    flow = w.get("flow")
    data = w.get("data") or {}
    if flow == "rpreply":
        return await _finish_report_reply(update, context, w, data)
    if flow == "usrsearch":
        return await _finish_user_search(update, context, w)
    if flow == "qnev":
        return await _route_qnev(update, context, w)
    if flow == "qntime":
        return await _route_qntime(update, context, w)
    if flow == "qnsrc":
        # ژمارەی پرسیارەکان بە تێکست (ئەگەر لە هەنگاوی count دایە)
        if w.get("step") == "count":
            msg = update.message
            if msg and msg.text:
                n = st.to_int(msg.text)
                if n is None or n < 1 or n > 500:
                    return await msg.reply_text(T.WIZ_INVALID_NUM)
                return await _save_event_src(update, context, w, count=n)
            return await update.message.reply_text(T.WIZ_INVALID_NUM) if update.message else None
        # لە هەنگاوی folder — بە دوگمە
        if update.message:
            return await update.message.reply_text(T.WIZ_USE_BUTTONS)
        return
    if flow == "usrmsg":
        return await _finish_user_msg(update, context, w)
    if flow == "usrban":
        return await _finish_user_ban(update, context, w)
    if flow == "bcast":
        return await _route_bcast(update, context, w)
    # هیچ لقێک وەڵامی نەدەوە — بێدەنگ مەبە (چارەسەری بڕوان)
    msg = update.message
    if msg:
        await msg.reply_text(T.WIZ_NEED_TEXT)


async def _save_event_src(update, context, w: dict, count: int):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    d = w.get("data") or {}
    ev = storage.get_event()
    src = {"type": "folder", "folder_id": d.get("folder_id"), "count": int(count)}
    ev = _ev_wizard_common(storage, ev, {
        "title": d.get("title"), "start": d.get("start"),
        "end": d.get("end"), "src": src})
    storage.save_event(ev)
    storage.clear_wizard(chat)
    folder = st.find_node(storage.db()["tree"], d.get("folder_id"))
    src_title = (folder or {}).get("title") or "—"
    n = src["count"] or st.count_questions(folder)
    try:
        await msg.reply_text(T.A_QN_SRC_SAVED.format(src=src_title, n=st.knum(n)))
    except Exception:
        pass
    await msg.reply_text(T.A_QN_SAVED, reply_markup=K.back_to_panel_kb())


async def _route_qntime(update, context, w: dict):
    import events as evmod
    storage = _storage(context)
    msg = update.message
    if not msg or not msg.text:
        return
    chat = msg.chat_id
    step = w.get("step")
    data = w.setdefault("data", {})
    txt = msg.text.strip()
    if step == "start":
        t = evmod.parse_hhmm(txt)
        if not t:
            return await msg.reply_text(T.WIZ_QN_TIME_BAD)
        data["start"] = t
        w["step"] = "end"
        storage.set_wizard(chat, w)
        await msg.reply_text(T.WIZ_QN_END)
        return
    if step == "end":
        t = evmod.parse_hhmm(txt)
        if not t:
            return await msg.reply_text(T.WIZ_QN_TIME_BAD)
        ev = storage.get_event()
        if not ev:
            storage.clear_wizard(chat)
            return await msg.reply_text(T.A_QN_NONE)
        ev["start"] = data["start"]
        ev["end"] = t
        storage.save_event(ev)
        storage.clear_wizard(chat)
        await msg.reply_text(T.A_QN_TIME_SAVED.format(
            start=evmod.clock_k(ev["start"]), end=evmod.clock_k(ev["end"])))
