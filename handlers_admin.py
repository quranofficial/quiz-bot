# -*- coding: utf-8 -*-
"""پانێڵی ئادمین: بەڕێوەبردنی بەش/پرسیار (بێ سنووری نەوە)، پەڕەکانی زانیاری (کەش)،
ئادمینەکان و ڕێکخستنەکان — دۆخی ویزارد لە داتادا هەڵدەگیرێت تا لەگەڵ
دووبارە دەستپێکردنەکانی GitHub Actions نەمایەوە."""

import json
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


def _storage(context) -> st.Storage:
    return context.bot_data["storage"]


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
                                  storage.count_users()))


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
                     storage.count_users()))


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
    opts = "\n".join(
        "{}) {} {}".format(st.LETTERS[i], o.get("text", ""), "✅" if o.get("correct") else "⬜")
        for i, o in enumerate(q.get("options", [])))
    text = T.Q_VIEW.format(
        text=q.get("text") or T.RESULT_IMG,
        img=("بەڵێ ✅" if q.get("image") else "نەخێر ❌"),
        opts=opts or "—")
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
        lines.append(T.ADMIN_ROW_OWNER.format(uid=config.OWNER_ID))
    others = [a for a in admins if a != config.OWNER_ID]
    if others:
        lines.extend(T.ADMIN_ROW.format(uid=a) for a in others)
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
                if len(data["options"]) >= 6:
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
                if len(data["options"]) >= 6:
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

    if flow == "impjson":
        return await _route_import(update, context, w, data, msg)

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
    if len(w["data"].get("options", [])) < 2:
        try:
            await query.message.reply_text(T.WIZ_NEED_MIN2)
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
    head = T.USER_REPLY_HEAD.format(id=st.knum(tid), reply=fmt.apply(text) if text else "")
    delivered = False
    try:
        if photo:
            await fmt.send_photo_html(context.bot, ticket.get("uid"), photo,
                                      head or "🖼", )
        else:
            await fmt.send_html(context.bot, ticket.get("uid"), head)
        delivered = True
    except Exception as e:
        log.warning("ناردنی وەڵام بۆ بەکارهێنەر: %s", e)

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

_SEC_TITLE_KEYS = ("بەش", "بەشی", "ناو", "نام", "کەرت", "کەرتی",
                   "title", "section", "chapter", "name", "folder")
_CHILD_KEYS = ("کەرتەکان", "بەشەکان", "بەشە ناوەوەکان", "children", "sections",
               "subs", "subsections")
_QS_KEYS = ("پرسیارەکان", "پرسیار", "questions", "qs")
_Q_TEXT_KEYS = ("پرسیار", "پرسیارەکە", "دەق", "question", "q", "text")
_Q_IMG_KEYS = ("وێنە", "وێنەی پرسیار", "image", "img", "photo", "picture")
_Q_OPT_KEYS = ("هەڵبژاردە", "هەڵبژاردەکان", "بژاردە", "options", "opts", "choices")
_Q_ANS_KEYS = ("وەڵام", "وەڵامی ڕاست", "ڕاست", "answer", "correct", "correct_answer")
_Q_EXPL_KEYS = ("ڕوونکردنەوە", "تێبینی", "explanation", "expl", "note")


