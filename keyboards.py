# -*- coding: utf-8 -*-
"""هەموو کیبۆردەکانی Inline بۆ بەکارهێنەر و ئادمین."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import storage as st
import texts as T


def btn(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=cb)


# ---------------- لای بەکارهێنەر ----------------

def main_menu(is_admin: bool, has_pages: bool) -> InlineKeyboardMarkup:
    rows = [[btn(T.BTN_SECTIONS, "nav:root")]]
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


def quiz_options(qid: str, options) -> InlineKeyboardMarkup:
    rows = []
    for i, o in enumerate(options):
        rows.append([btn("{}) {}".format(st.LETTERS[i], st.trunc(o.get("text", ""), 50)),
                         "ans:{}:{}".format(qid, i))])
    return InlineKeyboardMarkup(rows)


def answered_marker(correct: bool, letter: str, text: str) -> InlineKeyboardMarkup:
    mark = "✅" if correct else "❌"
    return InlineKeyboardMarkup([[btn("{} {}) {}".format(mark, letter, st.trunc(text, 45)), "noop")]])


def results_kb(folder_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.BTN_RETRY, "quiz:{}".format(folder_id))],
        [btn(T.BTN_HOME, "home")],
    ])


def pages_list(pages) -> InlineKeyboardMarkup:
    rows = [[btn("📄 " + st.trunc(p.get("title", "?"), 44), "pg:{}".format(p["id"]))] for p in pages]
    rows.append([btn(T.BTN_HOME, "home")])
    return InlineKeyboardMarkup(rows)


def page_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.BTN_BACK, "pgs")],
        [btn(T.BTN_HOME, "home")],
    ])


# ---------------- پانێڵی ئادمین ----------------

def admin_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn(T.A_BTN_TREE, "am:root")],
        [btn(T.A_BTN_PAGES, "admpgs")],
        [btn(T.A_BTN_ADMINS, "admadm")],
        [btn(T.A_BTN_SETTINGS, "setview")],
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
