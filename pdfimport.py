# -*- coding: utf-8 -*-
"""دەرهێنانی دەق لە PDF و وێنە + شیکردنەوەی پرسیارە هەڵبژاردەییەکان.

ئەم مۆدیوولە جێگەی هێنانی JSON دەگرێتەوە:
• PDF: دەق ڕاستەوخۆ دەرهێنراوە بە PyMuPDF؛ ئەگەر PDF ەکە وێنەیی (سکانکراو) بێت،
  OCR بە Tesseract بەکاردێت (ئەگەر دامەزراو بێت).
• وێنە: OCR بە Tesseract (زمانە بەردەستەکان: kur_ara / ara / fas / eng).

پارسەرەکە پرسیارەکان بەم شێوازانە دەناسێتەوە:
    1. دەقی پرسیار        ← "1 ." "2." "1)" "1 -" هەموو پەسەندن
    A) بژاردەی یەکەم      ← "A)" "A." "A -" "A ." "(A)" هەموو پەسەندن
    B - بژاردەی دووەم
    C . بژاردەی سێیەم
    D- بژاردەی چوارەم
    وەڵام: B        ← ئارەزوومەندانە (یان Answer: B، یان ✅ لەسەر بژاردەکە)

تایبەتمەندی گرنگ بۆ PDF ی فۆنتی کوردی کۆن:
• دەقەکە بە فۆرمە عەرەبییەکان (U+FB50–FDFF, U+FE70–FEFF) دەرهێنراوە — بە NFKC
  ئاسایی دەکرێتەوە و پیتی کوردییەکانی ناو (ة→ە، ى→ی، ك→ک…) چاک دەکرێن.
• ئەگەر PDF ەکە دێڕەکان یەک بخات (هەموو شت لە یەک دێڕدا)، پارسەرەکە پێش
  شیکردنەوە لە شوێنی ژمارەی پرسیار و تامی بژاردەکان جیایان دەکاتەوە —
  بۆیە "1 . کام…" و "A - …" تەنانەت لەناو دێڕێکی درێژیشدا دەناسرێنەوە.
• ئەگەر پەڕەیەک دەقەکەی شکاو بێت (ڕێژەی فۆرمە عەرەبییەکان زۆر بێت)،
  خۆکارانە OCR بۆ ئەو پەڕەیە بەکاردەهێنرێت (ئەگەر Tesseract دامەزرابێت).

گەڕانەوەی parse_questions: لیستی {"text", "options", "answered"} —
options لیستی {"text", "correct"} ـە و answered دەڵێت وەڵامی ڕاست دۆزرایەوە یان نا.
"""

import re
import unicodedata

from storage import _WESTERN_TABLE

# ---- کتێبخانەکان (ئارەزوومەندانە — ئەگەر نەبوون، هەڵەی ڕوون دەگەڕێنرێتەوە) ----

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from PIL import Image
except Exception:
    Image = None

MAX_FILE_BYTES = 15 * 1024 * 1024   # ١٥ مێگابایت
MAX_PAGES = 40
MAX_QUESTIONS = 150


class ImportError_(Exception):
    """هەڵەی گشتی هێنان — پەیامەکەی بۆ ئادمین پیشان دەدرێت."""


def _require(cond, msg):
    if not cond:
        raise ImportError_(msg)


# ---------------- دەرهێنانی دەق ----------------

def _ocr_langs():
    """باشترین زمانە بەردەستەکان بۆ OCR دەهەڵبژێرێت — None ئەگەر هیچ نەدۆزرایەوە."""
    try:
        avail = set(pytesseract.get_languages(config="") or [])
    except Exception:
        avail = set()
    pick = [l for l in ("kur_ara", "ara", "fas", "eng") if l in avail]
    return "+".join(pick) if pick else None


