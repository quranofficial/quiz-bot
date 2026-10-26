# -*- coding: utf-8 -*-
"""لای بەکارهێنەر: مینیوی سەرەکی، ڕاوکردنی بەشەکان، کویز و ئەنجامەکان."""

import random
import time

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import keyboards as K
import storage as st
import texts as T


def _storage(context) -> st.Storage:
    return context.bot_data["storage"]


# ---------------- یارمەتیدەرە گشتییەکان ----------------

async def edit_message(query, text, kb=None):
    """دەستکاری پەیامی دوگمەکە دەکات؛ ئەگەر نەکرا، پەیامی نوێ دەنێرێت."""
    try:
        await query.edit_message_text(text, reply_markup=kb)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        try:
            await query.message.reply_text(text, reply_markup=kb)
        except Exception:
            pass
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=kb)
        except Exception:
            pass


async def alert(query, text, kb=None):
    try:
        await query.message.reply_text(text, reply_markup=kb)
    except Exception:
        try:
            await query.answer(text, show_alert=True)
        except Exception:
            pass


def chunk_text(s: str, size: int = 3500):
    parts, cur = [], ""
    for line in s.split("\n"):
        if cur and len(cur) + len(line) + 1 > size:
            parts.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    if cur:
        parts.append(cur)
    return parts or [""]


# ---------------- فەرمانەکان ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage = _storage(context)
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    if update.effective_chat:
        storage.clear_wizard(update.effective_chat.id)
    kb = K.main_menu(storage.is_admin(user.id), bool(storage.db()["pages"]))
    await msg.reply_text(T.START.format(name=user.first_name or ""), reply_markup=kb)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(T.HELP, reply_markup=K.home_only())


# ---------------- مینیو و بەشەکان ----------------

async def cb_home(query, context):
    storage = _storage(context)
    kb = K.main_menu(storage.is_admin(query.from_user.id), bool(storage.db()["pages"]))
    await edit_message(query, T.START.format(name=query.from_user.first_name or ""), kb)


async def cb_nav(query, context, fid: str):
    storage = _storage(context)
    tree = storage.db()["tree"]
    if fid in ("", "root"):
        total = sum(st.count_questions(n) for n in tree)
        text = T.SECTIONS_ROOT + T.SECTIONS_INFO.format(n=st.knum(total))
        if not tree:
            text += "\n\n" + T.NO_SECTIONS
        kb = K.user_folder(None, None, tree)
    else:
        folder = st.find_node(tree, fid)
        if not folder or folder.get("type") != "folder":
            return await alert(query, T.GONE, K.home_only())
        parent_fid = st.find_parent_folder_id(tree, fid)
        children = folder.get("children", [])
        subs = sum(1 for c in children if c.get("type") == "folder")
        direct = sum(1 for c in children if c.get("type") == "question")
        text = T.FOLDER_INFO.format(
            title=folder.get("title", "?"),
            subs=st.knum(subs), direct=st.knum(direct),
            total=st.knum(st.count_questions(folder)))
        kb = K.user_folder(folder, None if parent_fid in (None, "root") else parent_fid, tree)
    await edit_message(query, text, kb)


# ---------------- کویز ----------------

async def cb_quiz(query, context, fid: str):
    storage = _storage(context)
    tree = storage.db()["tree"]
    if fid in ("", "root"):
        folder = None
        title = T.QUIZ_ALL_TITLE
        questions = [q for n in tree for q in st.collect_questions(n)]
    else:
        folder = st.find_node(tree, fid)
        if not folder or folder.get("type") != "folder":
            return await alert(query, T.GONE, K.home_only())
        title = folder.get("title", "?")
        questions = st.collect_questions(folder)

    if not questions:
        return await alert(query, T.NO_QUESTIONS, K.home_only())

    random.shuffle(questions)
    qpq = storage.db()["settings"].get("questions_per_quiz") or 0
    if qpq and qpq > 0:
        questions = questions[:qpq]

    session = {
        "uid": query.from_user.id,
        "folder_id": fid or "root",
        "folder_title": title,
        "qids": [q["id"] for q in questions],
        "idx": 0,
        "answers": [],
        "ts": time.time(),
    }
    storage.clean_old_sessions()
    storage.set_session(query.from_user.id, session)

    chat_id = query.message.chat_id
    try:
        await query.message.reply_text(T.QUIZ_START.format(title=title, n=st.knum(len(questions))))
    except Exception:
        pass
    await send_quiz_question(context, chat_id, session)


async def send_quiz_question(context, chat_id, session):
    storage = _storage(context)
    tree = storage.db()["tree"]

    # پرسیارە سڕدراوەکان بە تێپەڕ ببە
    while session["idx"] < len(session["qids"]):
        if st.find_node(tree, session["qids"][session["idx"]]):
            break
        session["idx"] += 1

    if session["idx"] >= len(session["qids"]):
        return await finish_quiz(context, chat_id, session)

    q = st.find_node(tree, session["qids"][session["idx"]])
    header = T.Q_PROGRESS.format(i=st.knum(session["idx"] + 1), n=st.knum(len(session["qids"])))
    qtext = (q.get("text") or "").strip()
    kb = K.quiz_options(q["id"], q.get("options", []))
    img = q.get("image")
    try:
        if img:
            cap = (header + "\n\n" + qtext).strip()
            if len(cap) > 1000:
                await context.bot.send_photo(chat_id, img, caption=header)
                await context.bot.send_message(chat_id, qtext, reply_markup=kb)
            else:
                await context.bot.send_photo(chat_id, img, caption=cap or header, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id, "{}\n\n{}".format(header, qtext), reply_markup=kb)
    except Exception:
        # لەوانەیە file_id ی وێنەکە چیتر دروست نەبێتەوە
        try:
            await context.bot.send_message(
                chat_id, "{}\n\n{}".format(header, qtext or T.RESULT_IMG), reply_markup=kb)
        except Exception:
            pass


