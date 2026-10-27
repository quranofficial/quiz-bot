# -*- coding: utf-8 -*-
"""کۆرەی داتا: مێژووی بەش/پرسیار (دارچین بێ سنوور)، پەڕەکان، ئادمینەکان،
دانیشتەکانی تاقیکردنەوە و دۆخی ویزاردی ئادمین — هەموو لە فایلی data/db.json هەڵدەگیرێت."""

import json
import os
import secrets
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import config

DEFAULT_TEACHER = "ئارام عبدالرزاق"

DEFAULT_DB: Dict[str, Any] = {
    "settings": {"questions_per_quiz": 0,          # 0 = هەموو پرسیارەکانی بەشەکە
                 "teacher_name": DEFAULT_TEACHER,   # ناوی مامۆستا لە تۆمارکردندا
                 "ticket_seq": 0,                   # ژمێریاری پرسیارەکانی بەکارهێنەران
                 "report_seq": 0},                  # ژمێریاری ڕاپۆرتەکانی کێشە
    "admins": [],                            # لیستی ID ی ئادمینەکان (جگە لە خاوەن)
    "tree": [],                              # دارچینی بەش و پرسیارەکان
    "pages": [],                             # پەڕەکانی زانیاری (تێبینیەکان)
    "users": {},                             # پرۆفایلی بەکارهێنەرانی تۆمارکراو
    "tickets": {},                           # پرسیارەکانی بەکارهێنەران (پرسیار بکە)
    "reports": {},                           # ڕاپۆرتەکانی کێشەی پرسیارەکان
    "inbox": {},                             # نامە هاتووەکانی بەکارهێنەران (لە ئادمین)
    "events": {},                            # تاقیکردنەوەی شەوانە (تاقیکردنەوەی کاتدار)
    "sessions": {},                          # دانیشتە چالاکەکانی تاقیکردنەوە
    "wizard": {},                            # دۆخی ویزاردەکان (ئادمین + بەکارهێنەر)
    "meta": {"updated_at": 0},
}

LETTERS = "ABCDEFGH"

_EASTERN_TABLE = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_WESTERN_TABLE = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def new_id(prefix: str) -> str:
    return "{}{}".format(prefix, secrets.token_hex(4))


def knum(n) -> str:
    """ژمارە بە پیتە ڕۆژهەڵاتییەکان (١٢٣)."""
    return str(n).translate(_EASTERN_TABLE)


def to_int(s) -> Optional[int]:
    """گەڕاندنەوەی ژمارە لە تێکست (پێ یا ڕۆژهەڵاتی یان لاتینی)."""
    try:
        return int(str(s).strip().translate(_WESTERN_TABLE))
    except (TypeError, ValueError):
        return None


def trunc(s: str, n: int = 40) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: max(1, n - 1)] + "…"


def has_correct(q: Optional[dict]) -> bool:
    """ئایا ئەم پرسیارە وەڵامی ڕاستی هەیە؟"""
    return any((o or {}).get("correct") for o in (q or {}).get("options", []) if o)


# ---------------------------------------------------------------------------
# یارمەتیدەرەکانی دارچین (Tree helpers)
# ---------------------------------------------------------------------------

def find_node(nodes: List[dict], node_id: str) -> Optional[dict]:
    for n in nodes:
        if n.get("id") == node_id:
            return n
        if n.get("type") == "folder":
            found = find_node(n.get("children", []), node_id)
            if found:
                return found
    return None


def find_parent_folder_id(nodes: List[dict], node_id: str, current: str = "root") -> Optional[str]:
    for n in nodes:
        if n.get("id") == node_id:
            return current
        if n.get("type") == "folder":
            res = find_parent_folder_id(n.get("children", []), node_id, n.get("id", "root"))
            if res:
                return res
    return None


def collect_questions(node: dict) -> List[dict]:
    if node.get("type") == "question":
        return [node]
    out: List[dict] = []
    for c in node.get("children", []):
        out.extend(collect_questions(c))
    return out


