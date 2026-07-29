import re
from typing import List, Tuple


def safe_truncate_html(html_text: str, max_length: int, suffix: str = "...") -> str:
    if len(html_text) <= max_length:
        return html_text

    tag_pattern = r'<[^>]+>'
    tags = []
    for match in re.finditer(tag_pattern, html_text):
        tags.append({
            'start': match.start(),
            'end': match.end(),
            'tag': match.group(),
            'is_opening': not match.group().startswith('</')
        })

    safe_cut_pos = max_length - len(suffix)

    for tag in tags:
        if tag['start'] < safe_cut_pos < tag['end']:
            safe_cut_pos = tag['start']
            break

    truncated = html_text[:safe_cut_pos]

    open_tags = []
    for tag in tags:
        if tag['end'] <= safe_cut_pos:
            tag_name = extract_tag_name(tag['tag'])
            if tag['is_opening'] and not is_self_closing_tag(tag_name):
                open_tags.append(tag_name)
            elif not tag['is_opening'] and open_tags:
                if tag_name in open_tags:
                    open_tags.remove(tag_name)

    for tag_name in reversed(open_tags):
        truncated += f"</{tag_name}>"

    return truncated + suffix


def extract_tag_name(tag: str) -> str:
    tag_content = tag.strip('<>')
    if tag_content.startswith('/'):
        tag_content = tag_content[1:]

    return tag_content.split()[0].lower()


def is_self_closing_tag(tag_name: str) -> bool:
    self_closing = {'br', 'hr', 'img', 'input', 'meta', 'link', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}
    return tag_name in self_closing


def safe_truncate_text_in_html(html_text: str, max_text_length: int, suffix: str = "...") -> str:
    text_only = re.sub(r'<[^>]+>', '', html_text)

    if len(text_only) <= max_text_length:
        return html_text

    current_length = 0
    result = ""
    i = 0

    while i < len(html_text) and current_length < max_text_length:
        if html_text[i] == '<':
            tag_end = html_text.find('>', i)
            if tag_end != -1:
                result += html_text[i:tag_end + 1]
                i = tag_end + 1
            else:
                break
        else:
            result += html_text[i]
            current_length += 1
            i += 1

    return _close_open_tags(result) + suffix


def _close_open_tags(html: str) -> str:
    tag_pattern = r'<([^/>][^>]*)>'
    closing_pattern = r'</([^>]+)>'

    opening_tags = re.findall(tag_pattern, html)
    closing_tags = re.findall(closing_pattern, html)

    open_tag_names = [tag.split()[0].lower() for tag in opening_tags]
    close_tag_names = [tag.lower() for tag in closing_tags]

    unclosed = []
    for tag_name in open_tag_names:
        if not is_self_closing_tag(tag_name):
            if tag_name in close_tag_names:
                close_tag_names.remove(tag_name)
            else:
                unclosed.append(tag_name)

    result = html
    for tag_name in reversed(unclosed):
        result += f"</{tag_name}>"

    return result
