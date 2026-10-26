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

def main_menu(is_admin: bool, has_pages: bool, has_tree: bool = True,
              has_event: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if has_tree:
        rows.append([btn(T.BTN_SECTIONS, "nav:root")])
        rows.append([btn(T.BTN_CUSTOM_QUIZ, "mq")])
    if has_event:
        rows.append([btn(T.BTN_EVENT, "qn")])
    if has_tree:
        rows.append([btn(T.BTN_ASK, "ask"), btn(T.BTN_FLASH, "fc")])
    else:
        rows.append([btn(T.BTN_FLASH, "fc")])
    rows.append([btn(T.BTN_MYSTATS, "mystats")])
    if has_pages:
        rows.append([btn(T.BTN_PAGES, "pgs")])
    if is_admin:
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
               users_n: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.A_BTN_TREE, "am:root")],
        [btn(T.A_BTN_IMPORT, "impjson")],
        [btn(T.A_BTN_TICKETS.format(n=st.knum(open_tickets)), "admtk"),
         btn(T.A_BTN_REPORTS.format(n=st.knum(open_reports)), "admrp")],
        [btn(T.A_BTN_EVENT, "qnev"),
         btn(T.A_BTN_BCAST, "bcast")],
        [btn(T.A_BTN_USERS.format(n=st.knum(users_n)), "usr"),
         btn(T.A_BTN_PAGES, "admpgs")],
        [btn(T.A_BTN_ADMINS, "admadm"), btn(T.A_BTN_SETTINGS, "setview")],
        [btn(T.A_BTN_STATS, "stats")],
        [btn(T.BTN_HOME, "home")],
    ])


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
            rows.append([btn("❓ " + st.trunc(label, 36), "amq:{}".format(c["id"]))])
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
    return InlineKeyboardMarkup([
        [btn(T.A_BTN_EDIT_TEXT, "amqtext:{}".format(q["id"])),
         btn(T.A_BTN_EDIT_IMAGE, "amqimg:{}".format(q["id"]))],
        [btn(T.A_BTN_DELETE, "amqdel:{}".format(q["id"]))],
        [btn(T.A_BTN_BACK, "am:{}".format(folder_id or "root"))],
    ])


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
    rows = [[btn("❌ {}".format(uid), "admdel:{}".format(uid))]
            for uid in admins if uid != owner_id]
    rows.append([btn(T.A_BTN_ADD_ADMIN, "admadd")])
    rows.append([btn(T.A_BTN_BACK_PANEL, "adm")])
    return InlineKeyboardMarkup(rows)


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


def user_view_kb(uid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.A_BTN_USR_MSG, "usrmsg:{}".format(uid))],
        [btn(T.A_USR_BACK_LIST, "usr")],
        [btn(T.A_BTN_BACK_PANEL, "adm")],
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
    rows = []
    for c in children:
        if c.get("type") == "folder":
            rows.append([btn("📁 " + st.trunc(c.get("title", "?"), 44),
                             "qnf:go:{}".format(c["id"]))])
    nav = []
    if depth > 0:
        nav.append(btn(T.A_QN_BTN_PICK_THIS, "qnf:ok"))
        nav.append(btn(T.BTN_ASK_BACK, "qnf:back"))
    if nav:
        rows.append(nav)
    rows.append([btn(T.WIZ_BTN_STOP, "qn:cancelwiz")])
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
    if n >= 2:
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


def after_import_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.IMP_BTN_AGAIN, "impjson")],
        [btn(T.A_BTN_TREE, "am:root")],
        [btn(T.BTN_HOME, "home")],
    ])
