import logging
import asyncio
from typing import Optional, Union, Dict, Tuple
from telethon import TelegramClient
from telethon.tl.types import Chat, Channel

logger = logging.getLogger(__name__)

_entity_cache: Dict[str, Tuple] = {}

def normalize_group_id(group_id: Union[str, int]) -> str:
    try:
        id_str = str(group_id)

        if id_str.startswith('-100'):
            return id_str[4:]
        elif id_str.startswith('-'):
            return id_str[1:]
        else:
            return id_str

    except Exception as e:
        logger.error(f"Ошибка нормализации ID группы {group_id}: {e}")
        return str(group_id)

def get_entity_id_variants(group_id: str) -> list:
    variants = []

    try:
        variants.append(group_id)

        if group_id.isdigit():
            group_id_int = int(group_id)

            variants.extend([
                group_id_int,
                -group_id_int,
                f"-100{group_id}",
                int(f"-100{group_id}"),
                f"-{group_id}",
            ])

            if group_id_int > 0:
                variants.extend([
                    f"chat#{group_id}",
                    f"#{group_id}",
                ])
        elif group_id.startswith('-100'):
            base_id = group_id[4:]
            if base_id.isdigit():
                variants.extend([
                    int(group_id),
                    base_id,
                    int(base_id),
                    f"-{base_id}",
                    int(f"-{base_id}"),
                    f"channel#{base_id}",
                ])
        elif group_id.startswith('-'):
            base_id = group_id[1:]
            if base_id.isdigit():
                variants.extend([
                    int(group_id),
                    base_id,
                    int(base_id),
                    f"-100{base_id}",
                    int(f"-100{base_id}"),
                    f"channel#{base_id}",
                ])

        seen = set()
        unique_variants = []

        if group_id.isdigit() and int(group_id) > 0:
            priority_variant = int(group_id)
            if priority_variant not in seen:
                seen.add(priority_variant)
                unique_variants.append(priority_variant)

        for variant in variants:
            if variant not in seen:
                seen.add(variant)
                unique_variants.append(variant)

        return unique_variants

    except Exception as e:
        logger.error(f"Ошибка генерации вариантов ID для {group_id}: {e}")
        return [group_id]

