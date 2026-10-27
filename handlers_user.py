# -*- coding: utf-8 -*-
"""لای بەکارهێنەر: مینیوی سەرەکی، ڕاوکردنی بەشەکان، تاقیکردنەوە (لەگەڵ هەڵبژاردنی ژمارە)،
تاقیکردنەوەی تایبەت، ڕاپۆرتکردنی کێشە، فڵاشکارت، تاقیکردنەوەی شەوانە و ئامار."""

import random
import time
import datetime as _dt

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import events as evmod
import fmtutil as fmt
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


async def edit_any(query, text, kb=None):
    """دەستکاری پەیامێک کە لەوانەیە وێنە بێت (کاپشن) — بۆ فڵاشکارت."""
    try:
        await query.edit_message_text(text, reply_markup=kb)
        return
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
    except Exception:
        pass
    try:
        await query.edit_message_caption(caption=text, reply_markup=kb)
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


async def reject_banned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """دەرگای باند — ئەگەر بەکارهێنەرەکە باندکراو بێت، هۆکارەکەی پیشان دەدرێت
    و هەموو داواکارییەکانی ڕادەگیرێت. True ئەگەر ڕاگیرابێت."""
    storage = _storage(context)
    user = update.effective_user
    if not user or storage.is_admin(user.id) or not storage.is_banned(user.id):
        return False
    ban = storage.get_ban_info(user.id) or {}
    reason = (ban.get("reason") or "").strip()
    text = T.BAN_NOTICE.format(reason=reason or "—")
    msg = update.effective_message
    try:
        if msg is not None:
            await msg.reply_text(text)
        else:
            await context.bot.send_message(user.id, text)
    except Exception:
        pass
    return True


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


def fmt_ts(ts) -> str:
    """کاتی عێراق/کوردستان (UTC+3) — نەک کاتی سیستەم کە لە GitHub دا UTC ـە."""
    try:
        tz = _dt.timezone(_dt.timedelta(hours=3))
        return _dt.datetime.fromtimestamp(int(ts), tz).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "—"


def _collect_for_fid(storage, fid: str):
    """(title, questions) بۆ بەشێک یان هەموو دارچینەکە.
    پرسیارە بێ وەڵامەکان (کە هێشتا وەڵامی ڕاستیان دیاری نەکراوە) نایەنەوە."""
    tree = storage.db()["tree"]
    if fid in ("", "root"):
        return T.QUIZ_ALL_TITLE, [q for n in tree for q in st.collect_questions(n)
                                  if st.has_correct(q)]
    folder = st.find_node(tree, fid)
    if not folder or folder.get("type") != "folder":
        return None, []
    return folder.get("title", "?"), [q for q in st.collect_questions(folder)
                                      if st.has_correct(q)]


# ---------------- فەرمانەکان ----------------

def _main_menu(storage, user):
    return K.main_menu(storage, user)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage = _storage(context)
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    # دەرگای باند — بەکارهێنەری باندکراو ناتوانێت بۆتەکە بەکاربهێنێت
    if await reject_banned(update, context):
        return
    if update.effective_chat:
        storage.clear_wizard(update.effective_chat.id)
    # تۆمارکردنی یەکەم جار: ناو + قوتابی مامۆستا
    if not storage.get_user(user.id):
        storage.save_user(user.id, {
            "name": (user.first_name or "بەکارهێنەر")[:40],
            "teacher": None,
            "username": ("@" + user.username) if user.username else "",
            "joined": int(time.time()),
        })
        storage.set_wizard(update.effective_chat.id,
                           {"flow": "reg", "step": "name", "data": {}})
        await msg.reply_text(T.REG_NAME)
        return
    profile = storage.get_user(user.id) or {}
    if not profile.get("name") or (profile.get("teacher") is None
                                   and not storage.is_admin(user.id)):
        # تۆمارکردن ناتەواوە — دووبارە بەردەوام بە (ئادمین: تەنها ناو پێویستە)
        storage.set_wizard(update.effective_chat.id,
                           {"flow": "reg", "step": "name",
                            "data": {"name": profile.get("name") or "",
                                     "redo": True}})
        await msg.reply_text(T.REG_NAME)
        return
    kb = _main_menu(storage, user)
    await msg.reply_text(T.START.format(name=profile.get("name") or user.first_name or ""),
                         reply_markup=kb)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_banned(update, context):
        return
    if update.effective_message:
        await update.effective_message.reply_text(T.HELP, reply_markup=K.home_only())


# ---------------- مینیو و بەشەکان ----------------

async def cb_home(query, context):
    """گەڕانەوە بۆ مینیوی سەرەکی — هەر ویزارد و دانیشتەیەکی تاقیکردنەوە دەوەستێت."""
    storage = _storage(context)
    try:
        chat_id = query.message.chat_id
    except Exception:
        return
    uid = query.from_user.id
    storage.clear_wizard(chat_id)
    if storage.get_session(uid):
        storage.del_session(uid)
    profile = storage.get_user(uid)
    if not profile:
        storage.set_wizard(chat_id, {"flow": "reg", "step": "name", "data": {}})
        return await edit_message(query, T.REG_NAME, None)
    if not profile.get("name") or profile.get("teacher") is None:
        storage.set_wizard(chat_id, {"flow": "reg", "step": "name",
                                     "data": {"name": profile.get("name") or "",
                                              "redo": True}})
        return await edit_message(query, T.REG_NAME, None)
    kb = _main_menu(storage, query.from_user)
    await edit_message(query,
                       T.START.format(name=profile.get("name") or query.from_user.first_name or ""),
                       kb)


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


# ---------------- تاقیکردنەوە: هەڵبژاردنی ژمارە + دەستپێکردن ----------------

async def cb_quiz(query, context, fid: str):
    """پیشاندانی ٣ بژاردە پێش دەستپێکردن: ١٠ / هەموو / ژمارەیەک دیاری بکە."""
    storage = _storage(context)
    title, questions = _collect_for_fid(storage, fid)
    if title is None or not questions:
        return await alert(query, T.NO_QUESTIONS, K.home_only())
    n = len(questions)
    await edit_message(query,
                       T.QS_TITLE.format(title=title, n=st.knum(n)),
                       K.quiz_start_options(fid or "root", n))


