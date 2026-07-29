import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

def convert_markdown_to_html(text: str) -> str:
    try:
        from chatgpt_md_converter.telegram_formatter import telegram_format

        html_text = telegram_format(text)

        html_text = fix_telegram_html_tags(html_text)

        logger.info(f"📝 Markdown конвертирован в HTML: '{text[:50]}...' -> '{html_text[:50]}...'")
        return html_text

    except ImportError as e:
        logger.error(f"❌ Ошибка импорта chatgpt-md-converter: {e}")
        return text
    except Exception as e:
        logger.error(f"❌ Ошибка при конвертации Markdown: {e}")
        return text

def fix_telegram_html_tags(html_text: str) -> str:
    try:
        html_text = re.sub(
            r'<span class="tg-spoiler">([^<]*)</span>',
            r'<a href="spoiler">\1</a>',
            html_text
        )

        html_text = re.sub(
            r'<blockquote expandable>([^<]*)</blockquote>',
            r'<blockquote>\1</blockquote>',
            html_text,
            flags=re.DOTALL
        )

        html_text = re.sub(
            r'<blockquote[^>]*>',
            '<blockquote>',
            html_text
        )

        logger.debug(f"🔧 Исправлены HTML теги для Telegram совместимости")
        return html_text

    except Exception as e:
        logger.error(f"❌ Ошибка при исправлении HTML тегов: {e}")
        return html_text

def is_markdown_text(text: str) -> bool:
    if not text:
        return False

    markdown_indicators = [
        '**',
        '__',
        '*',
        '_',
        '`',
        '```',
        '#',
        '[',
        '![',
        '>',
        '-',
        '+',
        '1.',
        '~~',
    ]

    for indicator in markdown_indicators:
        if indicator in text:
            return True

    return False

def safe_convert_markdown_to_html(text: str) -> str:
    if not text:
        return text

    if is_markdown_text(text):
        logger.info(f"🔍 Обнаружена Markdown разметка в тексте: '{text[:50]}...'")
        return convert_markdown_to_html(text)
    else:
        logger.debug(f"📄 Markdown разметка не обнаружена, возвращаем текст как есть")
        return text
