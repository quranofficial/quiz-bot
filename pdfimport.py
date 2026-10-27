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
import os
import unicodedata

try:
    import glob
except Exception:
    glob = None

try:
    import urllib.request
except Exception:
    urllib_request = None
else:
    urllib_request = urllib.request

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

# ---- پشتگیری کوردی سۆرانی بۆ OCR ----
# Tesseract بە شێوەی بنەڕەت کوردی سۆرانی (kur_ara) نییە — تەنها ara/fas/eng.
# ara و fas بۆ سۆرانی هەڵەی زۆر دەکەن (ڕ، ڵ، ۆ، ێ، ە، گ، چ، پ، ژ دەبینەوە بە پیتی عەرەبی/فارسی).
# بۆیە لە سەرەتای یەکەم بەکارهێنان، kur_ara.traineddata دادەگرین لە tessdata_fas و
# لە فۆڵدەرێکی ناوخۆییدا دادەنێین (لە دەرەوەی ریپۆ — /tmp) و TESSDATA_PREFIX
# بۆی دەکەینەوە — هیچ گۆڕانکارییەکی workflow پێویست نییە.

_TESS_LOCAL = "/tmp/tessdata_local"
_KUR_URLS = (
    # مۆدێلی تایبەت بە کوردی ناوەندی/سۆرانی (finetuned بۆ Tesseract 4/5)
    "https://raw.githubusercontent.com/Shreeshrii/tesstrain-ckb/master/data/ckbLayer_fast.traineddata",
    "https://raw.githubusercontent.com/Shreeshrii/tesstrain-ckb/master/data/ckbLayer.traineddata",
    # پاشکۆ: مۆدێلی سکریپتی عەرەبی (هەموو زمانە عەرەبی-نووسەکان)
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/script/Arabic.traineddata",
)
_KUR_STATE = None   # None = هێشتا پشکنەکراوە، True/False = ئەنجامی _ensure_kur_ara


def _find_system_tessdata():
    """فۆڵدەری tessdata ی سیستەم دەدۆزێتەوە (بۆ symlink ی زمانەکانی تر)."""
    if glob is None:
        return None
    for pat in ("/usr/share/tesseract-ocr/*/tessdata",
                "/usr/share/tesseract-ocr/tessdata",
                "/usr/share/tessdata", "/usr/share/tesseract/tessdata"):
        try:
            hits = glob.glob(os.path.join(pat, "eng.traineddata"))
        except Exception:
            continue
        if hits:
            return os.path.dirname(hits[0])
    return None


def _ensure_kur_ara() -> bool:
    """کوردی سۆرانی (kur_ara) بۆ OCR ئامادە دەکات — True ئەگەر بەردەست بێت.
    • ئەگەر سیستەم kur_ara ی هەبێت → هیچ ناکات.
    • نەبوو → kur_ara.traineddata دادەگرێت و TESSDATA_PREFIX دەگۆڕێت،
      زمانەکانی سیستەم (eng/ara/fas/osd) بە symlink دەچنە ناو فۆڵدەرە ناوخۆییەکە."""
    global _KUR_STATE
    if _KUR_STATE is not None:
        return _KUR_STATE
    _KUR_STATE = False
    if pytesseract is None or urllib_request is None:
        return _KUR_STATE
    try:
        avail = set(pytesseract.get_languages(config="") or [])
    except Exception:
        avail = set()
    if "kur_ara" in avail:
        _KUR_STATE = True
        return _KUR_STATE
    try:
        if os.name != "nt":
            os.makedirs(_TESS_LOCAL, exist_ok=True)
            tgt = os.path.join(_TESS_LOCAL, "kur_ara.traineddata")
            if (not os.path.exists(tgt)) or os.path.getsize(tgt) < 100000:
                for url in _KUR_URLS:
                    try:
                        with urllib_request.urlopen(url, timeout=120) as r:
                            data = r.read()
                        if len(data) > 100000:
                            with open(tgt, "wb") as f:
                                f.write(data)
                            break
                    except Exception:
                        continue
            if not (os.path.exists(tgt) and os.path.getsize(tgt) > 100000):
                return _KUR_STATE
            # زمانەکانی سیستەم بە symlink بێنە ناو فۆڵدەرە ناوخۆییەکە
            sys_dir = _find_system_tessdata()
            if sys_dir:
                for name in ("eng.traineddata", "ara.traineddata",
                             "fas.traineddata", "osd.traineddata"):
                    src = os.path.join(sys_dir, name)
                    dst = os.path.join(_TESS_LOCAL, name)
                    if os.path.exists(src) and not os.path.exists(dst):
                        try:
                            os.symlink(src, dst)
                        except Exception:
                            try:
                                import shutil
                                shutil.copy2(src, dst)
                            except Exception:
                                pass
            os.environ["TESSDATA_PREFIX"] = _TESS_LOCAL
            try:
                avail = set(pytesseract.get_languages(config="") or [])
            except Exception:
                avail = set()
            _KUR_STATE = "kur_ara" in avail
    except Exception:
        _KUR_STATE = False
    return _KUR_STATE