def pdf_text(path: str) -> str:
    """دەقی PDF دەرهێنان دەکات — بۆ پەڕە سکانکراوەکان OCR بەکاردەهێنێت."""
    _require(fitz is not None, "پشتگیری PDF بەردەست نییە (PyMuPDF نییە).")
    out = []
    try:
        doc = fitz.open(path)
    except Exception:
        raise ImportError_("فایلەکە PDF ی دروست نییە.")
    try:
        n = min(len(doc), MAX_PAGES)
        for i in range(n):
            page = doc[i]
            txt = page.get_text("text") or ""
            if txt.strip() and _garble_ratio(txt) < 0.35:
                out.append(txt)
                continue
            # پەڕە بێ دەق یان دەقەکەی شکاوە (فۆنتی کوردی کۆن) — OCR تاقی بکەرەوە
            ocr = _page_ocr(page)
            out.append(ocr if ocr.strip() else txt)
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return "\n".join(out)


def _ocr_text(img, langs=None):
    """OCR بە چەند پێکەهاتەیەکی جیاواز (psm) — ئەو دەقە دەگەڕێنێتەوە کە زۆرترین
    پرسیاری تێدا دەپارسێت (بۆ دەقی کورت وێنەیی پشێوازی بنەڕەتی هەندێک دێڕ لەدەست دەدات)."""
    best_txt, best_n = "", -1
    for psm in (4, 6, 3):
        try:
            cfg = "--psm {}".format(psm)
            txt = (pytesseract.image_to_string(img, lang=langs, config=cfg) or "") if langs \
                else (pytesseract.image_to_string(img, config=cfg) or "")
        except Exception:
            continue
        n = len(parse_questions(txt))
        if n > best_n:
            best_txt, best_n = txt, n
        if best_n >= 3:
            break   # باشە — زۆر پرسیار دۆزرانەوە
    return best_txt


def _page_ocr(page) -> str:
    """OCR بۆ یەک پەڕەی PDF — ئەگەر Tesseract نییە، بەتاڵ دەگەڕێنێتەوە."""
    if pytesseract is None or Image is None:
        return ""
    try:
        langs = _ocr_langs()
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return _ocr_text(img, langs)
    except Exception:
        return ""


def image_text(path: str) -> str:
    """دەقی وێنە بە OCR دەرهێنان دەکات — باشترین ئەنجامی چەند پشێوازێک."""
    _require(pytesseract is not None and Image is not None,
             "پشتگیری OCR بەردەست نییە — تکایە فایلی PDF (تێکستی) بنێرە.")
    try:
        img = Image.open(path)
    except Exception:
        raise ImportError_("وێنەکە نەکرایەوە — فۆرماتەکە پشتگیری نەکراوە.")
    # وێنەی ڕەنگاوڕەنگ بۆ ڕەش-سپی بگۆڕە — خوێندنەوە باشترە
    try:
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
    except Exception:
        pass
    try:
        langs = _ocr_langs()
        return _ocr_text(img, langs)
    except ImportError_:
        raise
    except Exception as e:
        raise ImportError_("هەڵەیەک لە خوێندنەوەی وێنەکە ڕوویدا: {}".format(e))


# ---------------- شیکردنەوەی پرسیارەکان ----------------

# ---- ئاساییکردنەوەی دەق (فۆرمە عەرەبییەکان، پیتی کوردی، ژمارەکان) ----

# پیتی کوردی کە فۆنتە کۆنەکان بە پیتی عەرەبی نزیک دەینێسن — دوای NFKC چاک دەکرێنەوە
_KURDI_FIX = {
    "ة": "ە",   # تی مەربوتا → ەی کوردی
    "ى": "ی", "ي": "ی",
    "ك": "ک",
    "ھ": "ه", "ہ": "ه", "ۀ": "ه",
}

# دیاکریتیک و پیتە نادیارەکان — لادەبرێن (فەتحە، کەسرە، تەطوێل، نیشانەی ئاڕاستە…)
_HARAKAT_RE = re.compile(u"[ \\t\\u00A0]?[\\u064B-\\u065F\\u0670\\u0640\\u06D6-\\u06ED\\u200B\\u200E\\u200F\\uFEFF\\u00AD]")
# فۆرمە دیاکریتیکە عەرەبییەکان (U+FE70–FE7F) — NFKC دەیانکاتە «بۆشایی + دیاکریتیک»
# بۆیە پێش NFKC بە تەواوی لادەبرێن
_PF_HARAKAT_RE = re.compile(u"[\\uFE70-\\uFE7F]")


