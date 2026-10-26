# -*- coding: utf-8 -*-
"""ڕێکخستنەکانی بۆت — لە گۆڕاوە ژینگەییەکان (Environment Variables) دەخوێنرێنەوە."""

import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# توکینی بۆت لە BotFather
BOT_TOKEN = (os.environ.get("BOT_TOKEN") or "").strip()

# ID ی خاوەن بۆت (ئادمینی سەرەکی) — ناگۆڕدرێت و ناسڕدرێتەوە
OWNER_ID = None
_raw_owner = (os.environ.get("OWNER_ID") or "").strip()
if _raw_owner:
    _trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    _digits = _raw_owner.translate(_trans)
    if _digits.isdigit():
        OWNER_ID = int(_digits)

# ماوەی کارکردنی هەر دانیشتێک بە چرکە — لە GitHub Actions هەر ٥ خولەک جارێک
# دەست پێدەکاتەوە، بۆیە ٢٤٠ چرکە (٤ خولەک) بەردەوام پۆڵینگ دەکات.
POLL_SECONDS = 240
try:
    POLL_SECONDS = max(30, int((os.environ.get("POLL_SECONDS") or "240").strip()))
except ValueError:
    pass

# چەند چرکە دوای دواین گۆڕانکاری، داتاکان بۆ GitHub پوش بکرێن (کۆکردنەوەی گۆڕانکارییەکان)
GIT_PUSH_DEBOUNCE = 8
try:
    GIT_PUSH_DEBOUNCE = max(2, int((os.environ.get("GIT_PUSH_DEBOUNCE") or "8").strip()))
except ValueError:
    pass

# ڕێڕەوی فایلی داتا
DATA_DIR = os.path.join(PROJECT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "db.json")


def validate():
    """لیستی گۆڕاوە ونبەکان دەگەڕێنێتەوە — ئەگەر بەتاڵ بوو، هەموو شتێک باشە."""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if OWNER_ID is None:
        missing.append("OWNER_ID")
    return missing