def count_questions(node: dict) -> int:
    if node.get("type") == "question":
        return 1
    return sum(count_questions(c) for c in node.get("children", []))


def count_folders_in(nodes: List[dict]) -> int:
    n = 0
    for x in nodes:
        if x.get("type") == "folder":
            n += 1 + count_folders_in(x.get("children", []))
    return n


def tree_stats(nodes: List[dict]):
    folders = 0
    questions = 0

    def walk(ns):
        nonlocal folders, questions
        for n in ns:
            if n.get("type") == "folder":
                folders += 1
                walk(n.get("children", []))
            else:
                questions += 1

    walk(nodes)
    return folders, questions


# ---------------------------------------------------------------------------
# کۆرەی داتا
# ---------------------------------------------------------------------------

class Storage:
    def __init__(self, path: str):
        self.path = path
        self.on_change = None  # لەلایەن bot.py ڕێکدەخرێت → gitsync.notify
        self._lock = threading.RLock()
        self._db = self._load()

    # ---- خوێندنەوە و نووسین ----

    def _load(self) -> Dict[str, Any]:
        data = json.loads(json.dumps(DEFAULT_DB))
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    for k, v in loaded.items():
                        if k in DEFAULT_DB:
                            data[k] = v
            except Exception:
                try:
                    shutil.copy(self.path, self.path + ".corrupt")
                except Exception:
                    pass
        for key in ("admins", "tree", "pages"):
            if not isinstance(data.get(key), list):
                data[key] = []
        for key in ("sessions", "wizard", "users", "tickets", "reports", "events",
                    "inbox"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        if not isinstance(data.get("settings"), dict):
            data["settings"] = {}
        data["settings"].setdefault("questions_per_quiz", 0)
        data["settings"].setdefault("teacher_name", DEFAULT_TEACHER)
        data["settings"].setdefault("ticket_seq", 0)
        data["settings"].setdefault("report_seq", 0)
        if not isinstance(data["settings"].get("menu_labels"), dict):
            data["settings"]["menu_labels"] = {}
        if not isinstance(data["settings"].get("menu_extra"), list):
            data["settings"]["menu_extra"] = []
        return data

    def db(self) -> Dict[str, Any]:
        return self._db

    def save(self):
        with self._lock:
            self._db["meta"]["updated_at"] = int(time.time())
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._db, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    # ---- بەشەکان (دارچین) ----

    def add_folder(self, parent_id: Optional[str], title: str) -> dict:
        node = {"id": new_id("f"), "type": "folder", "title": (title or "").strip()[:60],
                "children": []}
        if not parent_id or parent_id == "root":
            self._db["tree"].append(node)
        else:
            parent = find_node(self._db["tree"], parent_id)
            if parent is None or parent.get("type") != "folder":
                self._db["tree"].append(node)
            else:
                parent.setdefault("children", []).append(node)
        self.save()
        return node

    def rename_folder(self, folder_id: str, title: str) -> bool:
        node = find_node(self._db["tree"], folder_id)
        if not node or node.get("type") != "folder":
            return False
        node["title"] = title
        self.save()
        return True

    def delete_folder(self, folder_id: str) -> bool:
        lst = self._containing_list(folder_id)
        if lst is None:
            return False
        lst[:] = [n for n in lst if n.get("id") != folder_id]
        self.save()
        return True

    def _containing_list(self, node_id: str) -> Optional[List[dict]]:
        def walk(nodes):
            for n in nodes:
                if n.get("id") == node_id:
                    return nodes
                if n.get("type") == "folder":
                    res = walk(n.get("children", []))
                    if res is not None:
                        return res
            return None

        return walk(self._db["tree"])

    def add_question(self, folder_id: str, text: str, image: Optional[str],
                     options: List[dict]) -> dict:
        node = {
            "id": new_id("q"),
            "type": "question",
            "text": text or "",
            "image": image,
            "options": options,
        }
        folder = find_node(self._db["tree"], folder_id) if folder_id else None
        if folder is not None and folder.get("type") == "folder":
            folder.setdefault("children", []).append(node)
        else:
            self._db["tree"].append(node)
        self.save()
        return node

    def delete_question(self, qid: str) -> bool:
        lst = self._containing_list(qid)
        if lst is None:
            return False
        lst[:] = [n for n in lst if n.get("id") != qid]
        self.save()
        return True

    def set_question_text(self, qid: str, text: str) -> bool:
        node = find_node(self._db["tree"], qid)
        if not node or node.get("type") != "question":
            return False
        node["text"] = text
        self.save()
        return True

    def set_question_image(self, qid: str, image: Optional[str]) -> bool:
        node = find_node(self._db["tree"], qid)
        if not node or node.get("type") != "question":
            return False
        node["image"] = image
        self.save()
        return True

    def set_question_option(self, qid: str, idx: int, text: str) -> bool:
        """دەقی هەڵبژاردەیەکی پرسیار دەگۆڕێت (idx لە ٠ ەوە)."""
        node = find_node(self._db["tree"], qid)
        if not node or node.get("type") != "question":
            return False
        options = node.get("options") or []
        if idx < 0 or idx >= len(options):
            return False
        options[idx]["text"] = (text or "").strip()[:200]
        self.save()
        return True

    def set_question_correct(self, qid: str, idx: int) -> bool:
        """وەڵامی ڕاستی پرسیار دیاری دەکات — هەموو ئەوانی تر ناڕاست دەبن."""
        node = find_node(self._db["tree"], qid)
        if not node or node.get("type") != "question":
            return False
        options = node.get("options") or []
        if idx < 0 or idx >= len(options):
            return False
        for i, o in enumerate(options):
            o["correct"] = (i == idx)
        self.save()
        return True

    # ---- پرسیاری بێ وەڵام ----

    def pending_question_ids(self, limit: int = 200) -> List[str]:
        """لیستی ID ی پرسیارەکان کە هیچ وەڵامێکی ڕاستیان نییە."""
        out: List[str] = []

        def walk(nodes):
            for n in nodes:
                if n.get("type") == "question":
                    if not has_correct(n):
                        out.append(n["id"])
                        if len(out) >= limit:
                            return True
                else:
                    if walk(n.get("children", [])):
                        return True
            return False

        walk(self._db["tree"])
        return out

    def count_pending_questions(self) -> int:
        return len(self.pending_question_ids(limit=100000))

    # ---- پەڕەکانی زانیاری (کەش) ----

    def add_page(self, title: str) -> dict:
        page = {"id": new_id("p"), "title": title, "items": []}
        self._db["pages"].append(page)
        self.save()
        return page

    def delete_page(self, pid: str) -> bool:
        before = len(self._db["pages"])
        self._db["pages"] = [p for p in self._db["pages"] if p.get("id") != pid]
        changed = len(self._db["pages"]) != before
        if changed:
            self.save()
        return changed

    def add_page_item(self, pid: str, itype: str, content: str,
                      caption: Optional[str] = None) -> Optional[dict]:
        page = next((p for p in self._db["pages"] if p.get("id") == pid), None)
        if page is None:
            return None
        item = {"id": new_id("i"), "type": itype, "content": content}
        if caption:
            item["caption"] = caption
        page.setdefault("items", []).append(item)
        self.save()
        return item

    def delete_last_item(self, pid: str) -> bool:
        page = next((p for p in self._db["pages"] if p.get("id") == pid), None)
        if page is None or not page.get("items"):
            return False
        page["items"].pop()
        self.save()
        return True

    # ---- ئادمینەکان ----

    def is_admin(self, uid) -> bool:
        uid = int(uid) if isinstance(uid, str) and uid.isdigit() else uid
        if uid is None:
            return False
        if config.OWNER_ID is not None and uid == config.OWNER_ID:
            return True
        return uid in self._db["admins"]

    def add_admin(self, uid: int) -> bool:
        if config.OWNER_ID is not None and uid == config.OWNER_ID:
            return False
        if uid in self._db["admins"]:
            return False
        self._db["admins"].append(uid)
        self.save()
        return True

    def remove_admin(self, uid: int) -> bool:
        if config.OWNER_ID is not None and uid == config.OWNER_ID:
            return False
        if uid not in self._db["admins"]:
            return False
        self._db["admins"].remove(uid)
        self.save()
        return True

    # ---- ڕێکخستنەکان ----

    def set_questions_per_quiz(self, n: int):
        self._db["settings"]["questions_per_quiz"] = int(n)
        self.save()

    def get_teacher_name(self) -> str:
        return self._db["settings"].get("teacher_name") or DEFAULT_TEACHER

    def set_teacher_name(self, name: str):
        self._db["settings"]["teacher_name"] = (name or "").strip()[:60] or DEFAULT_TEACHER
        self.save()

    # ---- بەکارهێنەرانی تۆمارکراو ----

    def get_user(self, uid) -> Optional[dict]:
        return self._db["users"].get(str(uid))

    def save_user(self, uid, profile: dict) -> dict:
        profile["uid"] = int(uid) if str(uid).isdigit() else uid
        self._db["users"][str(uid)] = profile
        self.save()
        return profile

    def count_users(self, exclude_admins: bool = False) -> int:
        """کۆی بەکارهێنەران — ئەگەر exclude_admins بێت، ئادمینەکان نایژمێردرێن."""
        if not exclude_admins:
            return len(self._db["users"])
        return sum(1 for u in self._db["users"].values()
                   if not self.is_admin(u.get("uid")))

    # ---- باندکردن و سڕینەوەی هەژمار (لای ئادمین) ----

    def is_banned(self, uid) -> bool:
        """ئایا ئەم بەکارهێنەرە باندکراوە؟"""
        u = self.get_user(uid)
        return bool(u and (u.get("ban") or {}).get("on"))

    def get_ban_info(self, uid) -> Optional[dict]:
        """زانیاری باندەکە (هۆکار، کات، لای کێ) — None ئەگەر باند نەکراوە."""
        u = self.get_user(uid)
        ban = (u or {}).get("ban")
        return ban if (ban and ban.get("on")) else None

    def ban_user(self, uid, reason: str, by="") -> bool:
        """باندکردنی بەکارهێنەر بە هۆکارەوە — هۆکارەکە بۆ خۆی پیشان دەدرێت."""
        u = self.get_user(uid)
        if not u:
            return False
        u["ban"] = {"on": True,
                    "reason": (reason or "").strip()[:300],
                    "by": str(by or ""),
                    "at": int(time.time())}
        self.save()
        return True

    def unban_user(self, uid) -> bool:
        """لادانەوەی باند — بەکارهێنەرەکە دەگەڕێتەوە بۆ کارکردنی ئاسایی."""
        u = self.get_user(uid)
        if not u:
            return False
        if "ban" in u:
            del u["ban"]
            self.save()
        return True

    def delete_user(self, uid) -> bool:
        """سڕینەوەی تەواوی هەژمار: پرۆفایل، ئامار، فڵاشکارت، دانیشتە و ویزاردی چالاک.
        بەکارهێنەرەکە وەک یەکەم جار دەگەڕێتەوە سەرەتا."""
        key = str(uid)
        if key not in self._db["users"]:
            return False
        del self._db["users"][key]
        self._db["sessions"].pop(key, None)
        self._db["wizard"].pop(key, None)
        self.save()
        return True

    def count_teacher_users(self) -> Tuple[int, int]:
        """(قوتابیەکان، ئەوانی تر) — لە وەڵامی پرسیاری تۆمارکردنەوە."""
        students = others = 0
        for u in self._db["users"].values():
            if u.get("teacher") is True:
                students += 1
            else:
                others += 1
        return students, others

    # ---- پرسیارەکانی بەکارهێنەران (پرسیار بکە) ----

    def next_ticket_id(self) -> int:
        self._db["settings"]["ticket_seq"] = int(self._db["settings"].get("ticket_seq", 0)) + 1
        return self._db["settings"]["ticket_seq"]

    def create_ticket(self, ticket: dict) -> dict:
        self._db["tickets"][str(ticket["id"])] = ticket
        self.save()
        return ticket

    def get_ticket(self, tid) -> Optional[dict]:
        return self._db["tickets"].get(str(tid))

    def save_ticket(self, ticket: dict):
        self._db["tickets"][str(ticket["id"])] = ticket
        self.save()

    def open_tickets(self) -> List[dict]:
        out = [t for t in self._db["tickets"].values() if t.get("status") != "closed"]
        out.sort(key=lambda t: t.get("id", 0), reverse=True)
        return out

    def count_open_tickets(self) -> int:
        return len(self.open_tickets())

    def user_tickets(self, uid) -> List[dict]:
        """هەموو پرسیارەکانی یەک بەکارهێنەر — نوێترین لە سەرەوە."""
        key = str(uid)
        out = [t for t in self._db["tickets"].values() if str(t.get("uid")) == key]
        out.sort(key=lambda t: t.get("id", 0), reverse=True)
        return out

    # ---- ڕاپۆرتەکانی کێشە (پرسیاری گومانلێکراو لە کۆتایی تاقیکردنەوە) ----

    def next_report_id(self) -> int:
        self._db["settings"]["report_seq"] = int(self._db["settings"].get("report_seq", 0)) + 1
        return self._db["settings"]["report_seq"]

    def create_report(self, report: dict) -> dict:
        self._db["reports"][str(report["id"])] = report
        self.save()
        return report

    def get_report(self, rid) -> Optional[dict]:
        return self._db["reports"].get(str(rid))

    def save_report(self, report: dict):
        self._db["reports"][str(report["id"])] = report
        self.save()

    def all_reports(self) -> List[dict]:
        out = list(self._db["reports"].values())
        out.sort(key=lambda r: r.get("id", 0), reverse=True)
        return out

    def open_reports(self) -> List[dict]:
        """ئەوانەی هێشتا داخراون یان وەڵام نەدراون — سەرەتا نوێترین."""
        out = [r for r in self._db["reports"].values()
               if r.get("status") in ("open", "replied")]
        out.sort(key=lambda r: r.get("id", 0), reverse=True)
        return out

    def count_open_reports(self) -> int:
        return len(self.open_reports())

    def delete_report(self, rid) -> bool:
        key = str(rid)
        if key in self._db["reports"]:
            del self._db["reports"][key]
            self.save()
            return True
        return False

    def clear_closed_reports(self) -> int:
        """سڕینەوەی هەموو ڕاپۆرتە داخراوەکان — ژمارەی سڕدراوەکان دەگەڕێنێتەوە."""
        closed = [k for k, r in self._db["reports"].items() if r.get("status") == "closed"]
        for k in closed:
            del self._db["reports"][k]
        if closed:
            self.save()
        return len(closed)

    def user_reports(self, uid) -> List[dict]:
        """هەموو ڕاپۆرتەکانی یەک بەکارهێنەر — نوێترین لە سەرەوە."""
        key = str(uid)
        out = [r for r in self._db["reports"].values() if str(r.get("uid")) == key]
        out.sort(key=lambda r: r.get("id", 0), reverse=True)
        return out

    # ---- نامە هاتووەکان (نامەی تایبەتی ئادمین) ----

    def inbox_msgs(self, uid) -> List[dict]:
        return list(self._db["inbox"].get(str(uid)) or [])

    def add_inbox_msg(self, uid, text: Optional[str], photo: Optional[str],
                      by_id, by_name: str) -> dict:
        """نامەیەک بۆ بەکارهێنەر زیاد دەکات (لە نامەی تایبەتی ئادمین)."""
        key = str(uid)
        msg = {"id": new_id("m"),
               "text": (text or "").strip()[:3500],
               "photo": photo,
               "by": str(by_id or ""),
               "name": (by_name or "—").strip()[:40],
               "at": int(time.time())}
        self._db["inbox"].setdefault(key, []).append(msg)
        # زۆرترین ٥٠ نامە بۆ هەر بەکارهێنەرێک — کۆنەکان دەسڕدرێنەوە
        if len(self._db["inbox"][key]) > 50:
            self._db["inbox"][key] = self._db["inbox"][key][-50:]
        self.save()
        return msg

    # ---- مینیوی سەرەکی: ناوەکان و بەشە زیادکراوەکان ----

    def menu_label(self, key: str) -> Optional[str]:
        v = self._db["settings"]["menu_labels"].get(key)
        return (v or "").strip() or None if isinstance(v, str) else None

    def set_menu_label(self, key: str, label: str):
        lbl = (label or "").strip()[:40]
        if lbl:
            self._db["settings"]["menu_labels"][key] = lbl
        else:
            self._db["settings"]["menu_labels"].pop(key, None)
        self.save()

    def reset_menu_labels(self):
        self._db["settings"]["menu_labels"] = {}
        self.save()

    def menu_extras(self) -> List[dict]:
        return list(self._db["settings"].get("menu_extra") or [])

    def add_menu_extra(self, label: str, page_id: str) -> dict:
        item = {"id": new_id("mx"), "label": (label or "").strip()[:40],
                "page_id": page_id}
        self._db["settings"].setdefault("menu_extra", []).append(item)
        self.save()
        return item

    def del_menu_extra(self, extra_id: str) -> bool:
        lst = self._db["settings"].get("menu_extra") or []
        before = len(lst)
        self._db["settings"]["menu_extra"] = [x for x in lst if x.get("id") != extra_id]
        changed = len(self._db["settings"]["menu_extra"]) != before
        if changed:
            self.save()
        return changed

    # ---- تاقیکردنەوەی شەوانە (تاقیکردنەوەی کاتدار) ----

    def get_event(self) -> Optional[dict]:
        return self._db["events"].get("current")

    def save_event(self, event: Optional[dict]):
        if event is None:
            self._db["events"].pop("current", None)
        else:
            self._db["events"]["current"] = event
        self.save()

    def add_event_bank_question(self, q: dict) -> int:
        """پرسیارێک بۆ بەنکۆی تاقیکردنەوەی شەوانە زیاد دەکات — ژمارەی کۆی دەگەڕێنێتەوە."""
        ev = self.get_event()
        if not ev:
            return 0
        ev.setdefault("bank", []).append(q)
        self.save()
        return len(ev["bank"])

    def pop_event_bank_question(self) -> int:
        """دوایین پرسیاری بەنکۆکە دەسڕێتەوە — ماوەی ژمارە دەگەڕێنێتەوە."""
        ev = self.get_event()
        if not ev or not ev.get("bank"):
            return 0
        ev["bank"].pop()
        self.save()
        return len(ev.get("bank") or [])

    # ---- فڵاشکارتی بەکارهێنەران ----

    def get_flashcards(self, uid) -> List[dict]:
        u = self.get_user(uid)
        return (u or {}).get("flashcards") or []

    def add_flashcard(self, uid, front: str, back: str, photo: Optional[str]) -> dict:
        u = self.get_user(uid)
        if u is None:
            u = self.save_user(uid, {"name": "بەکارهێنەر"})
        card = {"id": new_id("c"), "front": front, "back": back, "photo": photo}
        u.setdefault("flashcards", []).append(card)
        self.save()
        return card

    def delete_flashcard(self, uid, card_id: str) -> bool:
        u = self.get_user(uid)
        if not u or not u.get("flashcards"):
            return False
        before = len(u["flashcards"])
        u["flashcards"] = [c for c in u["flashcards"] if c.get("id") != card_id]
        changed = len(u["flashcards"]) != before
        if changed:
            self.save()
        return changed

    # ---- ئامارەکانی بەکارهێنەران ----

    def record_quiz_result(self, uid, folder_title: str, correct: int, total: int):
        """تۆمارکردنی ئەنجامی تاقیکردنەوە لە پرۆفایلی بەکارهێنەردا (بۆ ئاماری ئادمین)."""
        u = self.get_user(uid)
        if u is None:
            return
        stt = u.setdefault("stats", {})
        stt["quizzes"] = int(stt.get("quizzes", 0)) + 1
        stt["total"] = int(stt.get("total", 0)) + int(total)
        stt["correct"] = int(stt.get("correct", 0)) + int(correct)
        stt["last_quiz_at"] = int(time.time())
        by = stt.setdefault("by_folder", {})
        key = folder_title or "—"
        cell = by.setdefault(key, {"q": 0, "c": 0})
        cell["q"] += int(total)
        cell["c"] += int(correct)
        self.save()

    def find_users(self, query: str) -> List[dict]:
        """گەڕان بە ناو، یوزەرنام یان ID — گەڕانەوەی لیستی هاوتاکان."""
        q = (query or "").strip().lower()
        if not q:
            return []
        q2 = q.translate(_WESTERN_TABLE)
        out = []
        for u in self._db["users"].values():
            hay = " ".join([
                str(u.get("name") or ""), str(u.get("username") or ""),
                str(u.get("uid") or ""),
            ]).lower()
            if q in hay or q2 in hay:
                out.append(u)
        out.sort(key=lambda u: u.get("joined", 0), reverse=True)
        return out

    def users_sorted(self) -> List[dict]:
        """هەموو بەکارهێنەران بە دوایین چالاکی (یان بەیەکەوەبوون)."""
        out = list(self._db["users"].values())
        out.sort(key=lambda u: max(u.get("stats", {}).get("last_quiz_at", 0),
                                   u.get("joined", 0)), reverse=True)
        return out

    def set_last_quiz(self, uid, info: dict):
        """هەڵگرتنی زانیاری دوایین تاقیکردنەوە — بۆ دوگمەی ڕاپۆرتکردنی کێشە."""
        u = self.get_user(uid)
        if u is None:
            return
        u["last_quiz"] = info
        self.save()

    def all_admin_ids(self) -> List[int]:
        ids = []
        if config.OWNER_ID is not None:
            ids.append(config.OWNER_ID)
        for a in self._db["admins"]:
            if a not in ids:
                ids.append(a)
        return ids

    # ---- هێنانی JSON: دۆزینەوە یان دروستکردنی بەش بە هەمان ناو ----

    def ensure_folder(self, parent_id: Optional[str], title: str) -> Tuple[dict, bool]:
        """بەشێک بەم ناوە لەم باوکەدا دەدۆزێتەوە؛ ئەگەر نەبوو دروستی دەکات.
        گەڕانەوە: (نۆد، دروستکرا یان نا)"""
        title = (title or "").strip()
        parent = (find_node(self._db["tree"], parent_id)
                  if parent_id not in (None, "root") else None)
        siblings = parent.get("children", []) if parent else self._db["tree"]
        for n in siblings:
            if n.get("type") == "folder" and (n.get("title") or "").strip() == title:
                return n, False
        return self.add_folder(parent_id, title), True

    # ---- دانیشتەکانی تاقیکردنەوە ----

    def get_session(self, uid):
        return self._db["sessions"].get(str(uid))

    def set_session(self, uid, session: dict):
        self._db["sessions"][str(uid)] = session
        self.save()

    def del_session(self, uid):
        if str(uid) in self._db["sessions"]:
            del self._db["sessions"][str(uid)]
            self.save()

    def clean_old_sessions(self, max_age: int = 6 * 3600):
        now = time.time()
        removed = False
        for key in list(self._db["sessions"].keys()):
            s = self._db["sessions"][key]
            if now - float(s.get("ts", 0)) > max_age:
                del self._db["sessions"][key]
                removed = True
        if removed:
            self.save()

    # ---- ویزاردی ئادمین ----

    def get_wizard(self, chat_id):
        return self._db["wizard"].get(str(chat_id))

    def set_wizard(self, chat_id, w: dict):
        self._db["wizard"][str(chat_id)] = w
        self.save()

    def clear_wizard(self, chat_id):
        key = str(chat_id)
        if key in self._db["wizard"]:
            del self._db["wizard"][key]
            self.save()