def _make_session(user, title, questions, folder_id, src="section",
                  event_id=None, date=None, extra=None):
    return {
        "uid": user.id,
        "folder_id": folder_id or "root",
        "folder_title": title,
        "qids": [q["id"] for q in questions],
        "idx": 0,
        "answers": [],
        "ts": time.time(),
        "src": src,
        "event_id": event_id,
        "date": date,
        "extra": extra or {},   # پرسیارەکانی بەنکۆی شەوانە (دەرەوەی دارچین)
    }


async def _launch_quiz(context, chat_id, user, title, questions, folder_id,
                       src="section", event_id=None, date=None, extra=None):
    storage = _storage(context)
    random.shuffle(questions)
    session = _make_session(user, title, questions, folder_id, src, event_id, date,
                            extra=extra)
    storage.clean_old_sessions()
    storage.set_session(user.id, session)
    try:
        await context.bot.send_message(
            chat_id, T.QUIZ_START.format(title=title, n=st.knum(len(questions))))
    except Exception:
        pass
    await send_quiz_question(context, chat_id, session)


async def cb_qs(query, context, fid: str, mode: str):
    """دەستپێکردنی تاقیکردنەوە بە یەکێک لە بژاردەکان: ten / all / num."""
    storage = _storage(context)
    chat_id = query.message.chat_id
    user = query.from_user

    if fid == "custom":
        w = storage.get_wizard(chat_id)
        pool = ((w or {}).get("data") or {}).get("pool") or []
        tree = storage.db()["tree"]
        questions = [st.find_node(tree, q) for q in pool]
        questions = [q for q in questions if q and q.get("type") == "question"]
        title = T.MQ_TITLE_NAME
    else:
        title, questions = _collect_for_fid(storage, fid)
    if not questions:
        return await alert(query, T.NO_QUESTIONS, K.home_only())

    if mode == "num":
        storage.set_wizard(chat_id, {"flow": "quiznum", "step": "num",
                                     "data": {"fid": fid or "root",
                                              "title": title,
                                              "n": len(questions)}})
        try:
            await query.message.reply_text(T.QS_NUM_PROMPT.format(n=st.knum(len(questions))))
        except Exception:
            pass
        return

    if mode == "ten":
        random.shuffle(questions)
        questions = questions[:10]
    return await _launch_quiz(context, chat_id, user, title, questions,
                              None if fid in ("", "root") else fid)


async def send_quiz_question(context, chat_id, session):
    storage = _storage(context)
    tree = storage.db()["tree"]
    extra = session.get("extra") or {}

    # پرسیارە سڕدراوەکان بە تێپەڕ ببە (پرسیارەکانی بەنکۆکە لە extra دا هەن)
    while session["idx"] < len(session["qids"]):
        qid = session["qids"][session["idx"]]
        if st.find_node(tree, qid) or qid in extra:
            break
        session["idx"] += 1

    if session["idx"] >= len(session["qids"]):
        return await finish_quiz(context, chat_id, session)

    qid = session["qids"][session["idx"]]
    q = st.find_node(tree, qid) or extra.get(qid)
    if not q:
        return await finish_quiz(context, chat_id, session)
    header = T.Q_PROGRESS.format(i=st.knum(session["idx"] + 1), n=st.knum(len(session["qids"])))
    qtext = (q.get("text") or "").strip()
    qtext_html = fmt.apply(qtext)
    kb = K.quiz_options(q["id"], q.get("options", []))
    img = q.get("image")
    try:
        if img:
            cap = (header + "\n\n" + qtext_html).strip()
            if len(cap) > 1000:
                await fmt.send_photo_html(context.bot, chat_id, img, header)
                await fmt.send_html(context.bot, chat_id, qtext_html, reply_markup=kb)
            else:
                await fmt.send_photo_html(context.bot, chat_id, img, cap or header,
                                          reply_markup=kb)
        else:
            await fmt.send_html(context.bot, chat_id,
                                "{}\n\n{}".format(header, qtext_html), reply_markup=kb)
    except Exception:
        # لەوانەیە file_id ی وێنەکە چیتر دروست نەبێتەوە
        try:
            await fmt.send_html(
                context.bot, chat_id,
                "{}\n\n{}".format(header, fmt.apply(qtext) or T.RESULT_IMG), reply_markup=kb)
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

    extra = s.get("extra") or {}
    q = st.find_node(tree, qid) or extra.get(qid)
    if not q:
        s["idx"] = s.get("idx", 0) + 1
        storage.set_session(uid, s)
        return await send_quiz_question(context, query.message.chat_id, s)

    options = q.get("options", [])
    if idx < 0 or idx >= len(options):
        return

    correct = bool(options[idx].get("correct"))
    right_idx = next((i for i, o in enumerate(options) if o.get("correct")), None)

    def lab(i, html=False):
        t = options[i].get("text", "")
        return "{}) {}".format(st.LETTERS[i], (fmt.apply(t) if html else fmt.plain(t)))

    s.setdefault("answers", []).append({
        "qid": qid,
        "correct": correct,
        "qtext": st.trunc(fmt.plain(q.get("text") or ""), 120),
        "chosen": st.trunc(lab(idx), 90),
        "right": (st.trunc(lab(right_idx), 90) if right_idx is not None else None),
        "has_image": bool(q.get("image")),
    })
    s["idx"] = s.get("idx", 0) + 1
    storage.set_session(uid, s)

    # دوگمەکان بگۆڕە بۆ نیشانەی وەڵامی هەڵبژێردراو
    try:
        await query.edit_message_reply_markup(
            reply_markup=K.answered_marker(correct, st.LETTERS[idx],
                                           fmt.plain(options[idx].get("text", ""))))
    except Exception:
        pass

    try:
        if correct:
            fb = T.CORRECT_FB
        else:
            right_html = lab(right_idx, html=True) if right_idx is not None else T.RESULT_NONE
            fb = T.WRONG_FB.format(a=right_html)
            if q.get("expl"):
                fb += "\n💡 " + fmt.apply(str(q["expl"]))
        await fmt.send_html(context.bot, query.message.chat_id, fb)
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
    uid = session.get("uid")
    answers = session.get("answers", [])
    total = len(answers)
    correct = sum(1 for a in answers if a.get("correct"))
    pct = int(round(correct * 100.0 / total)) if total else 0

    # ١) ئاماری بەکارهێنەر
    if uid is not None:
        storage.record_quiz_result(uid, session.get("folder_title", ""), correct, total)
        storage.set_last_quiz(uid, {
            "qids": session.get("qids", []),
            "title": session.get("folder_title", ""),
            "ts": int(time.time()),
        })

    # ٢) ئەگەر تاقیکردنەوەی شەوانەیە — ئەنجامەکە تۆمار بکە
    if session.get("src") == "event" and uid is not None:
        ev = storage.get_event()
        if ev and session.get("event_id") == ev.get("id"):
            profile = storage.get_user(uid) or {}
            evmod.add_result(ev, uid, {
                "name": profile.get("name") or "بەکارهێنەر",
                "username": profile.get("username") or "",
                "score": correct, "total": total, "pct": pct,
                "at": int(time.time()),
            }, date=session.get("date"))
            evmod.cleanup(ev)
            storage.save_event(ev)

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
    if uid is not None:
        storage.del_session(uid)


