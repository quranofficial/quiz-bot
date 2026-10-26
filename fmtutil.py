# -*- coding: utf-8 -*-
"""فۆرماتکردنی دەق بۆ تێلێگرام.

دوو ڕێگا پشتگیری دەکرێت:
١) مارکەری ساکار (لە ویزاردی زیادکردنی پرسیار و هێنانی JSON):
   **وشە**   → قەڵەو (Bold)
   __وشە__   → لادان (Italic)
   ~~وشە~~   → سڕینەوە (Strikethrough)
   ||وشە||   → شاراوە (Spoiler — کلیک بکە بۆ بینین)
   `وشە`     → کۆد (Monospace)
   {{وشە}}   → تەرخانکردنی تایبەت: 🔴وشە🔴 (نزیکترین شت بە ڕەنگی سوور لە تێلێگرام)

٢) تێگی HTML ی ڕاستەوخۆ:
   <b>قەڵەو</b> <i>لادان</i> <u>خەت لەژێر</u> <s>سڕینەوە</s>
   <code>کۆد</code> <tg-spoiler>شاراوە</tg-spoiler>
   <a href="https://example.com">لینک</a> <blockquote>وتە</blockquote>

> تێبینی: تێلێگرام ڕێگە نادات ڕەنگی فۆنت بگۆڕدرێت؛ نزیکترین شت بە «سوور»
> بەکارهێنانی {{وشە}} یان ئیمۆجی 🔴ـە.

ئەگەر HTML ەکە هەڵە بێت، پەیامەکە بەبێ فۆرمات دەنێردرێت (بێ شکست).
"""

import re

from telegram.error import BadRequest

# ---- یاساکانی گۆڕین (مارکەر → تێگی HTML) ----

_RULES = [
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"<b>\1</b>"),
    (re.compile(r"__(.+?)__", re.S), r"<i>\1</i>"),
    (re.compile(r"~~(.+?)~~", re.S), r"<s>\1</s>"),
    (re.compile(r"\|\|(.+?)\|\|", re.S), r'<span class="tg-spoiler">\1</span>'),
    (re.compile(r"`([^`\n]+?)`"), r"<code>\1</code>"),
    (re.compile(r"\{\{(.+?)\}\}", re.S), r"🔴\1🔴"),
]

# ---- یاساکانی لابردن (مارکەر و تێگەکان دەسڕدرێنەوە — بۆ دوگمە و لیستەکان) ----

_STRIP_RULES = [
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"\1"),
    (re.compile(r"__(.+?)__", re.S), r"\1"),
    (re.compile(r"~~(.+?)~~", re.S), r"\1"),
    (re.compile(r"\|\|(.+?)\|\|", re.S), r"\1"),
    (re.compile(r"`([^`\n]+?)`"), r"\1"),
    (re.compile(r"\{\{(.+?)\}\}", re.S), r"\1"),
    (re.compile(r"</?(?:b|i|u|s|code|pre|a|blockquote|tg-spoiler|span)[^>]{0,100}>"), r""),
]


def apply(text: str) -> str:
    """مارکەرە ساکارەکان دەگۆڕێت بۆ HTML — دەقی HTML ی ڕاستەوخۆ وەک خۆی دەمێنێتەوە."""
    t = text or ""
    for pat, repl in _RULES:
        t = pat.sub(repl, t)
    return t


def plain(text: str) -> str:
    """هەموو مارکەر و تێگەکان لادەبات — بۆ نیشاندانی دەق لە دوگمە و لیستەکاندا."""
    t = text or ""
    for pat, repl in _STRIP_RULES:
        t = pat.sub(repl, t)
    return t


def is_parse_error(e: Exception) -> bool:
    """دەڵێت ئایا ئەم هەڵەیە هەڵەی parse کردنی HTML ـە."""
    s = str(e).lower()
    return "parse entities" in s or "can't parse" in s


async def send_html(bot, chat_id, text: str, **kwargs):
    """پەیام دەنێرێت بە HTML؛ ئەگەر HTML ـەکە هەڵە بێت، بەبێ فۆرمات دەنێردرێت."""
    try:
        return await bot.send_message(chat_id, text, parse_mode="HTML", **kwargs)
    except BadRequest as e:
        if is_parse_error(e):
            return await bot.send_message(chat_id, text, **kwargs)
        raise


async def send_photo_html(bot, chat_id, photo, caption: str = None, **kwargs):
    """وێنە دەنێرێت لەگەڵ کاپشنی HTML؛ ئەگەر هەڵە بێت، بەبێ فۆرمات دەنێردرێت."""
    try:
        return await bot.send_photo(chat_id, photo, caption=caption,
                                    parse_mode="HTML", **kwargs)
    except BadRequest as e:
        if is_parse_error(e):
            return await bot.send_photo(chat_id, photo, caption=caption, **kwargs)
        raise