def _normalize(raw: str) -> str:
    """ئاساییکردنەوەی دەقی دەرهێنراو بۆ شیکردنەوەی دروست:
    • ژمارە ڕۆژھەڵاتییەکان (٠-٩) → ڕۆژئاوایی (0-9)
    • فۆرمە عەرەبییەکان (U+FB50–FDFF, U+FE70–FEFF) → پیتی سەرەکی بە NFKC
    • پیتی کوردی کە بە عەرەبی نوێشراونەتەوە → پیتی کوردی ڕاست
    • لابردنی دیاکریتیک و پیتە نادیارەکان
    """
    t = (raw or "").translate(_WESTERN_TABLE)
    t = _PF_HARAKAT_RE.sub("", t)
    try:
        t = unicodedata.normalize("NFKC", t)
    except Exception:
        pass
    for a, b in _KURDI_FIX.items():
        t = t.replace(a, b)
    t = _HARAKAT_RE.sub("", t)
    # بۆشایی دووانە بپەستڕێنەوە
    return re.sub(u"[ \\t\\u00A0]{2,}", " ", t)


def _garble_ratio(txt: str) -> float:
    """ڕێژەی فۆرمە عەرەبییەکان و پیتە تایبەتەکان لە دەقی عەرەبی-نووسدا.
    ڕێژەی بەرز = دەقەکە بە فۆنتی کۆنی شکاو دەرهێنراوە (پێویستی بە OCR هەیە)."""
    arabic = weird = 0
    for ch in txt or "":
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF:
            arabic += 1
        elif (0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF
              or 0xE000 <= o <= 0xF8FF):
            weird += 1
    if arabic + weird < 40:
        return 0.0
    return weird / float(arabic + weird)


# ---- دابەشکردنەوەی دێڕە یەکخراوەکان ----
# زۆر PDF (و OCR) دێڕەکان یەک دەخات — پێش شیکردنەوە لە شوێنی ژمارەی پرسیار
# و تامی بژاردەکان جیایان دەکەینەوە بە جێگۆڕکێی بۆشایی → دێڕی نوێ.

# پێش ژمارەی پرسیار: "… ﺣ 2. کام" → "… ﺣ\n2. کام"   (بەڵام "تاقیکردنەوە 12 ت" نشکێنرێت)
_Q_SPLIT_RE = re.compile(
    u"(?<![0-9A-Za-z])[ \\t\\u00A0]+"
    u"(?=(?:پرسیار(?:ی)?\\s*)?\\d{1,3}\\s*[.)\\-،:]\\s)")

# پێش تامی بژاردە کە بە بۆشایی دەستپێدەکات: " A - " / " A . " / " (A) "
# (بەڵام "DNA -" و "(A + B)" نشکێنرێن)
_O_SPLIT_RE1 = re.compile(
    u"(?<![A-Za-z0-9])[ \\t\\u00A0]+"
    u"(?=\\(?[A-DＡ-Ｄأبجد]\\s*[)\\.\\-–:](?:\\s|\\Z))")

# تامی بژاردە کە ڕاستەوخۆ دوای پیتی عەرەبی/کوردی دێت: "…ﺳﯿﻨﮕB - …"
_O_SPLIT_RE2 = re.compile(
    u"(?<=[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF\u200C\u200F])"
    u"(?=[A-DＡ-Ｄأبجد]\\s*[)\\.\\-–:](?:\\s|\\Z))")