async def try_get_entity_by_id(client: TelegramClient, group_id: str, logger_instance=None):
    if not logger_instance:
        logger_instance = logger

    try:
        if group_id in _entity_cache:
            cached_entity, cached_actual_id = _entity_cache[group_id]
            logger_instance.debug(f"💾 Использую кэш для группы {group_id}")
            return cached_entity, cached_actual_id

        id_variants = get_entity_id_variants(group_id)

        logger_instance.debug(f"🔍 Пробуем {len(id_variants)} вариантов ID для группы {group_id}: {id_variants}")

        for i, variant in enumerate(id_variants):
            try:
                logger_instance.debug(f"  Вариант {i+1}/{len(id_variants)}: {variant} (тип: {type(variant)})")
                entity = await client.get_entity(variant)
                logger_instance.info(f"✅ Группа найдена! ID {group_id} -> вариант {variant} -> сущность ID {entity.id} ({getattr(entity, 'title', 'No title')})")

                await _check_group_access(client, entity, logger_instance)

                _entity_cache[group_id] = (entity, variant)
                return entity, variant

            except Exception as e:
                error_msg = str(e)
                logger_instance.debug(f"  ❌ Вариант {variant} не подошел: {error_msg}")

                if 'CHAT_ADMIN_REQUIRED' in error_msg:
                    logger_instance.warning(f"⚠️ Нужны права администратора для группы {variant}")
                elif 'USER_BANNED_IN_CHANNEL' in error_msg:
                    logger_instance.warning(f"🚫 Аккаунт заблокирован в группе {variant}")
                elif 'CHANNEL_PRIVATE' in error_msg:
                    logger_instance.warning(f"🔒 Группа {variant} является приватной")
                elif 'NO_SUCH_CHAT' in error_msg:
                    logger_instance.warning(f"❌ Группа {variant} не существует или удалена")
                elif any(err in error_msg.lower() for err in ['flood', 'timeout', 'network']):
                    logger_instance.warning(f"⚠️ Сетевая ошибка для варианта {variant}: {error_msg}")
                    await asyncio.sleep(0.5)
                continue

        logger_instance.info(f"🔍 Прямой поиск не удался. Поиск группы {group_id} в диалогах...")

        try:
            dialog_count = 0
            found_similar = []

            async for dialog in client.iter_dialogs():
                dialog_count += 1
                entity_id = str(dialog.entity.id)
                normalized_id = normalize_group_id(entity_id)
                entity_title = getattr(dialog.entity, 'title', getattr(dialog.entity, 'first_name', 'No title'))

                matches = []
                if entity_id == group_id:
                    matches.append(f"exact_match({entity_id})")
                if normalized_id == group_id:
                    matches.append(f"normalized_match({normalized_id})")
                if str(abs(dialog.entity.id)) == group_id:
                    matches.append(f"abs_match({abs(dialog.entity.id)})")

                for variant in id_variants:
                    variant_str = str(variant)
                    if entity_id == variant_str or normalized_id == variant_str:
                        matches.append(f"variant_match({variant})")
                        break

                if any(group_id in str(variant) for variant in [entity_id, normalized_id, abs(dialog.entity.id)]):
                    found_similar.append(f"ID:{entity_id}({entity_title})")

                if matches:
                    logger_instance.info(f"✅ Группа найдена в диалогах! {group_id} -> {entity_title} (ID: {dialog.entity.id}) | Совпадения: {', '.join(matches)}")

                    _entity_cache[group_id] = (dialog.entity, dialog.entity.id)
                    return dialog.entity, dialog.entity.id

            if found_similar:
                logger_instance.info(f"🔍 Найдены похожие ID: {', '.join(found_similar[:5])}")

            logger_instance.warning(f"❌ Группа {group_id} не найдена среди {dialog_count} диалогов")

            logger_instance.info(f"📋 Первые группы/каналы в диалогах:")
            groups_shown = 0
            async for dialog in client.iter_dialogs():
                if hasattr(dialog.entity, 'title') and groups_shown < 10:
                    logger_instance.info(f"  - ID: {dialog.entity.id} | {dialog.entity.title}")
                    groups_shown += 1
                elif groups_shown >= 10:
                    break

        except Exception as dialog_error:
            logger_instance.error(f"❌ Ошибка при поиске в диалогах: {dialog_error}")

        logger_instance.info(f"🔍 Последняя попытка поиска через InputPeer...")

        try:
            from telethon.tl.types import InputPeerChannel, InputPeerChat

            for variant in id_variants:
                if isinstance(variant, int) and variant < 0:
                    try:
                        input_peer = InputPeerChannel(abs(variant), 0)
                        entity = await client.get_entity(input_peer)
                        logger_instance.info(f"✅ Группа найдена через InputPeerChannel! {group_id} -> {getattr(entity, 'title', 'No title')} (ID: {entity.id})")

                        _entity_cache[group_id] = (entity, variant)
                        return entity, variant
                    except:
                        pass

                    try:
                        input_peer = InputPeerChat(abs(variant))
                        entity = await client.get_entity(input_peer)
                        logger_instance.info(f"✅ Группа найдена через InputPeerChat! {group_id} -> {getattr(entity, 'title', 'No title')} (ID: {entity.id})")

                        _entity_cache[group_id] = (entity, variant)
                        return entity, variant
                    except:
                        pass

        except Exception as peer_error:
            logger_instance.error(f"❌ Ошибка при поиске через InputPeer: {peer_error}")

        logger_instance.warning(f"❌ Группа {group_id} не найдена ни одним способом")
        return None, None

    except Exception as e:
        logger_instance.error(f"❌ Критическая ошибка поиска группы {group_id}: {e}")
        return None, None

async def _check_group_access(client: TelegramClient, entity, logger_instance):
    try:
        entity_type = type(entity).__name__
        title = getattr(entity, 'title', 'No title')

        logger_instance.info(f"  📊 Тип: {entity_type}, Название: {title}")

        if hasattr(entity, 'default_banned_rights'):
            banned_rights = entity.default_banned_rights
            if banned_rights:
                restrictions = []
                if banned_rights.send_messages:
                    restrictions.append("отправка сообщений")
                if banned_rights.send_media:
                    restrictions.append("отправка медиа")
                if banned_rights.send_stickers:
                    restrictions.append("стикеры")

                if restrictions:
                    logger_instance.warning(f"  🚫 Ограничения: {', '.join(restrictions)}")
                else:
                    logger_instance.info(f"  ✅ Нет ограничений на отправку")

        if hasattr(entity, 'participants_count'):
            logger_instance.info(f"  👥 Участников: {entity.participants_count}")

        try:
            me = await client.get_me()
            if me is None:
                logger_instance.warning(f"  ⚠️ Не удалось получить информацию об аккаунте")
                return
            participants = await client.get_participants(entity, limit=1)
            logger_instance.info(f"  ✅ Аккаунт состоит в группе")
        except Exception as check_error:
            logger_instance.warning(f"  ⚠️ Проблема с участием в группе: {check_error}")

    except Exception as e:
        logger_instance.debug(f"  ❌ Ошибка проверки доступа: {e}")