def _pick(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return None


def _import_question(storage, q, folder_id, stats, errors, where):
    if not isinstance(q, dict):
        errors.append("{}: جۆرەکەی دروست نییە".format(where))
        return
    text = _pick(q, _Q_TEXT_KEYS)
    image = _pick(q, _Q_IMG_KEYS)
    opts = _pick(q, _Q_OPT_KEYS)
    ans = _pick(q, _Q_ANS_KEYS)
    expl = _pick(q, _Q_EXPL_KEYS)

    if not isinstance(opts, list) or len(opts) < 2:
        errors.append("{}: لانیکەم ٢ هەڵبژاردە پێویستە".format(where))
        return
    if len(opts) > 6:
        errors.append("{}: زۆرترین ٦ هەڵبژاردە".format(where))
        return
    opt_texts = [str(o).strip() for o in opts]
    if any(not t for t in opt_texts):
        errors.append("{}: هەڵبژاردەی بەتاڵ ڕێگەپێدراو نییە".format(where))
        return

    idx = None
    if isinstance(ans, bool):
        idx = None
    elif isinstance(ans, int):
        idx = ans - 1  # ژمارەکردن لە ١ ەوە
    elif isinstance(ans, str):
        s2 = ans.strip().translate(st._WESTERN_TABLE)
        if s2.isdigit():
            idx = int(s2) - 1
        elif s2.strip().upper() in st.LETTERS[:6]:
            idx = st.LETTERS.index(s2.strip().upper())
        else:
            for i, t in enumerate(opt_texts):
                if t == ans.strip():
                    idx = i
                    break
    if idx is None or idx < 0 or idx >= len(opt_texts):
        errors.append("{}: وەڵامی ڕاست دیاری نەکراوە (ژمارە ١ بۆ {} یان پیت A-{})".format(
            where, st.knum(len(opt_texts)), st.LETTERS[len(opt_texts) - 1]))
        return

    text_s = str(text).strip()[:3500] if text else ""
    img_s = str(image).strip() if image else ""
    if not text_s and not img_s:
        errors.append("{}: دەق یان وێنە پێویستە".format(where))
        return

    options = [{"text": t, "correct": (i == idx)} for i, t in enumerate(opt_texts)]
    node = storage.add_question(folder_id, text_s, img_s or None, options)
    if isinstance(expl, str) and expl.strip():
        node["expl"] = fmt.plain(expl.strip())[:1000]
        storage.save()
    stats["questions"] += 1


def _import_node(storage, node, parent_id, top, stats, errors, where):
    if not isinstance(node, dict):
        errors.append("{}: جۆرەکەی دروست نییە".format(where))
        return
    qs = _pick(node, _QS_KEYS)
    subs = None
    for k in _CHILD_KEYS:
        if isinstance(node.get(k), list):
            subs = node[k]
            break

    # دیاریکردنی ناوی بەشەکە
    title = None
    if top:
        t1 = node.get("بەش") or node.get("بەشی")
        if isinstance(t1, str) and t1.strip():
            folder, created = storage.ensure_folder("root", t1.strip()[:60])
            if created:
                stats["folders"] += 1
            deeper = folder["id"]
            t2 = node.get("کەرت") or node.get("کەرتی")
            if isinstance(t2, str) and t2.strip():
                folder2, created2 = storage.ensure_folder(deeper, t2.strip()[:60])
                if created2:
                    stats["folders"] += 1
                deeper = folder2["id"]
            title = t1.strip()[:60]
        else:
            t0 = _pick(node, ("کەرت", "کەرتی", "ناو", "نام", "title", "name", "section", "chapter"))
            if isinstance(t0, str) and t0.strip():
                folder, created = storage.ensure_folder("root", t0.strip()[:60])
                if created:
                    stats["folders"] += 1
                deeper = folder["id"]
                title = t0.strip()[:60]
            else:
                # ناوی نییە بەڵام پرسیارەکان لەناودان — بەشێکی خۆکار دروست بکە
                folder, created = storage.ensure_folder("root", "بەشی بێ ناو")
                if created:
                    stats["folders"] += 1
                deeper = folder["id"]
                title = "بەشی بێ ناو"
    else:
        t0 = _pick(node, _SEC_TITLE_KEYS)
        if isinstance(t0, str) and t0.strip():
            folder, created = storage.ensure_folder(parent_id, t0.strip()[:60])
            if created:
                stats["folders"] += 1
            deeper = folder["id"]
            title = t0.strip()[:60]
        else:
            deeper = parent_id

    if title is None and not qs and not subs:
        errors.append("{}: ناوی بەش یان پرسیارەکان نەدۆزرانەوە".format(where))
        return
    if title is None:
        deeper = deeper or parent_id or "root"

    if isinstance(qs, list):
        for qi, q in enumerate(qs, 1):
            _import_question(storage, q, deeper, stats, errors,
                             "{} › پرسیار {}".format(where, qi) if where
                             else "پرسیار {}".format(qi))
    elif qs is not None and not isinstance(qs, list):
        errors.append("{}: «پرسیارەکان» دەبێت لیست بێت".format(where))

    if isinstance(subs, list):
        for si, sub in enumerate(subs, 1):
            _import_node(storage, sub, deeper, False, stats, errors,
                         "{} › بەشی {}".format(where, si) if where
                         else "بەشی {}".format(si))


def import_json_data(storage, raw: str):
    """داتای JSON هەڵدەشێوێت و بۆ دارچینەکە زیادی دەکات.
    گەڕانەوە: (stats, errors) — stats: {"folders": n, "questions": n}"""
    stats = {"folders": 0, "questions": 0}
    errors = []
    data = json.loads(raw)
    if isinstance(data, list):
        for i, item in enumerate(data, 1):
            _import_node(storage, item, "root", True, stats, errors,
                         "بەشی {}".format(st.knum(i)))
    elif isinstance(data, dict):
        wrapper = None
        for k in _CHILD_KEYS:
            if isinstance(data.get(k), list):
                wrapper = data[k]
                break
        if wrapper is not None:
            for i, item in enumerate(wrapper, 1):
                _import_node(storage, item, "root", True, stats, errors,
                             "بەشی {}".format(st.knum(i)))
        elif _pick(data, _QS_KEYS) is not None or "بەش" in data or "کەرت" in data:
            _import_node(storage, data, "root", True, stats, errors, "")
        else:
            raise ValueError(T.IMP_UNKNOWN)
    else:
        raise ValueError(T.IMP_UNKNOWN)
    return stats, errors


async def start_import_json(query, context):
    storage = _storage(context)
    chat = query.message.chat_id
    storage.set_wizard(chat, {"flow": "impjson", "step": "file", "data": {}})
    text = T.IMP_PROMPT + "\n\n" + T.IMP_EXAMPLE + "\n\n" + T.IMP_NOT_FILE
    await handlers_user.edit_message(query, text, K.wiz_cancel_kb())


MAX_IMPORT_BYTES = 2 * 1024 * 1024


async def _route_import(update, context, w, data, msg):
    storage = _storage(context)
    chat = msg.chat_id
    raw = None

    if msg.document:
        doc = msg.document
        if (doc.file_size or 0) > MAX_IMPORT_BYTES:
            return await msg.reply_text(T.IMP_TOO_BIG)
        try:
            tg_file = await doc.get_file()
            path = os.path.join(config.DATA_DIR, "import_{}.json".format(chat))
            await tg_file.download_to_drive(path)
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            os.remove(path)
        except Exception as e:
            log.warning("داگرتنی فایلی JSON: %s", e)
            return await msg.reply_text(T.IMP_NOT_FILE)
    elif msg.text and msg.text.strip():
        raw = msg.text.strip()
    else:
        return await msg.reply_text(T.IMP_NOT_FILE)

    try:
        stats, errors = import_json_data(storage, raw)
    except json.JSONDecodeError as e:
        return await msg.reply_text(T.IMP_BAD.format(err=str(e)[:300]))
    except ValueError as e:
        return await msg.reply_text(str(e))

    storage.clear_wizard(chat)
    if stats["questions"] == 0 and not errors:
        return await msg.reply_text(T.IMP_NONE)

    out = T.IMP_DONE.format(f=st.knum(stats["folders"]), q=st.knum(stats["questions"]))
    if errors:
        shown = errors[:10]
        errs = "\n".join("• " + st.trunc(e, 80) for e in shown)
        if len(errors) > 10:
            errs += "\n• … و {} هەڵەی تر".format(st.knum(len(errors) - 10))
        out += T.IMP_ERRS.format(n=st.knum(len(errors)), errs=errs)
    await msg.reply_text(out, reply_markup=K.after_import_kb())


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
    head = T.RP_USER_HEAD.format(id=st.knum(report.get("id", 0)),
                                 reply=fmt.apply(text) if text else "")
    delivered = False
    try:
        if photo:
            await fmt.send_photo_html(context.bot, report.get("uid"), photo, head or "🖼")
        else:
            await fmt.send_html(context.bot, report.get("uid"), head)
        delivered = True
    except Exception as e:
        log.warning("ناردنی وەڵامی ڕاپۆرت: %s", e)

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

    text = T.A_USR_VIEW.format(
        name=u.get("name") or "—",
        username=u.get("username") or "—",
        uid=u.get("uid") or "—",
        teacher=storage.get_teacher_name(),
        is_t=("بەڵێ ✅" if u.get("teacher") else
              ("نەخێر ❌" if u.get("teacher") is not None else "—")),
        joined=handlers_user.fmt_ts(u.get("joined")),
        last=handlers_user.fmt_ts(stats.get("last_quiz_at") or u.get("joined")),
        quizzes=st.knum(stats.get("quizzes", 0)),
        total=st.knum(total), correct=st.knum(correct), pct=st.knum(pct),
        byfolder=byfolder, qn=qn_txt)
    await handlers_user.edit_message(query, text, K.user_view_kb(uid))


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
    try:
        if photo:
            await fmt.send_photo_html(context.bot, uid, photo, head or "📩")
        else:
            await fmt.send_html(context.bot, uid, head)
    except Exception as e:
        log.warning("ناردنی نامەی تایبەت بۆ %s: %s", uid, e)
        storage.clear_wizard(chat)
        return await msg.reply_text(T.USR_MSG_GONE)

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
    await msg.reply_text(T.A_USR_TITLE.format(
        n=st.knum(len(results)), p=st.knum(1), pp=st.knum(1)),
        reply_markup=InlineKeyboardMarkup(rows))


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
        ok_n = fail_n = 0
        BATCH = 20
        for i in range(0, len(users), BATCH):
            batch = users[i:i + BATCH]

            async def _send_one(u):
                try:
                    if photo:
                        await fmt.send_photo_html(context.bot, u.get("uid"), photo,
                                                  text or None)
                    else:
                        await context.bot.send_message(u.get("uid"), text)
                    return True
                except Exception:
                    return False

            import asyncio
            results = await asyncio.gather(*[_send_one(u) for u in batch])
            ok_n += sum(1 for r in results if r)
            fail_n += sum(1 for r in results if not r)
            if i + BATCH < len(users):
                await asyncio.sleep(1.0)
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