# ---------------- تاقیکردنەوەی تایبەت (چەند بەشێک لە یەک تاقیکردنەوە) ----------------

def _is_ancestor_or_descendant(tree, a: str, b: str) -> bool:
    """ئایا a و b باپیر-نەوەن (لە هەر ئاراستەیەکدا)؟"""
    # a باپیری b ـە؟ (باوکانی b بپشکنە)
    cur = b
    while True:
        p = st.find_parent_folder_id(tree, cur)
        if p in (None, "root"):
            break
        if p == a:
            return True
        cur = p
    # b باپیری a ـە؟ (باوکانی a بپشکنە)
    cur = a
    while True:
        p = st.find_parent_folder_id(tree, cur)
        if p in (None, "root"):
            break
        if p == b:
            return True
        cur = p
    return False


async def _mq_render(query, context, w):
    storage = _storage(context)
    tree = storage.db()["tree"]
    d = w.setdefault("data", {})
    sel = d.get("sel") or []
    path = d.get("path") or []
    # پاککردنەوەی ڕێڕەوی سڕدراوە
    for fid in list(path):
        node = st.find_node(tree, fid)
        if not node or node.get("type") != "folder":
            d["path"] = []
            path = []
            storage.set_wizard(query.message.chat_id, w)
            break
    if path:
        node = st.find_node(tree, path[-1])
        children = [c for c in node.get("children", []) if c.get("type") == "folder"]
    else:
        children = [n for n in tree if n.get("type") == "folder"]
    kb = K.custom_quiz_kb(children, len(path), sel, len(sel))
    await edit_message(query, T.MQ_TITLE.format(n=st.knum(len(sel))), kb)


async def cb_mq(query, context, data: str):
    storage = _storage(context)
    chat_id = query.message.chat_id
    tree = storage.db()["tree"]

    if data == "mq":
        storage.set_wizard(chat_id, {"flow": "mq", "step": "sel",
                                     "data": {"sel": [], "path": []}})
        return await _mq_render(query, context, storage.get_wizard(chat_id))

    w = storage.get_wizard(chat_id)
    if not w or w.get("flow") != "mq":
        return await alert(query, T.WIZ_GONE, K.home_only())
    d = w.setdefault("data", {})
    sel = d.get("sel") or []
    path = d.get("path") or []

    if data == "mq:back":
        if path:
            path.pop()
            d["path"] = path
            storage.set_wizard(chat_id, w)
        return await _mq_render(query, context, w)

    if data == "mq:clear":
        d["sel"] = []
        storage.set_wizard(chat_id, w)
        return await _mq_render(query, context, w)

    if data.startswith("mq:go:"):
        fid = data[6:]
        node = st.find_node(tree, fid)
        if not node or node.get("type") != "folder":
            return await alert(query, T.GONE)
        path.append(fid)
        d["path"] = path
        storage.set_wizard(chat_id, w)
        return await _mq_render(query, context, w)

    if data.startswith("mq:toggle:"):
        fid = data[10:]
        node = st.find_node(tree, fid)
        if not node or node.get("type") != "folder":
            return await alert(query, T.GONE)
        if fid in sel:
            sel.remove(fid)
        else:
            if len(sel) >= 4:
                return await alert(query, T.MQ_MAX)
            # باپیر و نەوەکان لاببە بۆ ڕێگری لە تێکەڵبوون
            for other in list(sel):
                if _is_ancestor_or_descendant(tree, other, fid) or \
                   _is_ancestor_or_descendant(tree, fid, other):
                    sel.remove(other)
            sel.append(fid)
        d["sel"] = sel
        storage.set_wizard(chat_id, w)
        return await _mq_render(query, context, w)

    if data == "mq:start":
        if len(sel) < 2:
            return await alert(query, T.MQ_NEED_MORE)
        seen, questions = set(), []
        for fid in sel:
            node = st.find_node(tree, fid)
            if node:
                for q in st.collect_questions(node):
                    if q["id"] not in seen and st.has_correct(q):
                        seen.add(q["id"])
                        questions.append(q)
        if not questions:
            return await alert(query, T.MQ_NO_QUESTIONS)
        storage.set_wizard(chat_id, {"flow": "quiznum", "step": "pool",
                                     "data": {"pool": [q["id"] for q in questions],
                                              "title": T.MQ_TITLE_NAME,
                                              "n": len(questions)}})
        await edit_message(query,
                           T.QS_TITLE.format(title=T.MQ_TITLE_NAME, n=st.knum(len(questions))),
                           K.quiz_start_options("custom", len(questions)))


# ---------------- ڕاپۆرتکردنی کێشە (لای بەکارهێنەر) ----------------