class ImportError_(Exception):
    """هەڵەی گشتی هێنان — پەیامەکەی بۆ ئادمین پیشان دەدرێت."""


def _require(cond, msg):
    if not cond:
        raise ImportError_(msg)


# ---------------- دەرهێنانی دەق ----------------

def _ocr_langs():
    """باشترین زمانە بەردەستەکان بۆ OCR — کوردی سۆرانی لە پێش هەموویانە.
    ئەگەر kur_ara بەردەست بێت: kur_ara (و +fas ئەگەر هەبێت).
    تێبینی: eng نەگوازراوەتەوە چونکە لە تێکەڵەدا زاڵ دەبێت و دەقی کوردی دەکاتە
    دەقی لاتینی غەیرەخوێندراو — eng تەنها بۆ فایلی بێ kur_ara بەکاردێت."""
    _ensure_kur_ara()
    try:
        avail = set(pytesseract.get_languages(config="") or [])
    except Exception:
        avail = set()
    if "kur_ara" in avail:
        pick = ["kur_ara"]
        if "fas" in avail:
            pick.append("fas")
        return "+".join(pick)
    pick = [l for l in ("ara", "fas", "eng") if l in avail]
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
            # و باشترینی (تێکست یان OCR) هەڵبژێرە — ئەوەی پرسیاری زیاتر دەپارسێت
            ocr = _page_ocr(page)
            if not ocr.strip():
                out.append(txt)
                continue
            try:
                n_txt = len(parse_questions(txt))
            except Exception:
                n_txt = 0
            try:
                n_ocr = len(parse_questions(ocr))
            except Exception:
                n_ocr = 0
            out.append(ocr if n_ocr > n_txt else txt)
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return "\n".join(out)


def _ocr_text(img, langs=None):
    """OCR بە چەند پێکەهاتە و تێکەڵە زمانێکی جیاواز — ئەو دەقە دەگەڕێنێتەوە کە
    زۆرترین پرسیاری تێدا دەپارسێت.
    بۆ نموونە بۆ kur_ara+fas+eng سێ تێکەڵە تاقی دەکەینەوە:
      kur_ara+fas+eng → kur_ara+fas → kur_ara  (هەریەکە بە psm ٦ و ٤)
    زوو دەوەستێت ئەگەر ٣ پرسیار یان زیاتر بناسرێنەوە."""
    if langs:
        parts = [l for l in langs.split("+") if l]
    else:
        parts = []
    if parts:
        combos = ["+".join(parts)]
        if len(parts) > 2:
            combos.append("+".join(parts[:2]))
            combos.append(parts[0])
        elif len(parts) == 2:
            combos.append(parts[0])
    else:
        combos = [None]
    best_txt, best_n = "", -1
    for lg in combos:
        for psm in (6, 4):
            try:
                cfg = "--psm {}".format(psm)
                if lg:
                    txt = pytesseract.image_to_string(img, lang=lg, config=cfg) or ""
                else:
                    txt = pytesseract.image_to_string(img, config=cfg) or ""
            except Exception:
                continue
            txt = _repair_ocr(txt)
            n = len(parse_questions(txt))
            if n > best_n:
                best_txt, best_n = txt, n
            if best_n >= 3:
                return best_txt   # باشە — زۆر پرسیار دۆزرانەوە
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
# شێوازی OCR: "B وەڵام:" — پیتەکە پێش وشەی وەڵام دێت (RTL لای OCR)
_ANS_RE2 = re.compile(
    u"\\(?\\s*([A-DＡ-Ｄأبجد])\\s*\\)?\\s*[:\\-–=]?\\s*"
    u"(?:وەڵامی?\\s*ڕاست|وەڵامی?\\s*دروست|وەڵام|ئەنجام|جاوب|answer|correct)", re.I)

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


# ---------------- چاککردنی تامی بژاردەکان لە دەقی OCR ----------------

# لە OCR ی کوردیدا پیتەکانی A/B/C/D زۆرجار تێک دەچن (A→٨، C→2، D→) …).
# دێڕی بژاردەی تێکچوو: پێشەکی غەیرە-عەرەبی (ژمارە/کەوانە/غەیرە) + تام + دەقی عەرەبی-نووس
_MANGLE_BODY_RE = re.compile(
    u"^[\u0621-\u064A\u066E-\u06D3\uFB50-\uFDFF\uFE70-\uFEFF]")  # یەکەم پیت = پیتی عەرەبی/کوردی ڕاستەقینە
_MANGLE_OPT_RE = re.compile(
    u"^[^\u0621-\u064A\u066E-\u06D3\uFB50-\uFDFF\uFE70-\uFEFFA-Za-z]{0,6}"
    u"[.\\)\\-–:|]?\\s*"
    u"([\u0621-\u064A\u066E-\u06D3\uFB50-\uFDFF\uFE70-\uFEFF][^\u064B-\u065F]{1,})$")

