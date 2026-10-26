# -*- coding: utf-8 -*-
"""پانێڵی ئادمین: بەڕێوەبردنی بەش/پرسیار (بێ سنووری نەوە)، پەڕەکانی زانیاری (کەش)،
ئادمینەکان و ڕێکخستنەکان — دۆخی ویزارد لە داتادا هەڵدەگیرێت تا لەگەڵ
دووبارە دەستپێکردنەکانی GitHub Actions نەمایەوە."""

import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
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
    await msg.reply_text(T.ADMIN_HOME, reply_markup=K.admin_main())


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
    await handlers_user.edit_message(query, T.ADMIN_HOME, K.admin_main())


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
    qpq = _storage(context).db()["settings"].get("questions_per_quiz", 0) or 0
    val = T.SET_ALL_VALUE if qpq <= 0 else st.knum(qpq)
    await handlers_user.edit_message(query, T.A_SETTINGS.format(v=val), K.settings_kb())


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
        return

    if flow == "newfolder" and msg.text and msg.text.strip():
        title = st.trunc(msg.text, 60)
        parent = data.get("parent") or "root"
        storage.add_folder(parent, title)
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_ADDED_FOLDER.format(title=title),
                             reply_markup=K.after_folder_saved_kb(parent))
        return

    if flow == "rename" and msg.text and msg.text.strip():
        title = st.trunc(msg.text, 60)
        fid = data.get("fid")
        storage.rename_folder(fid, title)
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_RENAMED.format(title=title),
                             reply_markup=K.back_to_folder_kb(fid))
        return

    if flow == "newpage" and msg.text and msg.text.strip():
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

    if flow == "addadmin" and msg.text:
        uid = st.to_int(msg.text)
        if uid is None or uid <= 0:
            return await msg.reply_text(T.WIZ_INVALID_NUM)
        added = storage.add_admin(uid)
        storage.clear_wizard(chat)
        text = T.WIZ_ADMIN_ADDED.format(uid=uid) if added else T.WIZ_ADMIN_EXISTS
        await msg.reply_text(text, reply_markup=K.back_to_panel_kb())
        return

    if flow == "setnum" and msg.text:
        n = st.to_int(msg.text)
        if n is None or n < 1 or n > 100:
            return await msg.reply_text(T.WIZ_INVALID_NUM)
        storage.set_questions_per_quiz(n)
        storage.clear_wizard(chat)
        await msg.reply_text(T.WIZ_SAVED_NUM.format(n=st.knum(n)),
                             reply_markup=K.back_to_panel_kb())
        return

    if flow == "editqtext" and msg.text and msg.text.strip():
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
    if not w or w.get("flow") != "addq" or w.get("step") != "image":
        return await _wiz_gone(query)
    _set_step(storage, chat, w, "text")
    await _edit_prompt(context, chat, w, T.WIZ_Q_TEXT, None)


async def wx_done(query, context):
    storage, chat, w = _wiz_of(query, context)
    if not w or w.get("flow") != "addq" or w.get("step") != "options":
        return await _wiz_gone(query)
    if len(w["data"].get("options", [])) < 2:
        try:
            await query.message.reply_text(T.WIZ_NEED_MIN2)
        except Exception:
            pass
        return
    _set_step(storage, chat, w, "correct")
    await _edit_prompt(context, chat, w, T.WIZ_Q_CORRECT, K.wiz_correct_kb(w["data"]["options"]))


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