async def cb_report(query, context, data: str):
    storage = _storage(context)
    chat_id = query.message.chat_id
    tree = storage.db()["tree"]

    if data == "rp":
        profile = storage.get_user(query.from_user.id) or {}
        last = profile.get("last_quiz")
        if not last or not last.get("qids"):
            return await alert(query, T.RP_NO_QUIZ)
        qids = last["qids"][:25]
        storage.set_wizard(chat_id, {"flow": "report", "step": "pick",
                                     "data": {"qids": qids,
                                              "title": last.get("title", "")}})
        return await edit_message(query,
                                  T.RP_PICK.format(title=last.get("title", "—")),
                                  K.report_pick_kb(qids, tree))

    w = storage.get_wizard(chat_id)
    if not w or w.get("flow") != "report":
        return await alert(query, T.WIZ_GONE, K.home_only())
    d = w.setdefault("data", {})

    if data.startswith("rp:pick:"):
        try:
            idx = int(data[8:])
        except ValueError:
            return
        qids = d.get("qids") or []
        if idx < 0 or idx >= len(qids):
            return await alert(query, T.RP_GONE)
        node = st.find_node(tree, qids[idx])
        if not node:
            return await alert(query, T.RP_GONE)
        d["qid"] = node["id"]
        d["qtext"] = st.trunc(fmt.plain(node.get("text") or "") or "🖼", 200)
        w["step"] = "comment"
        storage.set_wizard(chat_id, w)
        try:
            await query.message.reply_text(
                T.RP_COMMENT.format(q=d["qtext"]), reply_markup=K.report_comment_kb())
        except Exception:
            pass
        return

    if data == "rp:skip":
        return await _send_report(query, context, w, "")


async def _send_report(query, context, w: dict, comment: str):
    storage = _storage(context)
    chat_id = query.message.chat_id
    user = query.from_user
    d = w.get("data") or {}
    profile = storage.get_user(user.id) or {}
    report = {
        "id": storage.next_report_id(),
        "uid": user.id,
        "name": profile.get("name") or user.first_name or "بەکارهێنەر",
        "username": ("@" + user.username) if user.username else "",
        "quiz": d.get("title") or "—",
        "qid": d.get("qid"),
        "qtext": d.get("qtext") or "—",
        "comment": (comment or "").strip()[:500],
        "status": "open",
        "created": int(time.time()),
        "replies": [],
        "admin_msgs": {},
    }
    storage.create_report(report)
    storage.clear_wizard(chat_id)
    try:
        await query.message.reply_text(T.RP_SENT)
    except Exception:
        pass
    import handlers_admin  # import ی ناوخۆیی — بۆ ڕێگرتن لە سووڕی import
    try:
        await handlers_admin.notify_new_report(context, report)
    except Exception:
        pass


# ---------------- فڵاشکارت ----------------

async def cb_fc(query, context, data: str):
    storage = _storage(context)
    chat_id = query.message.chat_id
    uid = query.from_user.id

    if data == "fc":
        n = len(storage.get_flashcards(uid))
        return await edit_message(query, T.FC_TITLE.format(n=st.knum(n)), K.fc_menu(n))

    if data == "fc:add":
        if not storage.get_user(uid):
            return await alert(query, T.HINT_START, K.home_only())
        storage.set_wizard(chat_id, {"flow": "fcadd", "step": "front", "data": {}})
        try:
            await query.message.reply_text(T.FC_FRONT, reply_markup=K.fc_stop_kb())
        except Exception:
            pass
        return

    if data == "fc:stopadd":
        storage.clear_wizard(chat_id)
        n = len(storage.get_flashcards(uid))
        return await edit_message(query, T.FC_TITLE.format(n=st.knum(n)), K.fc_menu(n))

    if data == "fc:noimg":
        # پاشەکەوتکردنی کارتەکە بەبێ وێنە
        w = storage.get_wizard(chat_id)
        if not w or w.get("flow") != "fcadd":
            return await alert(query, T.WIZ_GONE, K.home_only())
        d = w.get("data") or {}
        storage.add_flashcard(uid, d.get("front", ""), d.get("back", ""), None)
        storage.clear_wizard(chat_id)
        try:
            await query.answer(T.FC_SAVED)
        except Exception:
            pass
        n = len(storage.get_flashcards(uid))
        return await edit_message(query, T.FC_TITLE.format(n=st.knum(n)), K.fc_menu(n))

    if data == "fc:stopstudy":
        n = len(storage.get_flashcards(uid))
        return await edit_message(query, T.FC_TITLE.format(n=st.knum(n)), K.fc_menu(n))

    if data == "fc:study":
        cards = storage.get_flashcards(uid)
        if not cards:
            return await alert(query, T.FC_EMPTY, K.home_only())
        return await _send_fc_card(context, chat_id, cards, 0)

    if data.startswith("fc:show:"):
        try:
            i = int(data[8:])
        except ValueError:
            return
        cards = storage.get_flashcards(uid)
        if i < 0 or i >= len(cards):
            return await alert(query, T.FC_GONE, K.home_only())
        card = cards[i]
        text = "{}\n\n{}\n\n—\n✅ {}".format(
            T.FC_STUDY_HEAD.format(i=st.knum(i + 1), n=st.knum(len(cards))),
            fmt.apply(card.get("front", "")), fmt.apply(card.get("back", "")))
        await edit_any(query, text, K.fc_reveal_kb(i))
        return

    if data.startswith("fc:next:"):
        try:
            i = int(data[8:])
        except ValueError:
            return
        cards = storage.get_flashcards(uid)
        nxt = i + 1
        if nxt >= len(cards):
            return await edit_message(
                query, T.FC_DONE.format(n=st.knum(len(cards))), K.fc_end_kb(len(cards)))
        return await _send_fc_card(context, chat_id, cards, nxt, edit_query=query)

    if data == "fc:del":
        cards = storage.get_flashcards(uid)
        if not cards:
            return await alert(query, T.FC_EMPTY, K.home_only())
        return await edit_message(query, T.FC_DEL_TITLE, K.fc_del_list(cards))

    if data.startswith("fc:deli:"):
        cid = data[8:]
        storage.delete_flashcard(uid, cid)
        cards = storage.get_flashcards(uid)
        try:
            await query.answer(T.FC_DELETED)
        except Exception:
            pass
        if not cards:
            return await edit_message(query, T.FC_TITLE.format(n=st.knum(0)), K.fc_menu(0))
        return await edit_message(query, T.FC_DEL_TITLE, K.fc_del_list(cards))


