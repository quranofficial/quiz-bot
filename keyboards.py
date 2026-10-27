# -*- coding: utf-8 -*-
"""هەموو کیبۆردەکانی Inline بۆ بەکارهێنەر و ئادمین."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import fmtutil as fmt
import storage as st
import texts as T


def btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cb)


def _flat(kb: InlineKeyboardMarkup):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


# ---------------- لای بەکارهێنەر ----------------

# کلیلەکانی دوگمەکانی مینیوی سەرەکی — ناوەکان لە ڕێکخستنەکاندا دەگۆڕدرێن
MENU_KEYS = ("sections", "custom", "event", "ask", "flash",
             "myq", "myrp", "myinbox", "mystats", "pages")


def menu_label(storage, key: str) -> str:
    """ناوی ئێستای دوگمەیەکی مینیو — ئەگەر ئادمین ناوی گۆڕیبێت، ئەوە دەگەڕێنێتەوە."""
    stored = storage.menu_label(key)
    if stored:
        return stored
    defaults = {
        "sections": T.BTN_SECTIONS, "custom": T.BTN_CUSTOM_QUIZ,
        "event": T.BTN_EVENT, "ask": T.BTN_ASK, "flash": T.BTN_FLASH,
        "myq": T.BTN_MYQ, "myrp": T.BTN_MYRP, "myinbox": T.BTN_MYINBOX,
        "mystats": T.BTN_MYSTATS, "pages": T.BTN_PAGES,
    }
    return defaults.get(key, key)


def main_menu(storage, user) -> InlineKeyboardMarkup:
    db = storage.db()
    ev = storage.get_event()
    has_event = bool(ev and ev.get("enabled"))
    has_tree = bool(db["tree"])
    has_pages = bool(db["pages"])
    L = lambda k: menu_label(storage, k)
    rows = []
    if has_tree:
        rows.append([btn(L("sections"), "nav:root")])
        rows.append([btn(L("custom"), "mq")])
    if has_event:
        rows.append([btn(L("event"), "qn")])
    if has_tree:
        rows.append([btn(L("ask"), "ask")])
    rows.append([btn(L("flash"), "fc")])
    rows.append([btn(L("myq"), "myq"), btn(L("myrp"), "myrp")])
    rows.append([btn(L("myinbox"), "myinbox"), btn(L("mystats"), "mystats")])
    if has_pages:
        rows.append([btn(L("pages"), "pgs")])
    # بەشە زیادکراوەکانی مینیو — هەر یەکێک پەڕەیەکی زانیاری دەکاتەوە
    page_ids = {p.get("id") for p in db["pages"]}
    for ex in storage.menu_extras():
        if ex.get("page_id") in page_ids:
            rows.append([btn(ex.get("label") or "📄", "cx:{}".format(ex["page_id"]))])
    if storage.is_admin(user.id):
        rows.append([btn(T.BTN_ADMIN, "adm")])
    return InlineKeyboardMarkup(rows)


def home_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.BTN_HOME, "home")]])


def user_folder(folder, parent_id, tree) -> InlineKeyboardMarkup:
    rows = []
    children = folder.get("children", []) if folder else tree
    if folder:
        nq = st.count_questions(folder)
        if nq:
            rows.append([btn(T.BTN_QUIZ.format(n=st.knum(nq)), "quiz:{}".format(folder["id"]))])
    elif tree:
        nq = sum(st.count_questions(n) for n in tree)
        if nq:
            rows.append([btn(T.BTN_QUIZ_ALL.format(n=st.knum(nq)), "quiz:root")])
    for c in children:
        if c.get("type") == "folder":
            rows.append([btn("📁 " + st.trunc(c.get("title", "?"), 44), "nav:{}".format(c["id"]))])
    back_cb = "nav:{}".format(parent_id) if parent_id else "home"
    rows.append([btn(T.BTN_BACK, back_cb)])
    return InlineKeyboardMarkup(rows)


# --- هەڵبژاردنی ژمارەی پرسیارەکان پێش دەستپێکردن ---

def quiz_start_options(fid: str, n: int) -> InlineKeyboardMarkup:
    """٣ بژاردە پێش دەستپێکردن: ١٠ پرسیار / هەموو / ژمارەیەک دیاری بکە."""
    rows = []
    if n >= 10:
        rows.append([btn(T.BTN_QS_TEN, "qs:{}:ten".format(fid))])
    rows.append([btn(T.BTN_QS_ALL.format(n=st.knum(n)), "qs:{}:all".format(fid))])
    rows.append([btn(T.BTN_QS_NUM, "qs:{}:num".format(fid))])
    if fid == "custom":
        back_cb = "mq"
    else:
        back_cb = "nav:{}".format(fid) if fid not in ("", "root") else "home"
    rows.append([btn(T.BTN_BACK, back_cb), btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


# --- تاقیکردنەوەی تایبەت (چەند بەشێک) ---

def custom_quiz_kb(children, depth: int, sel_ids, n_sel: int,
                   cur_fid=None) -> InlineKeyboardMarkup:
    """ڕاوکردنی چەند بەشێک بۆ تاقیکردنەوەی تایبەت — هەر بەشێک:
    کلیک لەسەر ناوەکە → چوونە ناوەوە؛ کلیک لەسەر ☑/☐ → هەڵبژاردن/لابردن."""
    rows = []
    for c in children:
        if c.get("type") != "folder":
            continue
        fid = c["id"]
        mark = T.MQ_SELECTED if fid in sel_ids else T.MQ_NOT_SELECTED
        rows.append([btn("📁 " + st.trunc(c.get("title", "?"), 38), "mq:go:{}".format(fid)),
                     btn(mark, "mq:toggle:{}".format(fid))])
    nav = []
    if depth > 0:
        nav.append(btn(T.BTN_ASK_BACK, "mq:back"))
    nav.append(btn(T.MQ_BTN_CLEAR, "mq:clear"))
    if nav:
        rows.append(nav)
    if n_sel >= 2:
        rows.append([btn(T.MQ_BTN_START.format(n=st.knum(n_sel)), "mq:start")])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


# --- فڵاشکارت ---

def fc_menu(n: int) -> InlineKeyboardMarkup:
    rows = [[btn(T.FC_BTN_ADD, "fc:add")]]
    if n:
        rows.append([btn(T.FC_BTN_STUDY, "fc:study"), btn(T.FC_BTN_DELETE, "fc:del")])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def fc_photo_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.WIZ_BTN_NOIMG, "fc:noimg")],
                                 [btn(T.WIZ_BTN_STOP, "fc:stopadd")]])


def fc_stop_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.WIZ_BTN_STOP, "fc:stopadd")]])


def fc_study_kb(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.FC_BTN_SHOW, "fc:show:{}".format(idx))],
                                 [btn(T.FC_BTN_STOP_CARD, "fc:stopstudy")]])


def fc_reveal_kb(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.FC_BTN_NEXT, "fc:next:{}".format(idx))],
                                 [btn(T.FC_BTN_STOP_CARD, "fc:stopstudy")]])


def fc_end_kb(n: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.FC_BTN_RESTART, "fc:study")],
                                 [btn(T.FC_BTN_DELETE, "fc:del")],
                                 [btn(T.BTN_HOME, "home")]])


def fc_del_list(cards) -> InlineKeyboardMarkup:
    rows = []
    for c in cards[:30]:
        rows.append([btn("❌ " + st.trunc(fmt.plain(c.get("front", "")), 36),
                         "fc:deli:{}".format(c["id"]))])
    rows.append([btn(T.FC_BTN_DEL_DONE, "fc")])
    return InlineKeyboardMarkup(rows)


# --- ڕاپۆرتکردنی کێشە (لای بەکارهێنەر) ---

def report_pick_kb(qids, tree) -> InlineKeyboardMarkup:
    """لیستی پرسیارەکانی دوایین تاقیکردنەوە بۆ ڕاپۆرتکردن."""
    rows = []
    for i, qid in enumerate(qids[:25], 1):
        node = st.find_node(tree, qid)
        label = st.trunc(fmt.plain((node or {}).get("text") or ""), 34) or T.RESULT_IMG
        rows.append([btn("{}. {}".format(st.knum(i), label), "rp:pick:{}".format(i - 1))])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def report_comment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.RP_BTN_SKIP, "rp:skip")]])


# --- تاقیکردنەوەی شەوانە (لای بەکارهێنەر) ---

def event_kb(state: str, played: bool) -> InlineKeyboardMarkup:
    rows = []
    if state == "open":
        if not played:
            rows.append([btn(T.QN_BTN_PLAY, "qn:play")])
        rows.append([btn(T.QN_BTN_RESULTS, "qn:results")])
    elif state == "wait":
        rows.append([btn(T.QN_BTN_REFRESH, "qn")])
    else:  # over
        rows.append([btn(T.QN_BTN_RESULTS, "qn:results")])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def quiz_options(qid: str, options) -> InlineKeyboardMarkup:
    rows = []
    for i, o in enumerate(options):
        rows.append([btn("{}) {}".format(st.LETTERS[i], st.trunc(o.get("text", ""), 50)),
                         "ans:{}:{}".format(qid, i))])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def answered_marker(correct: bool, letter: str, text: str) -> InlineKeyboardMarkup:
    mark = "✅" if correct else "❌"
    return InlineKeyboardMarkup([[btn("{} {}) {}".format(mark, letter, st.trunc(text, 45)), "noop")]])


def results_kb(folder_id: str, with_report: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if with_report:
        rows.append([btn(T.BTN_REPORT, "rp")])
    rows.append([btn(T.BTN_RETRY, "quiz:{}".format(folder_id))])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def pages_list(pages) -> InlineKeyboardMarkup:
    rows = [[btn("📄 " + st.trunc(p.get("title", "?"), 44), "pg:{}".format(p["id"]))] for p in pages]
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def page_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.BTN_BACK, "pgs")],
        [btn(T.BTN_HOME, "home")],
    ])


# ---------------- تۆمارکردن و پرسیار بکە ----------------

def reg_teacher_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.BTN_YES, "reg:t:1"), btn(T.BTN_NO, "reg:t:0")],
    ])


def ask_level_kb(children, depth: int) -> InlineKeyboardMarkup:
    """کیبۆردی ڕاوکردنی بەش/کەرت لە فلۆوی پرسیار بکە"""
    rows = []
    for c in children:
        if c.get("type") == "folder":
            rows.append([btn("📁 " + st.trunc(c.get("title", "?"), 44),
                             "ask:go:{}".format(c["id"]))])
    nav = []
    if depth > 0:
        nav.append(btn(T.BTN_ASK_PICK, "ask:pick"))
        nav.append(btn(T.BTN_ASK_BACK, "ask:back"))
    if nav:
        rows.append(nav)
    rows.append([btn(T.BTN_ASK_STOP, "ask:stop")])
    return InlineKeyboardMarkup(rows)


def ask_text_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.BTN_ASK_STOP, "ask:stop")]])


def ask_review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.BTN_ASK_SEND, "ask:send"), btn(T.BTN_ASK_PHOTO, "ask:photo")],
        [btn(T.BTN_ASK_STOP, "ask:stop")],
    ])


def ticket_kb(tid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.TK_BTN_REPLY, "tk:reply:{}".format(tid)),
         btn(T.TK_BTN_CLOSE, "tk:close:{}".format(tid))],
    ])


def tickets_list_kb(tickets) -> InlineKeyboardMarkup:
    rows = []
    for t in tickets[:25]:
        label = "#{}) {}".format(st.knum(t.get("id", 0)),
                                  st.trunc(t.get("text") or "🖼", 32))
        rows.append([btn(label, "tk:view:{}".format(t["id"]))])
    rows.append([btn(T.A_BTN_BACK_PANEL, "adm")])
    return InlineKeyboardMarkup(rows)


# ---------------- پانێڵی ئادمین ----------------

def admin_main(open_tickets: int = 0, open_reports: int = 0,
               users_n: int = 0, pending_n: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [btn(T.A_BTN_TREE, "am:root")],
        [btn(T.A_BTN_IMPFILE, "impfile")],
        [btn(T.A_BTN_TICKETS.format(n=st.knum(open_tickets)), "admtk"),
         btn(T.A_BTN_REPORTS.format(n=st.knum(open_reports)), "admrp")],
        [btn(T.A_BTN_EVENT, "qnev"),
         btn(T.A_BTN_BCAST, "bcast")],
        [btn(T.A_BTN_USERS.format(n=st.knum(users_n)), "usr"),
         btn(T.A_BTN_PAGES, "admpgs")],
        [btn(T.A_BTN_MENU, "menu"), btn(T.A_BTN_ADMINS, "admadm")],
        [btn(T.A_BTN_SETTINGS, "setview"), btn(T.A_BTN_STATS, "stats")],
    ]
    if pending_n:
        rows.append([btn(T.A_BTN_PENDING.format(n=st.knum(pending_n)), "pendq")])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def back_to_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.A_BTN_BACK_PANEL, "adm")], [btn(T.BTN_HOME, "home")]])


def back_to_folder_kb(fid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.WIZ_BTN_TO_FOLDER, "am:{}".format(fid or "root"))],
        [btn(T.BTN_HOME, "home")],
    ])


def back_to_question_kb(qid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.A_BTN_BACK_Q, "amq:{}".format(qid))],
        [btn(T.BTN_HOME, "home")],
    ])


def admin_folder(folder, parent_id, tree) -> InlineKeyboardMarkup:
    rows = []
    children = folder.get("children", []) if folder else tree
    for c in children:
        if c.get("type") == "folder":
            rows.append([btn("📁 " + st.trunc(c.get("title", "?"), 36), "am:{}".format(c["id"]))])
        else:
            label = c.get("text") or T.RESULT_IMG
            # ⚠️ = پرسیارێک کە هێشتا وەڵامی ڕاستی نییە
            mark = "❓" if st.has_correct(c) else "⚠️"
            rows.append([btn("{} ".format(mark) + st.trunc(label, 36), "amq:{}".format(c["id"]))])
    fid = folder["id"] if folder else "root"
    if folder:
        rows.append([btn(T.A_BTN_ADD_FOLDER, "amnew:{}".format(fid)),
                     btn(T.A_BTN_ADD_QUESTION, "amadd:{}".format(fid))])
        rows.append([btn(T.A_BTN_RENAME, "amren:{}".format(fid)),
                     btn(T.A_BTN_DELETE, "amdel:{}".format(fid))])
        back_cb = "am:{}".format(parent_id) if parent_id else "am:root"
        rows.append([btn(T.A_BTN_BACK, back_cb), btn(T.BTN_HOME, "home")])
    else:
        rows.append([btn(T.A_BTN_ADD_FOLDER, "amnew:root")])
        rows.append([btn(T.A_BTN_BACK_PANEL, "adm"), btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def admin_question(q, folder_id) -> InlineKeyboardMarkup:
    """شاشەی دەستکاری پرسیار: دەق، وێنە، هەموو هەڵبژاردەکان A-D و وەڵامی ڕاست."""
    qid = q["id"]
    opts = q.get("options") or []
    rows = [
        [btn(T.A_BTN_EDIT_TEXT, "amqtext:{}".format(qid)),
         btn(T.A_BTN_EDIT_IMAGE, "amqimg:{}".format(qid))],
    ]
    for i, o in enumerate(opts):
        mark = "✅" if o.get("correct") else "✏️"
        rows.append([btn("{} {}) {}".format(mark, st.LETTERS[i],
                                            st.trunc(o.get("text", ""), 32)),
                         "amqopt:{}:{}".format(qid, i))])
    corr = next((st.LETTERS[i] for i, o in enumerate(opts) if o.get("correct")), None)
    rows.append([btn(T.A_BTN_CORRECT.format(letter=corr or T.CORRECT_NONE),
                     "amqcorrp:{}".format(qid))])
    rows.append([btn(T.A_BTN_DELETE, "amqdel:{}".format(qid))])
    rows.append([btn(T.A_BTN_BACK, "am:{}".format(folder_id or "root"))])
    return InlineKeyboardMarkup(rows)


def correct_pick_kb(q) -> InlineKeyboardMarkup:
    """هەڵبژاردنی وەڵامی ڕاست لە دەستکاریکردنی پرسیاردا."""
    qid = q["id"]
    rows = []
    for i, o in enumerate(q.get("options") or []):
        mark = "✅" if o.get("correct") else "▫️"
        rows.append([btn("{} {}) {}".format(mark, st.LETTERS[i],
                                            st.trunc(o.get("text", ""), 40)),
                         "amqcorrset:{}:{}".format(qid, i))])
    rows.append([btn(T.A_BTN_BACK_Q, "amq:{}".format(qid))])
    return InlineKeyboardMarkup(rows)


def admin_pages(pages) -> InlineKeyboardMarkup:
    rows = [[btn("📄 " + st.trunc(p.get("title", "?"), 44), "ampg:{}".format(p["id"]))] for p in pages]
    rows.append([btn(T.A_BTN_NEW_PAGE, "ampnew")])
    rows.append([btn(T.A_BTN_BACK_PANEL, "adm")])
    return InlineKeyboardMarkup(rows)


def admin_page(page) -> InlineKeyboardMarkup:
    pid = page["id"]
    return InlineKeyboardMarkup([
        [btn(T.A_BTN_ADD_ITEM, "ampadd:{}".format(pid))],
        [btn(T.A_BTN_DEL_LAST, "ampdelli:{}".format(pid)),
         btn(T.A_BTN_DELETE, "ampdel:{}".format(pid))],
        [btn(T.A_BTN_BACK, "admpgs"), btn(T.BTN_HOME, "home")],
    ])


def admins_kb(admins, owner_id) -> InlineKeyboardMarkup:
    rows = []
    for uid in admins:
        if uid == owner_id:
            continue
        rows.append([btn("❌ {}".format(uid), "admdel:{}".format(uid)),
                     btn(T.A_BTN_ADMIN_BAN, "admban:{}".format(uid)),
                     btn(T.A_BTN_ADMIN_DEL, "admdelete:{}".format(uid))])
    rows.append([btn(T.A_BTN_ADD_ADMIN, "admadd")])
    rows.append([btn(T.A_BTN_BACK_PANEL, "adm")])
    return InlineKeyboardMarkup(rows)


def admin_del_confirm_kb(uid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.YES_DELETE, "admdeleteok:{}".format(uid)),
         btn(T.NO_KEEP, "admadm")],
    ])


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.SET_ALL_VALUE, "setall")],
        [btn(T.A_BTN_SET_NUM, "setnum")],
        [btn(T.A_BTN_BACK_PANEL, "adm")],
    ])


# --- ڕاپۆرتەکان (لای ئادمین) ---

def reports_list_kb(reports) -> InlineKeyboardMarkup:
    rows = []
    for r in reports[:25]:
        mark = {"open": "🟢", "replied": "🔵", "closed": "🔒"}.get(r.get("status"), "▫️")
        label = "{} #{} {})".format(mark, st.knum(r.get("id", 0)),
                                     st.trunc(fmt.plain(r.get("qtext") or ""), 24))
        rows.append([btn(label, "rp:view:{}".format(r["id"]))])
    rows.append([btn(T.RP_BTN_CLEAR_CLOSED, "rp:clear"),
                 btn(T.A_BTN_BACK_PANEL, "adm")])
    return InlineKeyboardMarkup(rows)


def report_kb(rid, status: str) -> InlineKeyboardMarkup:
    rows = [[btn(T.TK_BTN_REPLY, "rp:reply:{}".format(rid))]]
    act = []
    if status != "closed":
        act.append(btn(T.TK_BTN_CLOSE, "rp:close:{}".format(rid)))
    act.append(btn(T.RP_BTN_DEL, "rp:del:{}".format(rid)))
    rows.append(act)
    rows.append([btn(T.A_BTN_BACK, "admrp"), btn(T.A_BTN_BACK_PANEL, "adm")])
    return InlineKeyboardMarkup(rows)


def report_del_kb(rid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.YES_DELETE, "rp:delok:{}".format(rid)),
         btn(T.NO_KEEP, "rp:view:{}".format(rid))],
    ])


# --- بەکارهێنەران (لای ئادمین) ---

USERS_PER_PAGE = 25


def users_list_kb(users, page: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        label = "👤 {}".format(st.trunc(u.get("name") or str(u.get("uid")), 26))
        if u.get("username"):
            label += " ({})".format(st.trunc(u["username"], 16))
        if (u.get("ban") or {}).get("on"):
            label = "🚫 " + label
        rows.append([btn(label, "usr:view:{}".format(u.get("uid")))])
    pages_n = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    nav = []
    if page > 1:
        nav.append(btn("⬅️", "usr:page:{}".format(page - 1)))
    if page < pages_n:
        nav.append(btn("➡️", "usr:page:{}".format(page + 1)))
    if nav:
        rows.append(nav)
    rows.append([btn(T.A_USR_BTN_SEARCH, "usr:search")])
    rows.append([btn(T.A_BTN_BACK_PANEL, "adm")])
    return InlineKeyboardMarkup(rows)


def user_view_kb(uid, banned: bool = False) -> InlineKeyboardMarkup:
    ban_label = T.A_BTN_USR_UNBAN if banned else T.A_BTN_USR_BAN
    ban_data = ("usr:unban:{}".format(uid) if banned
                else "usr:ban:{}".format(uid))
    return InlineKeyboardMarkup([
        [btn(T.A_BTN_USR_MSG, "usrmsg:{}".format(uid))],
        [btn(ban_label, ban_data)],
        [btn(T.A_BTN_USR_DEL, "usr:del:{}".format(uid))],
        [btn(T.A_USR_BACK_LIST, "usr")],
        [btn(T.A_BTN_BACK_PANEL, "adm")],
    ])


def user_del_confirm_kb(uid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.YES_DELETE, "usr:delok:{}".format(uid)),
         btn(T.NO_KEEP, "usr:view:{}".format(uid))],
    ])


# --- تاقیکردنەوەی شەوانە (لای ئادمین) ---

def qn_none_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.A_QN_BTN_NEW, "qn:new")],
        [btn(T.A_BTN_BACK_PANEL, "adm")],
    ])


def qn_view_kb(enabled: bool) -> InlineKeyboardMarkup:
    toggle = T.A_QN_BTN_TOGGLE_OFF if enabled else T.A_QN_BTN_TOGGLE_ON
    return InlineKeyboardMarkup([
        [btn(toggle, "qn:toggle")],
        [btn(T.A_QN_BTN_EDIT_TIME, "qn:edittime"),
         btn(T.A_QN_BTN_EDIT_SRC, "qn:editsrc")],
        [btn(T.A_QN_BTN_RESULTS, "qnv:results"),
         btn(T.A_QN_BTN_DELETE, "qn:del")],
        [btn(T.A_BTN_BACK_PANEL, "adm")],
    ])


def qn_folder_kb(children, depth: int, fid=None) -> InlineKeyboardMarkup:
    """ڕاوکردنی بەش بۆ سەرچاوەی پرسیارەکانی تاقیکردنەوەی شەوانە."""
    return folder_picker_kb(children, depth, "qnf:", "qn:cancelwiz",
                            T.A_QN_BTN_PICK_THIS)


def folder_picker_kb(children, depth: int, prefix: str, cancel_cb: str,
                     pick_label: str = None) -> InlineKeyboardMarkup:
    """ڕاوکردنی گشتی بەش/کەرت — prefix دیاری دەکات چ فلۆوێک (نموونە: impf:)"""
    rows = []
    for c in children:
        if c.get("type") == "folder":
            rows.append([btn("📁 " + st.trunc(c.get("title", "?"), 44),
                             "{}go:{}".format(prefix, c["id"]))])
    nav = []
    if depth > 0:
        nav.append(btn(pick_label or T.A_QN_BTN_PICK_THIS, "{}ok".format(prefix)))
        nav.append(btn(T.BTN_ASK_BACK, "{}back".format(prefix)))
    if nav:
        rows.append(nav)
    rows.append([btn(T.WIZ_BTN_STOP, cancel_cb)])
    return InlineKeyboardMarkup(rows)


def qn_count_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.A_QN_BTN_ALL, "qn:countall")],
        [btn(T.A_QN_BTN_TEN, "qn:countn:10"), btn(T.A_QN_BTN_TWENTY, "qn:countn:20")],
        [btn(T.WIZ_BTN_STOP, "qn:cancelwiz")],
    ])


def qn_src_kb() -> InlineKeyboardMarkup:
    """سەرچاوەی پرسیارەکانی تاقیکردنەوەی شەوانە: لە بەشەکان یان نووسینی نوێ."""
    return InlineKeyboardMarkup([
        [btn(T.A_QN_BTN_SRC_FOLDER, "qn:srcfolder")],
        [btn(T.A_QN_BTN_SRC_BANK, "qn:srcbank")],
        [btn(T.A_BTN_BACK_PANEL, "qnev")],
    ])


def qn_bank_kb(n: int) -> InlineKeyboardMarkup:
    rows = [[btn(T.A_QN_BTN_BANK_ADD, "qn:bankadd")]]
    if n:
        rows.append([btn(T.A_QN_BTN_BANK_DEL, "qn:bankdel")])
    rows.append([btn(T.A_QN_BTN_BANK_DONE, "qn:bankdone")])
    return InlineKeyboardMarkup(rows)


def eb_correct_kb(options) -> InlineKeyboardMarkup:
    """هەڵبژاردنی وەڵامی ڕاست بۆ پرسیاری بەنکۆی شەوانە."""
    rows = []
    for i, o in enumerate(options):
        rows.append([btn("{}) {}".format(st.LETTERS[i], st.trunc(o.get("text", ""), 50)),
                         "ebcorr:{}".format(i))])
    rows.append([btn(T.WIZ_BTN_STOP, "wx:cancel")])
    return InlineKeyboardMarkup(rows)


def after_bank_saved_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.A_QN_BTN_BANK_ADD, "qn:bankadd")],
        [btn(T.A_QN_BTN_BANK_DONE, "qn:bankdone")],
    ])


def qn_confirm_del_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.YES_DELETE, "qn:delok"), btn(T.NO_KEEP, "qnev")],
    ])


# --- نامەی گشتی ---

def bcast_confirm_kb(n: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.BCAST_BTN_SEND.format(n=st.knum(n)), "bcast:go")],
        [btn(T.NO_KEEP, "bcast:no")],
    ])


def confirm_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.YES_DELETE, yes_cb)],
        [btn(T.NO_KEEP, no_cb)],
    ])


# ---------------- ویزارد ----------------

def wiz_image_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.WIZ_BTN_NOIMG, "wx:skipimg")],
        [btn(T.WIZ_BTN_STOP, "wx:cancel")],
    ])


def wiz_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[btn(T.WIZ_BTN_STOP, "wx:cancel")]])


def wiz_options_kb(n: int) -> InlineKeyboardMarkup:
    rows = []
    if n >= 4:
        rows.append([btn(T.WIZ_BTN_DONE.format(n=st.knum(n)), "wx:done")])
    rows.append([btn(T.WIZ_BTN_STOP, "wx:cancel")])
    return InlineKeyboardMarkup(rows)


def wiz_correct_kb(options) -> InlineKeyboardMarkup:
    rows = []
    for i, o in enumerate(options):
        rows.append([btn("{}) {}".format(st.LETTERS[i], st.trunc(o.get("text", ""), 50)),
                         "wxcorr:{}".format(i))])
    rows.append([btn(T.WIZ_BTN_STOP, "wx:cancel")])
    return InlineKeyboardMarkup(rows)


def wiz_editimg_kb(qid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.WIZ_BTN_REMOVE_IMG, "amqimgdel:{}".format(qid))],
        [btn(T.WIZ_BTN_STOP, "wx:cancel")],
    ])


def after_question_saved_kb(fid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.WIZ_BTN_NEXT_Q, "amadd:{}".format(fid))],
        [btn(T.WIZ_BTN_TO_FOLDER, "am:{}".format(fid))],
        [btn(T.BTN_HOME, "home")],
    ])


def after_folder_saved_kb(parent) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("📂 بەشەکە ببینە", "am:{}".format(parent or "root"))],
        [btn(T.BTN_HOME, "home")],
    ])


def after_page_saved_kb(pid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.WIZ_BTN_VIEW_PAGE, "ampg:{}".format(pid))],
        [btn(T.BTN_HOME, "home")],
    ])


def after_item_saved_kb(pid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.WIZ_BTN_ADD_MORE, "ampadd:{}".format(pid))],
        [btn(T.WIZ_BTN_VIEW_PAGE, "ampg:{}".format(pid))],
        [btn(T.BTN_HOME, "home")],
    ])


def after_import_kb(fid=None) -> InlineKeyboardMarkup:
    rows = [[btn(T.IMP2_BTN_AGAIN, "impfile")]]
    if fid:
        rows.append([btn(T.WIZ_BTN_TO_FOLDER, "am:{}".format(fid))])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


# --- هێنانی پرسیار بە PDF/وێنە ---

def imp_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.IMP2_BTN_CONFIRM, "impok")],
        [btn(T.WIZ_BTN_STOP, "wx:cancel")],
    ])


def pq_review_kb(options) -> InlineKeyboardMarkup:
    """دوگمەکانی دیاریکردنی وەڵامی ڕاست بۆ پرسیاری بێ وەڵام."""
    rows = []
    for i, o in enumerate(options):
        rows.append([btn("{}) {}".format(st.LETTERS[i], st.trunc(o.get("text", ""), 50)),
                         "pqset:{}".format(i))])
    rows.append([btn(T.PQ_BTN_SKIP, "pqskip"), btn(T.PQ_BTN_DONE, "pqdone")])
    return InlineKeyboardMarkup(rows)


# --- بەڕێوەبردنی مینیوی سەرەکی ---

def menu_admin_kb(storage) -> InlineKeyboardMarkup:
    rows = []
    for key in MENU_KEYS:
        label = menu_label(storage, key)
        rows.append([btn(T.MENU_LABEL_BTN.format(label=st.trunc(label, 28)),
                         "menu:{}".format(key))])
    for ex in storage.menu_extras():
        rows.append([btn("🗑 " + st.trunc(ex.get("label") or "؟", 28),
                         "menuexdel:{}".format(ex["id"]))])
    rows.append([btn(T.MENU_BTN_ADD_EXTRA, "menuex")])
    rows.append([btn(T.MENU_BTN_RESET, "menureset")])
    rows.append([btn(T.A_BTN_BACK_PANEL, "adm")])
    return InlineKeyboardMarkup(rows)


def menu_extra_pick_kb(pages) -> InlineKeyboardMarkup:
    rows = [[btn("📄 " + st.trunc(p.get("title", "?"), 40),
                 "menuexpick:{}".format(p["id"]))] for p in pages[:25]]
    rows.append([btn(T.WIZ_BTN_STOP, "wx:cancel")])
    return InlineKeyboardMarkup(rows)


# --- پرسیارەکانم / ڕاپۆرتەکانم / نامە هاتووەکان (لای بەکارهێنەر) ---

def _status_mark(status: str) -> str:
    return {"open": "🟢", "replied": "🔵", "closed": "🔒"}.get(status, "▫️")


def my_tickets_kb(tickets) -> InlineKeyboardMarkup:
    rows = []
    for t in tickets[:25]:
        label = T.MY_ITEM_BTN.format(mark=_status_mark(t.get("status")),
                                     id=st.knum(t.get("id", 0)),
                                     text=st.trunc(t.get("text") or "🖼", 30))
        rows.append([btn(label, "myqv:{}".format(t["id"]))])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def my_reports_kb(reports) -> InlineKeyboardMarkup:
    rows = []
    for r in reports[:25]:
        label = T.MY_ITEM_BTN.format(mark=_status_mark(r.get("status")),
                                     id=st.knum(r.get("id", 0)),
                                     text=st.trunc(fmt.plain(r.get("qtext") or ""), 30))
        rows.append([btn(label, "myrpv:{}".format(r["id"]))])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def my_inbox_kb(msgs) -> InlineKeyboardMarkup:
    rows = []
    for i, m in enumerate(msgs[-25:]):
        idx = len(msgs) - len(msgs[-25:]) + i   # ئیندێکسی ڕاستەقینە لە لیستەکەدا
        label = "📨 " + st.trunc(m.get("text") or "🖼", 34)
        rows.append([btn(label, "myinv:{}".format(idx))])
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)
