import json
import subprocess
import logging
import os
from typing import List, Dict, Any, Optional
from aiogram.types import Message, MessageEntity

logger = logging.getLogger(__name__)

def format_message_with_nodejs(message: Message) -> str:
    if not message.text:
        return ""

    entities_data = []
    if message.entities:
        for entity in message.entities:
            entity_dict = {
                'type': entity.type,
                'offset': entity.offset,
                'length': entity.length
            }

            if entity.type == 'custom_emoji' and hasattr(entity, 'custom_emoji_id'):
                entity_dict['custom_emoji_id'] = entity.custom_emoji_id
            elif entity.type == 'text_link' and hasattr(entity, 'url'):
                entity_dict['url'] = entity.url
            elif entity.type == 'mention' and hasattr(entity, 'user'):
                entity_dict['user'] = entity.user

            entities_data.append(entity_dict)

    return format_text_with_nodejs(message.text, entities_data)

def format_text_with_nodejs(text: str, entities: List[Dict[str, Any]] = None) -> str:
    if not text:
        return ""

    try:
        script_path = os.path.join(os.path.dirname(__file__), 'text_formatter.js')

        input_data = {
            'text': text,
            'entities': entities or []
        }

        process = subprocess.Popen(
            ['node', script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate(input=json.dumps(input_data))

        if process.returncode != 0:
            logger.error(f"Node.js форматировщик завершился с ошибкой: {stderr}")
            return text

        try:
            result_data = json.loads(stdout)
            formatted_text = result_data.get('result', text)

            logger.info(f"✅ Текст успешно форматирован через Node.js")
            logger.debug(f"Исходный: {text}...")
            logger.debug(f"Результат: {formatted_text}...")

            return formatted_text

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON ответа от Node.js: {e}")
            logger.error(f"Ответ: {stdout}")
            return text

    except FileNotFoundError:
        logger.error("Node.js не найден в системе. Убедитесь, что Node.js установлен.")
        return text
    except Exception as e:
        logger.error(f"Ошибка при вызове Node.js форматировщика: {e}")
        return text

def format_simple_text(text: str) -> str:
    if not text:
        return ""

    return format_text_with_nodejs(text, [])

def test_formatter():
    test_cases = [
        {
            'text': '💖 Pixel & Palette Studio: наш дизайн - путь к вашему успеху!',
            'entities': [
                {'type': 'custom_emoji', 'offset': 0, 'length': 1, 'custom_emoji_id': '5339342440027402534'},
                {'type': 'bold', 'offset': 3, 'length': 23},
                {'type': 'underline', 'offset': 31, 'length': 6},
                {'type': 'bold', 'offset': 31, 'length': 6}
            ]
        },
        {
            'text': '[💖] Аватарки / Баннеры / Крео',
            'entities': [
                {'type': 'custom_emoji', 'offset': 1, 'length': 1, 'custom_emoji_id': '5339067501990915450'},
                {'type': 'bold', 'offset': 5, 'length': 25},
                {'type': 'italic', 'offset': 5, 'length': 25}
            ]
        }
    ]

    for i, test_case in enumerate(test_cases):
        print(f"Тест {i+1}:")
        print(f"Исходный: {test_case['text']}")
        result = format_text_with_nodejs(test_case['text'], test_case['entities'])
        print(f"Результат: {result}")
        print("-" * 50)

if __name__ == "__main__":
    test_formatter()