async def _send_fc_card(context, chat_id, cards, i, edit_query=None):
    card = cards[i]
    head = T.FC_STUDY_HEAD.format(i=st.knum(i + 1), n=st.knum(len(cards)))
    text = "{}\n\n{}".format(head, fmt.apply(card.get("front", "")))
    kb = K.fc_study_kb(i)
    photo = card.get("photo")
    try:
        if edit_query is not None and photo is None:
            await edit_message(edit_query, text, kb)
            return
        if photo:
            await fmt.send_photo_html(context.bot, chat_id, photo, text, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id, text, reply_markup=kb)
    except Exception:
        try:
            await context.bot.send_message(chat_id, text, reply_markup=kb)
        except Exception:
            pass


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
                await fmt.send_html(context.bot, chat_id, fmt.apply(item.get("content", "")))
            elif item["type"] == "photo":
                cap = fmt.apply(item.get("caption") or "")
                await fmt.send_photo_html(context.bot, chat_id, item.get("content"),
                                          caption=cap or None)
            elif item["type"] == "document":
                await context.bot.send_document(chat_id, item.get("content"),
                                                caption=item.get("caption") or None)
        except Exception:
            pass
    try:
        await context.bot.send_message(chat_id, T.PAGE_END, reply_markup=K.page_back())
    except Exception:
        pass


# ---------------- تۆمارکردنی بەکارهێنەر (/start) ----------------

async def route_reg(update: Update, context: ContextTypes.DEFAULT_TYPE, w: dict):
    storage = _storage(context)
    msg = update.message
    if not msg or not msg.from_user:
        return False
    chat = msg.chat_id
    step = w.get("step")

    if step == "name":
        name = (msg.text or "").strip()
        if len(name) < 2 or len(name) > 40:
            await msg.reply_text(T.REG_NAME_ERR)
            return True
        w.setdefault("data", {})["name"] = st.trunc(name, 40)
        # ئادمین: تەنها ناو — پرسیاری قوتابی مامۆستا ناکرێت
        if storage.is_admin(msg.from_user.id):
            user = msg.from_user
            old = storage.get_user(user.id) or {}
            storage.save_user(user.id, {
                "name": w["data"]["name"],
                "teacher": old.get("teacher"),
                "username": ("@" + user.username) if user.username else "",
                "joined": old.get("joined") or int(time.time()),
                "stats": old.get("stats") or {},
                "flashcards": old.get("flashcards") or [],
                "last_quiz": old.get("last_quiz"),
            })
            storage.clear_wizard(chat)
            await msg.reply_text(T.REG_DONE.format(name=w["data"]["name"]),
                                 reply_markup=_main_menu(storage, user))
            return True
        w["step"] = "teacher"
        storage.set_wizard(chat, w)
        await msg.reply_text(
            T.REG_TEACHER.format(name=w["data"]["name"],
                                 teacher=storage.get_teacher_name()),
            reply_markup=K.reg_teacher_kb())
        return True
    return False


async def cb_reg(query, context, payload: str):
    storage = _storage(context)
    chat = query.message.chat_id
    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "reg" or w.get("step") != "teacher":
        return await alert(query, T.WIZ_GONE, K.home_only())
    teacher = payload.endswith(":1")
    data = w.get("data") or {}
    user = query.from_user
    name = data.get("name") or user.first_name or "بەکارهێنەر"
    # پاراستنی ئامار و فڵاشکارتە کۆنەکان لە کاتی نوێکردنەوەی پرۆفایل
    old = storage.get_user(user.id) or {}
    storage.save_user(user.id, {
        "name": name,
        "teacher": teacher,
        "username": ("@" + user.username) if user.username else "",
        "joined": old.get("joined") or int(time.time()),
        "stats": old.get("stats") or {},
        "flashcards": old.get("flashcards") or [],
        "last_quiz": old.get("last_quiz"),
    })
    storage.clear_wizard(chat)
    # ئەگەر لە «پرسیار بکە» ەوە هاتووە، بەردەوام بە لەگەڵ پرسیارەکە
    if data.get("next") == "ask":
        return await _ask_begin(query, context, edit=True)
    await edit_message(query, T.REG_DONE.format(name=name),
                       _main_menu(storage, user))


# ---------------- پرسیار بکە ----------------

async def _ask_begin(query, context, edit: bool = False):
    storage = _storage(context)
    chat = query.message.chat_id
    tree = storage.db()["tree"]
    if not tree:
        storage.clear_wizard(chat)
        return await alert(query, T.ASK_EMPTY, K.home_only())
    storage.set_wizard(chat, {"flow": "ask", "step": "nav",
                              "data": {"path": [], "text": None, "photo": None}})
    kb = K.ask_level_kb([n for n in tree if n.get("type") == "folder"], 0)
    if edit:
        await edit_message(query, T.ASK_START, kb)
    else:
        try:
            await query.message.reply_text(T.ASK_START, reply_markup=kb)
        except Exception:
            pass


async def _ask_render_level(query, context, w: dict):
    storage = _storage(context)
    d = w.setdefault("data", {})
    path = d.get("path") or []
    tree = storage.db()["tree"]
    # ئەگەر بەشێکی ڕێڕەوەکە سڕدرابێتەوە، لە سەرەتاوە دەست پێبکەوە
    for fid in list(path):
        node = st.find_node(tree, fid)
        if not node or node.get("type") != "folder":
            d["path"] = []
            storage.set_wizard(query.message.chat_id, w)
            path = []
            break
    if path:
        node = st.find_node(tree, path[-1])
        text = T.ASK_LEVEL.format(title=node.get("title", "?"))
        children = [c for c in node.get("children", []) if c.get("type") == "folder"]
    else:
        text = T.ASK_START
        children = [n for n in tree if n.get("type") == "folder"]
    await edit_message(query, text, K.ask_level_kb(children, len(d.get("path") or [])))


def _ask_path_titles(storage, path) -> list:
    titles = []
    tree = storage.db()["tree"]
    for fid in path or []:
        node = st.find_node(tree, fid)
        if node:
            titles.append(node.get("title", "?"))
    return titles


async def _send_review(context, chat, w: dict, reply_to=None):
    storage = _storage(context)
    d = w.get("data") or {}
    text = T.ASK_REVIEW.format(
        path=" › ".join(_ask_path_titles(storage, d.get("path"))) or "—",
        text=st.trunc(d.get("text") or "—", 600),
        img=T.ASK_IMG_YES if d.get("photo") else T.ASK_IMG_NO)
    try:
        if reply_to is not None:
            await reply_to.reply_text(text, reply_markup=K.ask_review_kb())
        else:
            await context.bot.send_message(chat, text, reply_markup=K.ask_review_kb())
    except Exception:
        pass