# تامی پێچەوانە لەناو دێڕدا: "…ﮐﺮﺩ . A ﺏﯾﺴﯩﺖ" → "…ﮐﺮﺩ\n. A ﺏﯾﺴﯩﺖ"
# (بۆشایی + تام + پیتی بژاردە + بۆشایی + دەق)
_O_SPLIT_RE3 = re.compile(
    u"\\s+(?=[.\\-–:)]\\s*[A-DＡ-Ｄأبجد]\\s+\\S)")


def _split_segments(text: str) -> str:
    text = _Q_SPLIT_RE.sub("\n", text)
    text = _O_SPLIT_RE1.sub("\n", text)
    text = _O_SPLIT_RE2.sub("\n", text)
    # RE3 دەستی — دابەشی مەکە ئەگەر پێش تامەکە تەنها ژمارەی پرسیار بێت
    # ("3 . A …" پرسیارە نەک بژاردە)
    out = []
    for ln in text.split("\n"):
        parts = []
        pos = 0
        for m in _O_SPLIT_RE3.finditer(ln):
            pre = ln[:m.start()]
            if m.start() <= 4 and re.fullmatch(r"[\d.)\]\s(]*", pre):
                continue
            parts.append(ln[pos:m.start()])
            parts.append("\n")
            pos = m.start()
        parts.append(ln[pos:])
        out.append("".join(parts))
    return "\n".join(out)


# پیتەکانی بژاردە: A-D لاتینی + أ ب ج د عەرەبی
_LETTER_MAP = {
    "A": "A", "B": "B", "C": "C", "D": "D",
    "a": "A", "b": "B", "c": "C", "d": "D",
    "أ": "A", "ب": "B", "ج": "C", "د": "D",
    "Ａ": "A", "Ｂ": "B", "Ｃ": "C", "Ｄ": "D",
}

# دێڕی بژاردە: "A) ..." یان "A. ..." یان "A - ..." یان "A . ..." یان "(A) ..." یان "أ) ..."
_OPT_RE = re.compile(u"^\\(?\\s*([A-DＡ-Ｄأبجد])\\s*[)\\.\\-–:]\\s*(.+)$")
# تامی پێچەوانە لە سەرەتای دێڕ: ". A …" یان "- B …" (فۆنتە کۆنەکان)
_OPT_RE2 = re.compile(u"^[.\\)\\-–:]\\s*([A-DＡ-Ｄأبجد])\\s+(.+)$")

# ژمارەی پرسیار: "1 . ..." یان "2. ..." یان "1) ..." یان "1 - ..." یان "پرسیاری ١: ..."
_QNUM_RE = re.compile(
    u"^\\s*(?:پرسیار(?:ی)?\\s*)?(\\d{1,3})\\s*[.\\)\\-–:،]\\s*(.*)$")

# وەڵامی ڕاست: "وەڵام: B" / "وەڵامی ڕاست: B" / "Answer: B" / "Correct - C" / "جاوب: D"
_ANS_RE = re.compile(
    u"(?:وەڵامی?\\s*ڕاست|وەڵامی?\\s*دروست|وەڵام|ئەنجام|جاوب"
    u"|answer|correct(?:\\s*answer)?|key)"
    u"\\s*[:\\-–=]?\\s*\\(?\\s*([A-DＡ-Ｄأبجد1-4])\\s*\\)?", re.I)

# دێڕی جیاکەرەوە (-----) کە ناوەڕۆکی نییە
_SEP_RE = re.compile(u"^[-–—=_*•·.\\s]+$")

_MARK_CHARS = "✅☑✔✓"
_TRUE_WORDS = ("(ڕاست)", "(دروست)", "(true)")


def _norm_letter(ch: str):
    return _LETTER_MAP.get(ch or "")


def _ans_to_idx(v: str, n_opts: int):
    """گەڕاندنەوەی ئیندێکسی وەڵام (٠-بنەڕەت) لە پیت یان ژمارە — None ئەگەر نەگونجاوە."""
    if not v:
        return None
    v = v.strip()
    if v.isdigit():
        i = int(v) - 1
        return i if 0 <= i < max(n_opts, 4) else None
    L = _norm_letter(v)
    if L:
        i = ord(L) - ord("A")
        return i if 0 <= i < max(n_opts, 4) else None
    return None