# بژاردەی پێچەوانە: "٢٠٤(٨" — دەق + کەوانە + پیتێکی تێکچوو لە کۆتایی
_MANGLE_REV_RE = re.compile(
    u"^(.{2,60}?)[\\(\\[\\{]\\s*[^\\s\u0621-\u064A\u066E-\u06D3\uFB50-\uFDFF\uFE70-\uFEFFA-Za-z]$")
_ARABIC_LETTER_RE = re.compile(
    u"[\u0621-\u064A\u066E-\u06D3\uFB50-\uFDFF\uFE70-\uFEFF]")
# وشەی وەڵام بەبێ پیتی دروست — دێڕی غەیرە-خوێندراو ("٨ وەڵام:")
_ANS_WORD_RE = re.compile(u"وەڵام|جاوب|ئەنجام|answer|correct|key", re.I)


def _repair_ocr(text: str) -> str:
    """چاککردنی دێڕەکانی بژاردە لە دەقی OCR کە تامەکانیان (A-D) تێکچووە.

    شێواز: دوای هەر ژمارەی پرسیار، ٤ دێڕی بژاردە بە ڕیز دێن.
    • پێشەوە: "٨ - جگەر" ← "A) جگەر"   (پیت لە سەرەتا، تێکچوو)
    • پێچەوانە: "٢٠٤(٨" ← "A) ٢٠٤"     (پیت لە کۆتایی، کەوانە لە ناوەڕاست)
    • دێڕی دروست ("A) …") وەک خۆی دەمێنێتەوە.
    • دێڕی غەیرە-خوێندراو ("٣:]") لادەبرێت — وەک پرسیار ژماردە نەکرێت.
    بۆ دەقی ئاسایی (دەرهێنانی ڕاستەوخۆی PDF) هیچ کاریگەری نییە."""
    if not text:
        return text
    out = []
    expect = None          # ئەگەر ژمارەی پرسیار دیاری نەکراوە — None
    last_q = 0
    for ln in text.split("\n"):
        s = ln.strip().strip(u"\u200e\u200f\u202a-\u202e\ufeff\u00ad").strip()
        if not s:
            out.append(ln)
            continue
        # ---- ژمارەی پرسیار — دەبێت دەقی گونجاو بێت و بە دوایین ژمارە + ١ بێت
        qm = _QNUM_RE.match(s)
        om = _OPT_RE.match(s) or _OPT_RE2.match(s)
        if qm and not om:
            qn = int(qm.group(1))
            body = (qm.group(2) or "").strip()
            ok_body = len(body) >= 3 and bool(_ARABIC_LETTER_RE.search(body))
            ok_seq = (qn == last_q + 1 or qn == 1
                      or (last_q == 0 and qn <= 5))
            if ok_body and ok_seq:
                last_q = qn
                expect = 0
                out.append(ln)
                continue
        # ---- دێڕی بژاردە بە پیتی ناسراو
        if om and expect is not None:
            L = _norm_letter(om.group(1))
            if L:
                idx = ord(L) - ord("A")
                body = om.group(2).strip()
                # ڕێکخستنەوە: پیتی هەڵە بە پیتی چاوەڕوانکراو شوێنی دەگیرێتەوە
                out.append("{}) {}".format(chr(ord("A") + expect), body))
                expect += 1
                continue
        # ---- دێڕی وەڵام — بە پیتی ناسراو: وەک خۆی؛ بێ پیت: لادەبرێت
        if _ANS_RE.search(s) or _ANS_RE2.search(s):
            out.append(ln)
            continue
        if _ANS_WORD_RE.search(s):
            continue
        # ---- بژاردەی تێکچوو (پێشەوە یان پێچەوانە) — تەنها لە کاتی چاوەڕوانیدا
        if expect is not None and 0 <= expect < 4:
            mm = _MANGLE_OPT_RE.match(s)
            if mm and _MANGLE_BODY_RE.match(mm.group(1)):
                body = mm.group(1).strip()
                if len(body) >= 2:
                    out.append("{}) {}".format(chr(ord("A") + expect), body))
                    expect += 1
                    continue
            rm = _MANGLE_REV_RE.match(s)
            if rm:
                body = rm.group(1).strip()
                if (len(body) >= 2 and not body.endswith("؟")
                        and re.search(u"[\\u0621-\\u064A\\u066E-\\u06D3\\uFB50-\\uFDFF\\uFE70-\\uFEFF\\u0660-\\u0669]", body)):
                    out.append("{}) {}".format(chr(ord("A") + expect), body))
                    expect += 1
                    continue
        # ---- دێڕی غەیرە-خوێندراو لە ناوەڕاستی بژاردەکاندا — لادەبرێت
        if expect is not None and 0 < expect < 4 and not _MANGLE_BODY_RE.search(s):
            continue
        out.append(ln)
    return "\n".join(out)


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
        if am is None:
            am2 = _ANS_RE2.search(ln)
            am = am2 if am2 else None
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