async def _ask_send(query, context, w: dict):
    storage = _storage(context)
    chat = query.message.chat_id
    user = query.from_user
    d = w.get("data") or {}
    text = (d.get("text") or "").strip()
    if not text and not d.get("photo"):
        try:
            await query.message.reply_text(T.ASK_NEED_TEXT)
        except Exception:
            pass
        return
    profile = storage.get_user(user.id) or {}
    tid = storage.next_ticket_id()
    ticket = {
        "id": tid,
        "uid": user.id,
        "name": profile.get("name") or user.first_name or "بەکارهێنەر",
        "username": ("@" + user.username) if user.username else "",
        "teacher": bool(profile.get("teacher")),
        "path": _ask_path_titles(storage, d.get("path")),
        "text": text,
        "photo": d.get("photo"),
        "status": "open",
        "created": int(time.time()),
        "replies": [],
        "admin_msgs": {},
    }
    storage.create_ticket(ticket)
    storage.clear_wizard(chat)
    try:
        await query.message.reply_text(T.ASK_SENT)
    except Exception:
        pass
    import handlers_admin  # import ی ناوخۆیی — بۆ ڕێگرتن لە سووڕی import
    try:
        await handlers_admin.notify_new_ticket(context, ticket)
    except Exception:
        pass


async def cb_ask(query, context, data: str):
    storage = _storage(context)
    chat = query.message.chat_id
    uid = query.from_user.id

    if data == "ask":
        # دەستپێکردن — پێشتر تۆمارکراوە؟
        if not storage.get_user(uid):
            storage.set_wizard(chat, {"flow": "reg", "step": "name",
                                      "data": {"next": "ask"}})
            return await edit_message(query, T.REG_NAME, None)
        return await _ask_begin(query, context, edit=True)

    payload = data[4:]
    if payload == "stop":
        storage.clear_wizard(chat)
        return await alert(query, T.ASK_CANCELLED, K.home_only())

    w = storage.get_wizard(chat)
    if not w or w.get("flow") != "ask":
        return await alert(query, T.WIZ_GONE, K.home_only())
    d = w.setdefault("data", {})
    path = d.get("path") or []

    if payload == "back":
        if path:
            path.pop()
            d["path"] = path
            storage.set_wizard(chat, w)
        return await _ask_render_level(query, context, w)

    if payload == "pick":
        if not path:
            return await alert(query, T.ASK_NEED_PICK)
        w["step"] = "text"
        storage.set_wizard(chat, w)
        try:
            await query.message.reply_text(T.ASK_TEXT, reply_markup=K.ask_text_kb())
        except Exception:
            pass
        return

    if payload.startswith("go:"):
        fid = payload[3:]
        node = st.find_node(storage.db()["tree"], fid)
        if not node or node.get("type") != "folder":
            return await alert(query, T.GONE)
        path.append(fid)
        d["path"] = path
        storage.set_wizard(chat, w)
        return await _ask_render_level(query, context, w)

    if payload == "photo":
        w["step"] = "photo"
        storage.set_wizard(chat, w)
        try:
            await query.message.reply_text(T.ASK_NEED_PHOTO, reply_markup=K.ask_text_kb())
        except Exception:
            pass
        return

    if payload == "send":
        return await _ask_send(query, context, w)


async def route_ask(update: Update, context: ContextTypes.DEFAULT_TYPE, w: dict):
    storage = _storage(context)
    msg = update.message
    if not msg:
        return False
    chat = msg.chat_id
    step = w.get("step")
    d = w.setdefault("data", {})

    if step in ("text", "photo", "review"):
        changed = False
        if msg.text and msg.text.strip():
            d["text"] = msg.text.strip()[:3500]
            changed = True
        if msg.photo:
            d["photo"] = msg.photo[-1].file_id
            if not (d.get("text") or "").strip() and (msg.caption or "").strip():
                d["text"] = (msg.caption or "").strip()[:3500]
            changed = True
        if not changed:
            await msg.reply_text(
                T.ASK_NEED_PHOTO if step == "photo" else T.ASK_NEED_TEXT)
            return True
        if not (d.get("text") or "").strip():
            await msg.reply_text(T.ASK_NEED_TEXT)
            return True
        w["step"] = "review"
        storage.set_wizard(chat, w)
        await _send_review(context, chat, w, reply_to=msg)
        return True
    return False


# ---------------- تاقیکردنەوەی شەوانە (لای بەکارهێنەر) ----------------

async def cb_qn(query, context, data: str):
    storage = _storage(context)
    chat_id = query.message.chat_id
    uid = query.from_user.id
    ev = storage.get_event()
    if not ev or not ev.get("enabled"):
        return await alert(query, T.GONE, K.home_only())

    title = ev.get("title", "تاقیکردنەوەی شەوانە")
    start_s = evmod.clock_k(ev.get("start", "21:00"))
    end_s = evmod.clock_k(ev.get("end", "21:30"))
    state = evmod.status(ev)
    date = evmod.today_str()
    played = evmod.has_played(ev, uid, date)

    if data in ("qn", "qn:refresh"):
        if state == evmod.STATUS_WAIT:
            start_dt, _ = evmod.window(ev)
            text = T.QN_WAIT.format(title=title, start=start_s, end=end_s,
                                    left=evmod.remaining_text(start_dt))
            return await edit_message(query, text, K.event_kb("wait", False))
        if state == evmod.STATUS_OPEN:
            text = T.QN_START.format(title=title, start=start_s, end=end_s)
            return await edit_message(query, text, K.event_kb("open", played))
        # over
        return await edit_message(query, T.QN_OVER, K.event_kb("over", played))

    if data == "qn:play":
        if state != evmod.STATUS_OPEN:
            return await cb_qn(query, context, "qn")
        if played:
            return await _qn_show_results(query, context, ev, uid)
        # دەستپێکردنی تاقیکردنەوەی ئیڤێنت — لە بەشەکان یان لە بەنکۆی پرسیارە نوێکان
        src = ev.get("src") or {}
        title = ev.get("title", title)
        if (src.get("type") or "folder") == "bank":
            bank = ev.get("bank") or []
            if not bank:
                return await alert(query, T.NO_QUESTIONS, K.home_only())
            questions = [dict(q) for q in bank]
            extra = {q["id"]: q for q in questions}
            return await _launch_quiz(context, chat_id, query.from_user, title,
                                      questions, None, src="event",
                                      event_id=ev.get("id"), date=date, extra=extra)
        fid = src.get("folder_id")
        folder = st.find_node(storage.db()["tree"], fid) if fid else None
        if not folder:
            return await alert(query, T.NO_QUESTIONS, K.home_only())
        questions = [q for q in st.collect_questions(folder) if st.has_correct(q)]
        if not questions:
            return await alert(query, T.NO_QUESTIONS, K.home_only())
        count = int(src.get("count") or 0)
        if count > 0:
            random.shuffle(questions)
            questions = questions[:count]
        await _launch_quiz(context, chat_id, query.from_user, title, questions,
                           fid, src="event", event_id=ev.get("id"), date=date)
        return

    if data == "qn:results":
        return await _qn_show_results(query, context, ev, uid)


