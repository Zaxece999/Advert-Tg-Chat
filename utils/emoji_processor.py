import re
from typing import Optional, List, Tuple
from aiogram.types import Message, MessageEntity
import html
import logging

logger = logging.getLogger(__name__)

def find_emoji_positions(text: str) -> List[Tuple[int, int, str]]:
    emoji_pattern = re.compile(
        r'[\U0001F600-\U0001F64F]|'
        r'[\U0001F300-\U0001F5FF]|'
        r'[\U0001F680-\U0001F6FF]|'
        r'[\U0001F1E0-\U0001F1FF]|'
        r'[\U00002702-\U000027B0]|'
        r'[\U000024C2-\U0001F251]|'
        r'[\U0001F900-\U0001F9FF]|'
        r'[\U0001FA70-\U0001FAFF]'
    )
    emojis = []
    for match in emoji_pattern.finditer(text):
        emojis.append((match.start(), match.start() + 1, match.group()))
    return emojis

def correct_entity_positions(message: Message) -> List[MessageEntity]:
    text = message.text
    if not text or not message.entities:
        return message.entities or []

    sorted_entities = sorted(message.entities, key=lambda x: x.offset)
    corrected_entities = []
    offset_shift = 0
    emoji_positions = find_emoji_positions(text)
    emoji_index = 0

    for i, entity in enumerate(sorted_entities):
        original_offset = entity.offset

        while emoji_index < len(emoji_positions):
            emoji_start, _, emoji_text = emoji_positions[emoji_index]
            if emoji_start < original_offset:
                if len(emoji_text) > 1:
                    offset_shift -= len(emoji_text) - 1
                emoji_index += 1
            else:
                break

        if entity.type == "custom_emoji":
            corrected_entity = MessageEntity(
                type=entity.type,
                offset=original_offset + offset_shift,
                length=1,
                custom_emoji_id=entity.custom_emoji_id
            )
            corrected_entities.append(corrected_entity)
            logger.debug(f"Custom emoji {i}: original_offset={original_offset}, "
                        f"original_length={entity.length}, new_offset={corrected_entity.offset}, "
                        f"offset_shift_after={offset_shift}")
        else:
            corrected_entity = MessageEntity(
                type=entity.type,
                offset=original_offset + offset_shift,
                length=entity.length,
                url=getattr(entity, 'url', None),
                user=getattr(entity, 'user', None),
                language=getattr(entity, 'language', None),
                custom_emoji_id=getattr(entity, 'custom_emoji_id', None)
            )
            corrected_entities.append(corrected_entity)
            logger.debug(f"Entity {i} ({entity.type}): original_offset={original_offset}, "
                        f"new_offset={corrected_entity.offset}, offset_shift={offset_shift}")

    return corrected_entities

def correct_non_emoji_entity(text: str, entity: MessageEntity) -> MessageEntity:
    original_start = entity.offset
    original_end = entity.offset + entity.length
    if original_start < len(text) and original_end <= len(text):
        original_text = text[original_start:original_end]
        if original_text.strip():
            return entity
    if entity.type == "strikethrough":
        for i, char in enumerate(text):
            if char in '?!.,;:':
                corrected_entity = MessageEntity(
                    type=entity.type,
                    offset=i,
                    length=1
                )
                return corrected_entity
    return entity

def parse_html_to_telethon_entities(html_text: str) -> Tuple[str, List]:
    try:
        from telethon.tl.types import MessageEntityCustomEmoji, MessageEntityBold, MessageEntityItalic, MessageEntityStrike, MessageEntityCode, MessageEntityPre
        plain_text = html_text
        all_entities = []
        all_tags = []
        emoji_pattern = r'<tg-emoji emoji-id="([^"]+)">([^<]+)</tg-emoji>'
        for match in re.finditer(emoji_pattern, html_text):
            all_tags.append({
                'start': match.start(),
                'end': match.end(),
                'type': 'custom_emoji',
                'emoji_id': match.group(1),
                'content': match.group(2),
                'full_match': match.group(0)
            })
        html_tags = [
            (r'<b>(.*?)</b>', MessageEntityBold, 'bold'),
            (r'<i>(.*?)</i>', MessageEntityItalic, 'italic'),
            (r'<s>(.*?)</s>', MessageEntityStrike, 'strike'),
            (r'<code>(.*?)</code>', MessageEntityCode, 'code'),
            (r'<pre>(.*?)</pre>', MessageEntityPre, 'pre'),
        ]
        for pattern, entity_type, tag_name in html_tags:
            for match in re.finditer(pattern, html_text, re.DOTALL):
                all_tags.append({
                    'start': match.start(),
                    'end': match.end(),
                    'type': 'formatting',
                    'entity_type': entity_type,
                    'content': match.group(1),
                    'full_match': match.group(0),
                    'tag_name': tag_name
                })
        if not all_tags:
            return html_text, []
        all_tags.sort(key=lambda x: x['start'], reverse=True)
        for tag in all_tags:
            start = tag['start']
            end = tag['end']
            content = tag['content']
            if tag['type'] == 'custom_emoji':
                plain_text = plain_text[:start] + content + plain_text[end:]
                entity = MessageEntityCustomEmoji(
                    offset=start,
                    length=len(content),
                    document_id=int(tag['emoji_id'])
                )
                all_entities.append(entity)
            elif tag['type'] == 'formatting':
                plain_text = plain_text[:start] + content + plain_text[end:]
                entity = tag['entity_type'](offset=start, length=len(content))
                all_entities.append(entity)
        all_entities.sort(key=lambda x: x.offset)
        return plain_text, all_entities
    except ImportError:
        return html_text, []
    except Exception:
        return html_text, []