async def cb_answer(query, context, qid: str, idx: int):
    storage = _storage(context)
    tree = storage.db()["tree"]
    uid = query.from_user.id
    s = storage.get_session(uid)
    if not s or s.get("uid") != uid:
        return await alert(query, T.SESSION_GONE, K.home_only())

    if s.get("idx", 0) >= len(s.get("qids", [])) or s["qids"][s["idx"]] != qid:
        try:
            await query.message.reply_text(T.ALREADY_ANSWERED)
        except Exception:
            pass
        return

    q = st.find_node(tree, qid)
    if not q:
        s["idx"] = s.get("idx", 0) + 1
        storage.set_session(uid, s)
        return await send_quiz_question(context, query.message.chat_id, s)

    options = q.get("options", [])
    if idx < 0 or idx >= len(options):
        return

    correct = bool(options[idx].get("correct"))
    right_idx = next((i for i, o in enumerate(options) if o.get("correct")), None)
    chosen = "{}) {}".format(st.LETTERS[idx], st.trunc(options[idx].get("text", ""), 80))
    right = ("{}) {}".format(st.LETTERS[right_idx], st.trunc(options[right_idx].get("text", ""), 80))
             if right_idx is not None else None)

    s.setdefault("answers", []).append({
        "qid": qid,
        "correct": correct,
        "qtext": st.trunc(q.get("text") or "", 120),
        "chosen": chosen,
        "right": right,
        "has_image": bool(q.get("image")),
    })
    s["idx"] = s.get("idx", 0) + 1
    storage.set_session(uid, s)

    # دوگمەکان بگۆڕە بۆ نیشانەی وەڵامی هەڵبژێردراو
    try:
        await query.edit_message_reply_markup(
            reply_markup=K.answered_marker(correct, st.LETTERS[idx], options[idx].get("text", "")))
    except Exception:
        pass

    try:
        await query.message.reply_text(
            T.CORRECT_FB if correct else T.WRONG_FB.format(a=right or T.RESULT_NONE))
    except Exception:
        pass

    await send_quiz_question(context, query.message.chat_id, s)


def build_results(session, tree) -> str:
    answers = session.get("answers", [])
    total = len(answers)
    correct = sum(1 for a in answers if a.get("correct"))
    wrong = total - correct
    pct = int(round(correct * 100.0 / total)) if total else 0
    if pct >= 80:
        foot = T.MSG_GREAT
    elif pct >= 50:
        foot = T.MSG_GOOD
    else:
        foot = T.MSG_TRY

    head = T.RESULT_TITLE.format(
        title=session.get("folder_title", "-"),
        c=st.knum(correct), w=st.knum(wrong), p=st.knum(pct))

    blocks = []
    for i, a in enumerate(answers, 1):
        mark = "✅" if a.get("correct") else "❌"
        qlabel = a.get("qtext") or (T.RESULT_IMG if a.get("has_image") else T.RESULT_NONE)
        block = [
            T.RESULT_ITEM.format(i=st.knum(i), mark=mark, q=st.trunc(qlabel, 120)),
            T.RESULT_YOURS.format(a=a.get("chosen") or T.RESULT_NONE),
        ]
        if not a.get("correct") and a.get("right"):
            block.append(T.RESULT_RIGHT.format(a=a["right"]))
        blocks.append("\n".join(block))

    return head + "\n" + "\n\n".join(blocks) + T.RESULT_FOOT.format(msg=foot)


async def finish_quiz(context, chat_id, session):
    storage = _storage(context)
    text = build_results(session, storage.db()["tree"])
    chunks = chunk_text(text)
    kb = K.results_kb(session.get("folder_id", "root"))
    for i, chunk in enumerate(chunks):
        try:
            if i == len(chunks) - 1:
                await context.bot.send_message(chat_id, chunk, reply_markup=kb)
            else:
                await context.bot.send_message(chat_id, chunk)
        except Exception:
            pass
    uid = session.get("uid")
    if uid is not None:
        storage.del_session(uid)


# ---------------- پەڕەکانی زانیاری ----------------

async def cb_pages(query, context):
    pages = _storage(context).db()["pages"]
    if not pages:
        return await alert(query, T.NO_PAGES, K.home_only())
    await edit_message(query, T.PAGES_TITLE, K.pages_list(pages))


async def cb_page(query, context, pid: str):
    pages = _storage(context).db()["pages"]
    page = next((p for p in pages if p.get("id") == pid), None)
    if not page:
        return await alert(query, T.PAGE_GONE)
    chat_id = query.message.chat_id
    try:
        await context.bot.send_message(chat_id, T.PAGE_HEADER.format(title=page.get("title", "?")))
    except Exception:
        pass
    for item in page.get("items", []):
        try:
            if item["type"] == "text":
                await context.bot.send_message(chat_id, item.get("content", ""))
            elif item["type"] == "photo":
                await context.bot.send_photo(chat_id, item.get("content"),
                                             caption=item.get("caption") or None)
            elif item["type"] == "document":
                await context.bot.send_document(chat_id, item.get("content"),
                                                caption=item.get("caption") or None)
        except Exception:
            pass
    try:
        await context.bot.send_message(chat_id, T.PAGE_END, reply_markup=K.page_back())
    except Exception:
        pass