def get_correct_group_id_for_storage(entity) -> str:
    try:
        if isinstance(entity, (Chat, Channel)):
            return str(entity.id)
        else:
            return str(entity.id)

    except Exception as e:
        logger.error(f"Ошибка получения ID для сохранения: {e}")
        return str(entity.id) if hasattr(entity, 'id') else 'unknown'

async def diagnose_group_access(client: TelegramClient, group_id: str, logger_instance=None):
    if not logger_instance:
        logger_instance = logger

    result = {
        'group_id': group_id,
        'found': False,
        'entity': None,
        'can_send': False,
        'error': None,
        'entity_type': None,
        'title': None,
        'participants_count': None
    }

    try:
        entity, actual_id = await try_get_entity_by_id(client, group_id, logger_instance)

        if not entity:
            result['error'] = 'Группа не найдена'
            return result

        result['found'] = True
        result['entity'] = entity
        result['entity_type'] = type(entity).__name__
        result['title'] = getattr(entity, 'title', 'Unknown')
        result['participants_count'] = getattr(entity, 'participants_count', None)

        try:
            me = await client.get_me()
            if me is None:
                result['can_send'] = False
                result['error'] = 'Не удалось получить информацию об аккаунте'
                return result

            if hasattr(entity, 'default_banned_rights'):
                banned_rights = entity.default_banned_rights
                if banned_rights and banned_rights.send_messages:
                    result['can_send'] = False
                    result['error'] = 'Отправка сообщений запрещена'
                else:
                    result['can_send'] = True
            else:
                result['can_send'] = True

        except Exception as e:
            result['error'] = f'Ошибка проверки прав: {e}'

        logger_instance.info(f"📊 Диагностика группы {group_id}: найдена={result['found']}, "
                           f"тип={result['entity_type']}, название={result['title']}, "
                           f"можно_отправлять={result['can_send']}")

        return result

    except Exception as e:
        result['error'] = str(e)
        logger_instance.error(f"❌ Ошибка диагностики группы {group_id}: {e}")
        return result

def clear_entity_cache():
    global _entity_cache
    cache_size = len(_entity_cache)
    _entity_cache.clear()
    logger.info(f"🧹 Очищен кэш сущностей, было записей: {cache_size}")

def get_cache_stats():
    return {
        'cache_size': len(_entity_cache),
        'cached_groups': list(_entity_cache.keys())
    }

async def debug_list_all_dialogs(client: TelegramClient, logger_instance=None):
    if not logger_instance:
        logger_instance = logger

    try:
        logger_instance.info("🔍 === ОТЛАДКА: Список всех диалогов ===")

        dialog_count = 0
        group_count = 0
        channel_count = 0

        async for dialog in client.iter_dialogs():
            dialog_count += 1
            entity = dialog.entity
            entity_type = type(entity).__name__

            if hasattr(entity, 'megagroup') and entity.megagroup:
                dialog_type = "СУПЕРГРУППА"
                group_count += 1
            elif entity_type == "Channel":
                dialog_type = "КАНАЛ"
                channel_count += 1
            elif entity_type == "Chat":
                dialog_type = "ГРУППА"
                group_count += 1
            else:
                dialog_type = "ПОЛЬЗОВАТЕЛЬ"

            logger_instance.info(f"  {dialog_count}. ID: {entity.id} | Тип: {dialog_type} | Название: {getattr(entity, 'title', getattr(entity, 'first_name', 'Unknown'))}")

            if dialog_count <= 20:
                logger_instance.info(f"     Детали: {entity_type}, доступ_хэш: {getattr(entity, 'access_hash', 'N/A')}")

        logger_instance.info(f"📊 Итого диалогов: {dialog_count} (Групп: {group_count}, Каналов: {channel_count})")
        logger_instance.info("🔍 === КОНЕЦ ОТЛАДКИ ДИАЛОГОВ ===")

        return dialog_count

    except Exception as e:
        logger_instance.error(f"❌ Ошибка при отладке диалогов: {e}")
        return 0

async def search_group_by_keywords(client: TelegramClient, keywords: list, logger_instance=None):
    if not logger_instance:
        logger_instance = logger

    try:
        logger_instance.info(f"🔍 Поиск групп по ключевым словам: {keywords}")

        found_groups = []

        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            title = getattr(entity, 'title', '')

            if title:
                for keyword in keywords:
                    if keyword.lower() in title.lower():
                        found_groups.append({
                            'id': entity.id,
                            'title': title,
                            'type': type(entity).__name__
                        })
                        logger_instance.info(f"  ✅ Найдена группа: ID {entity.id} | {title}")
                        break

        logger_instance.info(f"📊 Найдено групп: {len(found_groups)}")
        return found_groups

    except Exception as e:
        logger_instance.error(f"❌ Ошибка поиска по ключевым словам: {e}")
        return []