def extract_custom_emojis_from_message(message: Message) -> List[dict]:
    custom_emojis = []
    if not message.entities:
        return custom_emojis
    for i, entity in enumerate(message.entities):
        if entity.type == "custom_emoji":
            actual_length = min(1, len(message.text) - entity.offset)
            emoji_text = message.text[entity.offset:entity.offset + actual_length]
            custom_emojis.append({
                'emoji_id': entity.custom_emoji_id,
                'offset': entity.offset,
                'length': 1,
                'fallback_emoji': emoji_text
            })
    return custom_emojis

def convert_message_to_html_with_formatting(message: Message) -> str:
    if not message.text:
        return ""

    if message.entities:
        return _convert_entities_to_html(message)
    else:
        return convert_markdown_to_html(message.text)


def _convert_entities_to_html(message: Message) -> str:
    if not message.entities:
        return message.text

    sorted_entities = sorted(message.entities, key=lambda x: x.offset)

    positions = []

    for entity in sorted_entities:
        if entity.type == "custom_emoji":
            positions.append({
                'pos': entity.offset,
                'type': 'emoji_start',
                'emoji_id': entity.custom_emoji_id,
                'length': entity.length
            })
            positions.append({
                'pos': entity.offset + entity.length,
                'type': 'emoji_end'
            })
        elif entity.type == "bold":
            positions.append({'pos': entity.offset, 'type': 'bold_start'})
            positions.append({'pos': entity.offset + entity.length, 'type': 'bold_end'})
        elif entity.type == "italic":
            positions.append({'pos': entity.offset, 'type': 'italic_start'})
            positions.append({'pos': entity.offset + entity.length, 'type': 'italic_end'})
        elif entity.type == "underline":
            positions.append({'pos': entity.offset, 'type': 'underline_start'})
            positions.append({'pos': entity.offset + entity.length, 'type': 'underline_end'})
        elif entity.type == "strikethrough":
            positions.append({'pos': entity.offset, 'type': 'strike_start'})
            positions.append({'pos': entity.offset + entity.length, 'type': 'strike_end'})
        elif entity.type == "code":
            positions.append({'pos': entity.offset, 'type': 'code_start'})
            positions.append({'pos': entity.offset + entity.length, 'type': 'code_end'})
        elif entity.type == "pre":
            positions.append({'pos': entity.offset, 'type': 'pre_start'})
            positions.append({'pos': entity.offset + entity.length, 'type': 'pre_end'})
        elif entity.type == "text_link":
            positions.append({
                'pos': entity.offset,
                'type': 'link_start',
                'url': entity.url
            })
            positions.append({'pos': entity.offset + entity.length, 'type': 'link_end'})
        elif entity.type == "blockquote":
            positions.append({'pos': entity.offset, 'type': 'blockquote_start'})
            positions.append({'pos': entity.offset + entity.length, 'type': 'blockquote_end'})
        elif entity.type == "spoiler":
            positions.append({'pos': entity.offset, 'type': 'spoiler_start'})
            positions.append({'pos': entity.offset + entity.length, 'type': 'spoiler_end'})

    positions.sort(key=lambda x: (x['pos'], x['type'].endswith('_end')), reverse=True)

    text = message.text
    for pos_info in positions:
        pos = pos_info['pos']
        tag_type = pos_info['type']

        if tag_type == 'emoji_start':
            emoji_id = pos_info['emoji_id']
            emoji_text = text[pos:pos + pos_info['length']]
            replacement = f'<a href="emoji/{emoji_id}">{emoji_text}</a>'
            text = text[:pos] + replacement + text[pos + pos_info['length']:]
        elif tag_type == 'bold_start':
            text = text[:pos] + '<b>' + text[pos:]
        elif tag_type == 'bold_end':
            text = text[:pos] + '</b>' + text[pos:]
        elif tag_type == 'italic_start':
            text = text[:pos] + '<i>' + text[pos:]
        elif tag_type == 'italic_end':
            text = text[:pos] + '</i>' + text[pos:]
        elif tag_type == 'underline_start':
            text = text[:pos] + '<u>' + text[pos:]
        elif tag_type == 'underline_end':
            text = text[:pos] + '</u>' + text[pos:]
        elif tag_type == 'strike_start':
            text = text[:pos] + '<s>' + text[pos:]
        elif tag_type == 'strike_end':
            text = text[:pos] + '</s>' + text[pos:]
        elif tag_type == 'code_start':
            text = text[:pos] + '<code>' + text[pos:]
        elif tag_type == 'code_end':
            text = text[:pos] + '</code>' + text[pos:]
        elif tag_type == 'pre_start':
            text = text[:pos] + '<pre>' + text[pos:]
        elif tag_type == 'pre_end':
            text = text[:pos] + '</pre>' + text[pos:]
        elif tag_type == 'link_start':
            url = pos_info['url']
            text = text[:pos] + f'<a href="{url}">' + text[pos:]
        elif tag_type == 'link_end':
            text = text[:pos] + '</a>' + text[pos:]
        elif tag_type == 'blockquote_start':
            text = text[:pos] + '<blockquote>' + text[pos:]
        elif tag_type == 'blockquote_end':
            text = text[:pos] + '</blockquote>' + text[pos:]
        elif tag_type == 'spoiler_start':
            text = text[:pos] + '<a href="spoiler">' + text[pos:]
        elif tag_type == 'spoiler_end':
            text = text[:pos] + '</a>' + text[pos:]

    return text