async def _qn_show_results(query, context, ev, uid):
    date = evmod.today_str()
    day = (ev.get("results") or {}).get(date) or {}
    rows = evmod.leaderboard(day)
    text = evmod.fmt_leaderboard(rows, ev.get("title", "تاقیکردنەوەی شەوانە"), me_uid=uid)
    try:
        await context.bot.send_message(query.message.chat_id, text,
                                       reply_markup=K.home_only(), parse_mode="HTML")
    except Exception:
        pass


# ---------------- ئامارەکەم ----------------

async def cb_mystats(query, context):
    storage = _storage(context)
    profile = storage.get_user(query.from_user.id) or {}
    stats = profile.get("stats") or {}
    if not stats.get("quizzes"):
        return await alert(query, T.MYSTATS_EMPTY, K.home_only())
    total = int(stats.get("total", 0))
    correct = int(stats.get("correct", 0))
    pct = int(round(correct * 100.0 / total)) if total else 0
    text = T.MYSTATS.format(name=profile.get("name") or "",
                            quizzes=st.knum(stats.get("quizzes", 0)),
                            total=st.knum(total), correct=st.knum(correct),
                            pct=st.knum(pct))
    await edit_message(query, text, K.home_only())


# ---------------- پرسیارەکانم / ڕاپۆرتەکانم / نامە هاتووەکان ----------------

def _my_status_text(x: dict) -> str:
    s = x.get("status")
    if s == "closed":
        return T.MY_STATUS_CLOSED
    if s == "replied":
        return T.MY_STATUS_REPLIED.format(n=st.knum(len(x.get("replies") or [])))
    return T.MY_STATUS_OPEN


def _my_replies_text(x: dict) -> str:
    replies = x.get("replies") or []
    if not replies:
        return T.MY_NO_REPLY
    out = T.MY_REPLIES_HEAD
    for i, r in enumerate(replies, 1):
        body = fmt.apply(r.get("text") or "")
        out += T.MY_REPLY_ITEM.format(i=st.knum(i), name=r.get("name") or "—",
                                      date=fmt_ts(r.get("at")),
                                      text=body or T.MY_REPLY_PHOTO)
        if r.get("photo"):
            out += T.MY_REPLY_PHOTO
    return out


async def cb_myq(query, context):
    storage = _storage(context)
    tickets = storage.user_tickets(query.from_user.id)
    if not tickets:
        return await alert(query, T.MYQ_EMPTY, K.home_only())
    await edit_message(query, T.MYQ_TITLE.format(n=st.knum(len(tickets))),
                       K.my_tickets_kb(tickets))


async def _send_my_ticket(context, query, t: dict):
    chat = query.message.chat_id
    text = T.MY_TICKET_VIEW.format(
        id=st.knum(t.get("id", 0)),
        path=" › ".join(t.get("path") or []) or "—",
        text=fmt.apply(t.get("text") or "") or "🖼",
        date=fmt_ts(t.get("created")),
        status=_my_status_text(t),
        replies=_my_replies_text(t))
    try:
        await fmt.send_html(context.bot, chat, text)
    except Exception:
        pass
    # وێنەکانی وەڵامەکان بە پەیامی جیا دەنێردرێن
    for r in (t.get("replies") or []):
        if r.get("photo"):
            try:
                await fmt.send_photo_html(context.bot, chat, r["photo"],
                                          fmt.apply(r.get("text") or "") or None)
            except Exception:
                pass


async def cb_myq_view(query, context, tid_raw: str):
    storage = _storage(context)
    tid = st.to_int(tid_raw)
    t = storage.get_ticket(tid) if tid is not None else None
    if not t or str(t.get("uid")) != str(query.from_user.id):
        return await alert(query, T.TK_GONE, K.home_only())
    return await _send_my_ticket(context, query, t)


async def cb_myrp(query, context):
    storage = _storage(context)
    reports = storage.user_reports(query.from_user.id)
    if not reports:
        return await alert(query, T.MYRP_EMPTY, K.home_only())
    await edit_message(query, T.MYRP_TITLE.format(n=st.knum(len(reports))),
                       K.my_reports_kb(reports))


async def _send_my_report(context, query, r: dict):
    chat = query.message.chat_id
    text = T.MY_REPORT_VIEW.format(
        id=st.knum(r.get("id", 0)),
        quiz=r.get("quiz") or "—",
        qtext=fmt.apply(r.get("qtext") or "") or "—",
        comment=fmt.apply(r.get("comment") or "") or "—",
        date=fmt_ts(r.get("created")),
        status=_my_status_text(r),
        replies=_my_replies_text(r))
    try:
        await fmt.send_html(context.bot, chat, text)
    except Exception:
        pass
    for rep in (r.get("replies") or []):
        if rep.get("photo"):
            try:
                await fmt.send_photo_html(context.bot, chat, rep["photo"],
                                          fmt.apply(rep.get("text") or "") or None)
            except Exception:
                pass


async def cb_myrp_view(query, context, rid_raw: str):
    storage = _storage(context)
    r = storage.get_report(rid_raw)
    if not r or str(r.get("uid")) != str(query.from_user.id):
        return await alert(query, T.RP_GONE, K.home_only())
    return await _send_my_report(context, query, r)


async def cb_myinbox(query, context):
    storage = _storage(context)
    msgs = storage.inbox_msgs(query.from_user.id)
    if not msgs:
        return await alert(query, T.MYINBOX_EMPTY, K.home_only())
    await edit_message(query, T.MYINBOX_TITLE.format(n=st.knum(len(msgs))),
                       K.my_inbox_kb(msgs))


