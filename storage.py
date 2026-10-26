# -*- coding: utf-8 -*-
"""کۆرەی داتا: مێژووی بەش/پرسیار (دارچین بێ سنوور)، پەڕەکان، ئادمینەکان،
دانیشتەکانی کویز و دۆخی ویزاردی ئادمین — هەموو لە فایلی data/db.json هەڵدەگیرێت."""

import json
import os
import secrets
import shutil
import threading
import time
from typing import Any, Dict, List, Optional

import config

DEFAULT_DB: Dict[str, Any] = {
    "settings": {"questions_per_quiz": 0},  # 0 = هەموو پرسیارەکانی بەشەکە
    "admins": [],                            # لیستی ID ی ئادمینەکان (جگە لە خاوەن)
    "tree": [],                              # دارچینی بەش و پرسیارەکان
    "pages": [],                             # پەڕەکانی زانیاری (تێبینیەکان)
    "sessions": {},                          # دانیشتە چالاکەکانی کویز
    "wizard": {},                            # دۆخی ویزاردی ئادمین
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
        for key in ("sessions", "wizard"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        if not isinstance(data.get("settings"), dict):
            data["settings"] = {"questions_per_quiz": 0}
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
        node = {"id": new_id("f"), "type": "folder", "title": title, "children": []}
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

    # ---- دانیشتەکانی کویز ----

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