def convert_markdown_to_html(text: str) -> str:
    if not text:
        return ""

    text = _process_premium_emojis(text)

    text = _process_markdown_formatting(text)

    text = _escape_html_safe(text)

    return text


def _process_markdown_formatting(text: str) -> str:
    emoji_placeholders = {}
    emoji_counter = 0

    def protect_emoji(match):
        nonlocal emoji_counter
        placeholder = f"__EMOJI_{emoji_counter}__"
        emoji_placeholders[placeholder] = match.group(0)
        emoji_counter += 1
        return placeholder

    emoji_pattern = r'<a href="emoji/\d+">[^<]+</a>'
    text = re.sub(emoji_pattern, protect_emoji, text)

    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)

    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)

    text = re.sub(r'~(.*?)~', r'<u>\1</u>', text)

    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)

    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)

    text = re.sub(r'```(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)

    text = re.sub(r'^>\s*(.*?)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)

    for placeholder, emoji in emoji_placeholders.items():
        text = text.replace(placeholder, emoji)

    return text


def _process_premium_emojis(text: str) -> str:
    emoji_pattern = r'\[(\d+):([^\]]+)\]'

    def replace_emoji(match):
        emoji_id = match.group(1)
        emoji_text = match.group(2).strip()
        return f'<a href="emoji/{emoji_id}">{emoji_text}</a>'

    return re.sub(emoji_pattern, replace_emoji, text)


def _escape_html_safe(text: str) -> str:
    import re

    tag_placeholders = {}
    tag_counter = 0

    def protect_tag(match):
        nonlocal tag_counter
        placeholder = f"__TAG_{tag_counter}__"
        tag_placeholders[placeholder] = match.group(0)
        tag_counter += 1
        return placeholder

    tag_pattern = r'<[^>]+>'
    text = re.sub(tag_pattern, protect_tag, text)

    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')

    for placeholder, tag in tag_placeholders.items():
        text = text.replace(placeholder, tag)

    return text


def convert_custom_emoji_message_to_html(message: Message, custom_emoji_entities: List[MessageEntity]) -> str:
    return message.text if message.text else ""


def convert_message_to_html_with_formatting_fallback(message: Message) -> str:
    return message.text if message.text else ""


def convert_message_to_html_with_emojis(message: Message) -> str:
    if not message.text:
        return ""
    return message.text

def process_text_with_custom_emojis(text: str, entities: Optional[List] = None) -> str:
    return text


def process_telethon_message_with_emojis(message) -> str:
    if not hasattr(message, 'text') or not message.text:
        return ""
    return message.text


def clean_broken_html(html_text: str) -> str:
    if not html_text:
        return ""
    return html_text


def safe_html_for_telegram(html_text: str) -> str:
    if not html_text:
        return ""
    return html_text


def html_with_tg_emoji_to_plain_text(html_text: str) -> str:
    if not html_text:
        return ""

    import re

    text = re.sub(r'<a href="emoji/\d+">([^<]+)</a>', r'\1', html_text)
    text = re.sub(r'<tg-emoji[^>]*>([^<]+)</tg-emoji>', r'\1', text)

    text = re.sub(r'<[^>]+>', '', text)

    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')

    return text