def _line_is_marked(ln: str) -> bool:
    """ئایا ئەم دێڕە نیشانەی وەڵامی ڕاستی تێدایە (✅ یان (ڕاست))؟"""
    if any(ch in ln for ch in _MARK_CHARS):
        return True
    low = ln.lower().strip()
    return any(w in low for w in _TRUE_WORDS)


def _strip_marks(s: str) -> str:
    for ch in _MARK_CHARS:
        s = s.replace(ch, " ")
    for w in ("(ڕاست)", "(دروست)", "(true)", "(True)"):
        s = s.replace(w, " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_questions(raw: str):
    """شیکردنەوەی دەقی پرسیارەکان — لیستی {"text", "options", "answered"} دەگەڕێنێتەوە.

    هەنگاوەکان:
    ١. ئاساییکردنەوەی دەق (NFKC، پیتی کوردی، ژمارەکان)
    ٢. دابەشکردنەوەی دێڕە یەکخراوەکان لە شوێنی ژمارەی پرسیار و تامی بژاردەکان
    ٣. پێکهێنانی پرسیارەکان بە مەکینەی دۆخی سادە (دێڕ-بە-دێڕ)
    """
    text = _normalize(raw)
    text = _split_segments(text)
    lines = [l.strip() for l in text.splitlines()]

    questions = []
    cur = None

    def flush():
        nonlocal cur
        if cur and len([o for o in cur["options"] if o and o.strip()]) >= 2:
            questions.append(cur)
        cur = None

    for ln in lines:
        if not ln:
            continue
        # دێڕی جیاکەرەوە (-------------) پشتگوێ بخرێت
        if _SEP_RE.match(ln):
            continue

        om = _OPT_RE.match(ln) or _OPT_RE2.match(ln)
        qm = _QNUM_RE.match(ln)

        # ---- دێڕی بژاردە ----
        if om and cur is not None:
            L = _norm_letter(om.group(1))
            body = om.group(2).strip()
            if L:
                idx = ord(L) - ord("A")
                while len(cur["options"]) <= idx:
                    cur["options"].append("")
                if idx < 4:
                    cur["options"][idx] = _strip_marks(body)
                if _line_is_marked(ln) and idx < 4:
                    cur["answer"] = idx
                continue

        # ---- دێڕی وەڵامی ڕاست ----
        am = _ANS_RE.search(ln)
        if am and cur is not None:
            idx = _ans_to_idx(am.group(1), len(cur["options"]))
            if idx is not None:
                cur["answer"] = idx
            continue

        # ---- دێڕی ژمارەی پرسیار — هەمیشە پرسیاری نوێ دەستپێدەکات ----
        if qm:
            flush()
            cur = {"text": (qm.group(2) or "").strip(), "options": [], "answer": None}
            continue

        # ---- دێڕی ئاسایی ----
        if cur is None:
            cur = {"text": ln, "options": [], "answer": None}
        elif len([o for o in cur["options"] if o and o.strip()]) >= 2:
            # دوای بژاردەکان دێڕی نوێ بێ ژمارە — پرسیاری نوێ دادەنرێت
            flush()
            cur = {"text": ln, "options": [], "answer": None}
        else:
            cur["text"] = (cur["text"] + " " + ln).strip()

    flush()

    # ---- پاککردنەوە و سنووردان ----
    out = []
    for q in questions[:MAX_QUESTIONS]:
        t = (q.get("text") or "").strip()
        opts = [o.strip() for o in (q.get("options") or [])[:4] if o and o.strip()]
        if not t or len(opts) < 2:
            continue
        options = [{"text": o[:300], "correct": False} for o in opts]
        ans = q.get("answer")
        answered = False
        if ans is not None and 0 <= ans < len(options):
            options[ans]["correct"] = True
            answered = True
        out.append({"text": t[:3500], "options": options, "answered": answered})
    return out
