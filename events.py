# -*- coding: utf-8 -*-
"""لۆجیکی تاقیکردنەوەی شەوانە (کویزی کاتدار) — خاڵیس و بێ تێلێگرام بۆ ئاسانی تاقیکردنەوە.

ئیڤێنتێک ئەم شێوەیە هەیە:
{
  "id": "eXXXX",
  "title": "تاقیکردنەوەی شەوانە",
  "start": "21:00",        # کاتی دەستپێک (کاتی ناوخۆیی)
  "end": "21:30",          # کاتی کۆتایی
  "src": {"folder_id": "f..", "title": "کەرتی X", "count": 10},   # count=0 → هەموو
  "enabled": True,          # پیشاندانی دوگمەکە لە مینیوی بەکارهێنەران
  "announced": {"2026-10-27": True},   # ئەنجامەکانی ئەو ڕۆژە بڵاوکراونەتەوە
  "results": {"2026-10-27": {"<uid>": {...}}}
}
"""

import datetime as _dt
from typing import List, Optional, Tuple

# کاتی ناوخۆیی عێراق/کوردستان = UTC+3 (ئادمین کاتە ناوخۆییەکان دەنووسێت)
TZ_HOURS = 3

_EASTERN_TABLE = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def knum(n) -> str:
    return str(n).translate(_EASTERN_TABLE)


def now_tz() -> _dt.datetime:
    """کاتی ئێستا بە کاتی ناوخۆیی (UTC+3)."""
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=TZ_HOURS)))


def parse_hhmm(s):
    """وەرگرتنی «21:00» یان «٩:٣٠» یان «9:5» → «21:00» شێوەی ستاندارد، یان None."""
    if s is None:
        return None
    t = str(s).strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
                                               "01234567890123456789"))
    t = t.replace("٫", ":").replace(".", ":").replace("،", ":").replace(" ", "")
    parts = t.split(":")
    if len(parts) == 1 and len(parts[0]) in (3, 4) and parts[0].isdigit():
        parts = [parts[0][:-2], parts[0][-2:]]  # «2100» → «21»، «00»
    if len(parts) != 2:
        return None
    if not (parts[0].isdigit() and parts[1].isdigit()):
        return None
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return "{:02d}:{:02d}".format(h, m)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def today_str(now: Optional[_dt.datetime] = None) -> str:
    n = now or now_tz()
    return n.strftime("%Y-%m-%d")


def window(ev: dict, now: Optional[_dt.datetime] = None) -> Tuple[_dt.datetime, _dt.datetime]:
    """پەنجەرەی کاتی ئەمڕۆی ئیڤێنتەکە — (دەستپێک، کۆتایی) بە کاتی ناوخۆیی."""
    n = now or now_tz()
    base = n.replace(hour=0, minute=0, second=0, microsecond=0)
    start = base + _dt.timedelta(minutes=_minutes(ev.get("start") or "21:00"))
    end = base + _dt.timedelta(minutes=_minutes(ev.get("end") or "21:30"))
    if end < start:  # ئیڤێنتی بەسەر نیوەشەو دەڕوات
        if n < start:
            end += _dt.timedelta(days=1)
        else:
            start -= _dt.timedelta(days=1)
    return start, end


# دۆخەکان: "wait" = هێشتا دەست پێنەکردووە، "open" = کراوەیە، "over" = کۆتایی هاتووە
STATUS_WAIT, STATUS_OPEN, STATUS_OVER = "wait", "open", "over"


def status(ev: dict, now: Optional[_dt.datetime] = None) -> str:
    n = now or now_tz()
    start, end = window(ev, n)
    if n < start:
        return STATUS_WAIT
    if n <= end:
        return STATUS_OPEN
    return STATUS_OVER


def remaining_text(target: _dt.datetime, now: Optional[_dt.datetime] = None) -> str:
    """«٢ کاتژمێر و ٥ خولەک» — ماوەی نێوان ئێستا و ئامانجەکە."""
    n = now or now_tz()
    delta = target - n
    total_min = int(delta.total_seconds() // 60)
    if total_min < 0:
        return "٠ خولەک"
    h, m = total_min // 60, total_min % 60
    if h and m:
        return "{} کاتژمێر و {} خولەک".format(knum(h), knum(m))
    if h:
        return "{} کاتژمێر".format(knum(h))
    return "{} خولەک".format(knum(max(1, m)))


def clock_k(hhmm: str) -> str:
    """21:00 → ٢١:٠٠"""
    return hhmm.translate(_EASTERN_TABLE)


def has_played(ev: dict, uid, date: Optional[str] = None) -> bool:
    d = date or today_str()
    return str(uid) in (ev.get("results") or {}).get(d, {})


def add_result(ev: dict, uid, entry: dict, date: Optional[str] = None):
    """تۆمارکردنی ئەنجامی بەکارهێنەرێک بۆ ئەمڕۆ (یەک جار بۆ هەر ئەکاونتێک)."""
    d = date or today_str()
    ev.setdefault("results", {}).setdefault(d, {})[str(uid)] = entry


def leaderboard(day_results: dict) -> List[Tuple[str, dict]]:
    """ڕیزکردنی ئەنجامەکان: پلەی بەرزتر سەرەوە، هەمان پلە → زوو تەواوکردن سەرەوە."""
    rows = [(uid, e) for uid, e in (day_results or {}).items()]
    rows.sort(key=lambda x: (-float(x[1].get("pct", 0)),
                             -int(x[1].get("score", 0)),
                             int(x[1].get("at", 0))))
    return rows


def rank_of(rows: List[Tuple[str, dict]], uid) -> Optional[int]:
    for i, (u, _) in enumerate(rows, 1):
        if u == str(uid):
            return i
    return None


def fmt_leaderboard(rows: List[Tuple[str, dict]], title: str, top: int = 10,
                    me_uid=None) -> str:
    """دەقی ڕیزبەندی — ناوی یەکەم لە سەرەوە (top rank)."""
    if not rows:
        return "ℹ️ هیچ بەژدارییەک تۆمار نەکراوە."
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>ئەنجامی {t}</b>\n".format(t=title)]
    for i, (uid, e) in enumerate(rows[:top], 1):
        mark = medals[i - 1] if i <= 3 else "▫️"
        name = e.get("name") or "بەکارهێنەر"
        me = " ← (تۆ)" if (me_uid is not None and str(me_uid) == uid) else ""
        lines.append("{} {} — {} / {} ({}٪){}".format(
            mark, _esc(name), knum(e.get("score", 0)), knum(e.get("total", 0)),
            knum(e.get("pct", 0)), me))
    if me_uid is not None and len(rows) > top:
        r = rank_of(rows, me_uid)
        if r and r > top:
            e = dict(rows[r - 1][1])
            lines.append("▫️ {} — {} / {} ({}٪) ← (تۆ)".format(
                knum(r), _esc(e.get("name") or "بەکارهێنەر"),
                knum(e.get("score", 0)), knum(e.get("total", 0)),
                knum(e.get("pct", 0))))
    return "\n".join(lines)


def _esc(s: str) -> str:
    return (str(s) or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cleanup(ev: dict, keep: int = 7):
    """پاراستنی تەنها دوا «keep» ڕۆژ لە ئەنجامەکان (بۆ بچووککردنەوەی db)."""
    res = ev.get("results") or {}
    ann = ev.get("announced") or {}
    dates = sorted(set(list(res.keys()) + list(ann.keys())))
    for d in dates[:-keep]:
        res.pop(d, None)
        ann.pop(d, None)
    ev["results"] = res
    ev["announced"] = ann