async def cb_myinbox_view(query, context, idx_raw: str):
    storage = _storage(context)
    try:
        idx = int(idx_raw)
    except (TypeError, ValueError):
        return
    msgs = storage.inbox_msgs(query.from_user.id)
    if idx < 0 or idx >= len(msgs):
        return await alert(query, T.MYINBOX_EMPTY, K.home_only())
    m = msgs[idx]
    chat = query.message.chat_id
    text = T.MY_MSG_VIEW.format(date=fmt_ts(m.get("at")),
                                name=m.get("name") or "—",
                                text=fmt.apply(m.get("text") or "") or "—")
    try:
        if m.get("photo"):
            await fmt.send_photo_html(context.bot, chat, m["photo"], text)
        else:
            await fmt.send_html(context.bot, chat, text)
    except Exception:
        pass


# ---------------- ڕێگەکانی ویزاردی بەکارهێنەر ----------------

async def route_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, w: dict):
    """فلۆوەکانی بەکارهێنەر: reg / ask / quiznum / report / fcadd / mq"""
    flow = w.get("flow")
    if flow == "reg":
        handled = await route_reg(update, context, w)
    elif flow == "ask":
        handled = await route_ask(update, context, w)
    elif flow == "quiznum":
        handled = await _route_quiznum(update, context, w)
    elif flow == "report":
        handled = await _route_report(update, context, w)
    elif flow == "fcadd":
        handled = await _route_fcadd(update, context, w)
    else:
        handled = False
    # هیچ لقێک وەڵامی نەدەوە — بێدەنگ مەبە (چارەسەری بڕوان)
    if not handled:
        return await _wizard_fallback(update, context, w)


async def _wizard_fallback(update, context, w: dict):
    """کاتێک پەیامەکە لەگەڵ هیچ هەنگاوێکی ویزارد ناگونجێت — هەمیشە وەڵام بدەرەوە."""
    msg = update.message
    if not msg:
        return
    flow, step = w.get("flow"), w.get("step")
    if flow == "reg" and step == "name":
        return await msg.reply_text(T.REG_NAME_ERR)
    return await msg.reply_text(T.WIZ_USE_BUTTONS)


async def _route_quiznum(update, context, w: dict):
    storage = _storage(context)
    msg = update.message
    if not msg:
        return False
    if not msg.text:
        await msg.reply_text(
            T.QS_NUM_BAD.format(n=st.knum((w.get("data") or {}).get("n", 1))))
        return True
    d = w.get("data") or {}
    n = st.to_int(msg.text)
    avail = int(d.get("n") or 0)
    if n is None or n < 1 or (avail and n > avail):
        await msg.reply_text(T.QS_NUM_BAD.format(n=st.knum(avail or 1)))
        return True
    chat = msg.chat_id
    storage.clear_wizard(chat)

    if (d.get("fid") == "custom") or d.get("pool"):
        tree = storage.db()["tree"]
        pool = d.get("pool") or []
        questions = [st.find_node(tree, q) for q in pool]
        questions = [q for q in questions if q and q.get("type") == "question"]
        random.shuffle(questions)
        questions = questions[:n]
        await _launch_quiz(context, chat, msg.from_user,
                           d.get("title") or T.MQ_TITLE_NAME, questions, None)
        return True

    title, all_questions = _collect_for_fid(storage, d.get("fid") or "root")
    if not all_questions:
        await msg.reply_text(T.NO_QUESTIONS)
        return True
    random.shuffle(all_questions)
    questions = all_questions[:n]
    fid = d.get("fid") or "root"
    await _launch_quiz(context, chat, msg.from_user, title, questions,
                       None if fid in ("", "root") else fid)
    return True


async def _route_report(update, context, w: dict):
    storage = _storage(context)
    msg = update.message
    if not msg:
        return False
    if w.get("step") == "comment":
        if not msg.text:
            await msg.reply_text(T.WIZ_NEED_TEXT)
            return True
        await _send_report_msg(update, context, w, msg.text.strip()[:500])
        return True
    return False


async def _send_report_msg(update, context, w: dict, comment: str):
    storage = _storage(context)
    msg = update.message
    chat = msg.chat_id
    user = msg.from_user
    d = w.get("data") or {}
    profile = storage.get_user(user.id) or {}
    report = {
        "id": storage.next_report_id(),
        "uid": user.id,
        "name": profile.get("name") or user.first_name or "بەکارهێنەر",
        "username": ("@" + user.username) if user.username else "",
        "quiz": d.get("title") or "—",
        "qid": d.get("qid"),
        "qtext": d.get("qtext") or "—",
        "comment": (comment or "").strip()[:500],
        "status": "open",
        "created": int(time.time()),
        "replies": [],
        "admin_msgs": {},
    }
    storage.create_report(report)
    storage.clear_wizard(chat)
    try:
        await msg.reply_text(T.RP_SENT)
    except Exception:
        pass
    import handlers_admin
    try:
        await handlers_admin.notify_new_report(context, report)
    except Exception:
        pass


async def _route_fcadd(update, context, w: dict):
    storage = _storage(context)
    msg = update.message
    if not msg:
        return False
    chat = msg.chat_id
    step = w.get("step")
    d = w.setdefault("data", {})

    if step == "front":
        if not (msg.text and msg.text.strip()):
            await msg.reply_text(T.FC_NEED_TEXT)
            return True
        d["front"] = msg.text.strip()[:500]
        w["step"] = "back"
        storage.set_wizard(chat, w)
        await msg.reply_text(T.FC_BACK, reply_markup=K.fc_stop_kb())
        return True

    if step == "back":
        if not (msg.text and msg.text.strip()):
            await msg.reply_text(T.FC_NEED_TEXT)
            return True
        d["back"] = msg.text.strip()[:500]
        w["step"] = "photo"
        storage.set_wizard(chat, w)
        await msg.reply_text(T.FC_PHOTO, reply_markup=K.fc_photo_kb())
        return True

    if step == "photo":
        if msg.photo:
            d["photo"] = msg.photo[-1].file_id
        else:
            await msg.reply_text(
                "⚠️ تکایە وێنە بنێرە یان «⏭ بەبێ وێنە» بکە.")
            return True
        card = storage.add_flashcard(msg.from_user.id, d.get("front", ""),
                                     d.get("back", ""), d.get("photo"))
        storage.clear_wizard(chat)
        await msg.reply_text(T.FC_SAVED, reply_markup=K.fc_menu(1))
        return True
    return False
