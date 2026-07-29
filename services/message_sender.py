import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, UserBannedInChannelError, ChatAdminRequiredError,
    MessageTooLongError, SlowModeWaitError, ChatWriteForbiddenError,
    UserNotParticipantError, ChannelPrivateError, RPCError
)
from telethon.tl.types import InputPeerChannel, InputPeerChat, PeerChannel, PeerChat
import configparser
import io
import re
import multiprocessing
import time
import os
import sys
from database.database import log_message

from database.database import (
    get_active_accounts, get_group_settings, create_group_settings,
    log_message, get_proxy_by_id, db, get_working_proxies
)
from database.models import Account, GroupSettings, SuperGroup
from utils.proxy_validator import get_telethon_proxy_config, validate_proxy_for_telethon
from utils.cyrillic_substitution import apply_cyrillic_substitution
from utils.xtelethon import CustomParseMode, convert_html_to_custom_format
import random

logger = logging.getLogger(__name__)

def process_account_broadcast(account_data):
    try:
        logging.basicConfig(
            level=logging.INFO,
            format=f'%(asctime)s - PROCESS-{os.getpid()} - %(name)s - %(levelname)s - %(message)s'
        )
        process_logger = logging.getLogger(f"account_process_{account_data['id']}")

        process_logger.info(f"🚀 Запуск процесса для аккаунта {account_data['phone_number']} (PID: {os.getpid()})")

        from database.database import Database
        process_db = Database()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                _process_single_account_async(account_data, process_logger, process_db)
            )
            process_logger.info(f"✅ Процесс завершен для аккаунта {account_data['phone_number']}")
            return result
        finally:
            loop.close()

    except Exception as e:
        print(f"❌ Ошибка в процессе аккаунта {account_data.get('phone_number', 'Unknown')}: {e}")
        return {'success': False, 'error': str(e)}

async def _process_single_account_async(account_data, process_logger, process_db):
    try:
        account = type('Account', (), account_data)()

        if not account.is_active or account.subscription_minutes <= 0:
            process_logger.info(f"Аккаунт {account.phone_number} неактивен или подписка истекла")
            return {'success': False, 'reason': 'inactive_or_expired'}

        session = process_db.get_session()
        try:
            from database.models import GroupSettings, SuperGroup

            process_logger.info(f"🔍 Запрос групп для аккаунта ID={account.id}, телефон={account.phone_number}")

            enabled_groups = session.query(GroupSettings).filter(
                GroupSettings.account_id == account.id,
                GroupSettings.is_enabled == True
            ).all()

            process_logger.info(f"📋 Найдено обычных групп: {len(enabled_groups)}")

            enabled_super_groups = session.query(SuperGroup).filter(
                SuperGroup.account_id == account.id,
                SuperGroup.is_enabled == True
            ).all()

            process_logger.info(f"🏗️ Найдено супер групп (топиков): {len(enabled_super_groups)}")

            for i, sg in enumerate(enabled_super_groups):
                process_logger.info(f"   Супер группа {i+1}: {sg.base_group_name} | {sg.topic_name} (ID: {sg.base_group_id}_{sg.topic_id}, enabled={sg.is_enabled})")
                process_logger.info(f"      Сообщение: {'✉️ есть' if sg.custom_message else '📝 нет'}")

            process_logger.info(f"📊 Итого: {len(enabled_groups)} обычных групп + {len(enabled_super_groups)} супер групп для аккаунта {account.phone_number}")

        finally:
            process_db.close_session(session)

        if not enabled_groups and not enabled_super_groups:
            process_logger.warning(f"Нет выбранных групп или супер групп для аккаунта {account.phone_number}")
            return {'success': False, 'reason': 'no_groups'}

        client = await _create_telegram_client(account, process_logger)
        if not client:
            return {'success': False, 'reason': 'client_failed'}

        successful_sends = 0
        skipped_groups = 0
        failed_sends = 0

        try:
            batch_size = getattr(account, 'batch_size', 10)

            ready_groups = []
            for group_settings in enabled_groups:
                group_id = group_settings.group_id

                if not group_settings.custom_message and not account.default_message:
                    process_logger.info(f"Пропуск группы {group_id} - не задано сообщение")
                    skipped_groups += 1
                    continue

                if group_settings and group_settings.last_message_time:
                    interval_minutes = group_settings.custom_interval if group_settings.custom_interval else account.message_interval
                    next_send_time = group_settings.last_message_time + timedelta(minutes=interval_minutes)
                    current_time = datetime.now()

                    if current_time < next_send_time:
                        remaining_seconds = (next_send_time - current_time).total_seconds()
                        remaining_minutes = remaining_seconds / 60
                        process_logger.info(f"⏰ Cooldown активен для группы {group_id}. Интервал: {interval_minutes} мин, осталось ждать: {remaining_minutes:.1f} мин")
                        skipped_groups += 1
                        continue

                ready_groups.append(('group', group_settings))

            for super_group in enabled_super_groups:
                if not super_group.custom_message and not account.default_message:
                    process_logger.info(f"Пропуск супер группы {super_group.base_group_name} | {super_group.topic_name} - не задано сообщение")
                    skipped_groups += 1
                    continue

                if super_group.last_message_time:
                    interval_minutes = super_group.custom_interval if super_group.custom_interval else account.message_interval
                    next_send_time = super_group.last_message_time + timedelta(minutes=interval_minutes)
                    current_time = datetime.now()

                    if current_time < next_send_time:
                        remaining_seconds = (next_send_time - current_time).total_seconds()
                        remaining_minutes = remaining_seconds / 60
                        process_logger.info(f"⏰ Cooldown активен для супер группы {super_group.base_group_name} | {super_group.topic_name}. Интервал: {interval_minutes} мин, осталось ждать: {remaining_minutes:.1f} мин")
                        skipped_groups += 1
                        continue

                ready_groups.append(('super_group', super_group))

            if not ready_groups:
                process_logger.info(f"Нет групп готовых к отправке для аккаунта {account.phone_number}")
                return {
                    'success': True,
                    'account_phone': account.phone_number,
                    'successful_sends': 0,
                    'skipped_groups': skipped_groups,
                    'failed_sends': 0
                }

            process_logger.info(f"📦 Обработка {len(ready_groups)} готовых групп пакетами по {batch_size}")

            for i in range(0, len(ready_groups), batch_size):
                batch = ready_groups[i:i + batch_size]
                process_logger.info(f"🚀 Обработка пакета {i//batch_size + 1}: группы {i+1}-{min(i+batch_size, len(ready_groups))}")

                tasks = []
                for group_type, group_settings in batch:
                    if group_type == 'group':
                        if group_settings.custom_message:
                            message_to_send = group_settings.custom_message
                            process_logger.debug(f"📝 Используем индивидуальное сообщение для группы {group_settings.group_id}")
                        else:
                            message_to_send = account.default_message
                            process_logger.debug(f"📝 Используем общее сообщение для группы {group_settings.group_id}")

                            if group_settings.escrow_username and message_to_send:
                                message_to_send = message_to_send + f'\n\n<b>escrow/гарант : {group_settings.escrow_username}</b>'
                                process_logger.debug(f"➕ Добавлен гарант к общему сообщению: {group_settings.escrow_username}")

                        if hasattr(account, 'cyrillic_substitution') and account.cyrillic_substitution:
                            original_message = message_to_send
                            message_to_send = apply_cyrillic_substitution(message_to_send, enabled=True, rate=0.3)
                            process_logger.debug(f"🔄 Кириллическая замена: '{original_message}' -> '{message_to_send}'")

                        task = _send_message_to_group_batch(
                            client, account, group_settings.group_id, message_to_send,
                            group_settings, process_logger, process_db
                        )
                    else:
                        if group_settings.custom_message:
                            message_to_send = group_settings.custom_message
                            process_logger.debug(f"📝 Используем индивидуальное сообщение для темы {group_settings.base_group_id}_{group_settings.topic_id}")
                        else:
                            message_to_send = account.default_message
                            process_logger.debug(f"📝 Используем общее сообщение для темы {group_settings.base_group_id}_{group_settings.topic_id}")

                            if hasattr(group_settings, 'escrow_username') and group_settings.escrow_username and message_to_send:
                                message_to_send = message_to_send + f'\n\n<b>escrow/гарант : {group_settings.escrow_username}</b>'
                                process_logger.debug(f"➕ Добавлен гарант к общему сообщению темы: {group_settings.escrow_username}")

                        if hasattr(account, 'cyrillic_substitution') and account.cyrillic_substitution:
                            original_message = message_to_send
                            message_to_send = apply_cyrillic_substitution(message_to_send, enabled=True, rate=0.3)
                            process_logger.debug(f"🔄 Кириллическая замена: '{original_message}' -> '{message_to_send}'")

                        task = _send_message_to_super_group_batch(
                            client, account, group_settings.base_group_id, group_settings.topic_id, message_to_send,
                            group_settings, process_logger, process_db
                        )

                    tasks.append(task)

                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                for j, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        process_logger.error(f"❌ Ошибка в задаче пакета: {result}")
                        failed_sends += 1
                    elif result:
                        successful_sends += 1
                    else:
                        failed_sends += 1

                if i + batch_size < len(ready_groups):
                    await asyncio.sleep(1)

            process_logger.info(f"✅ Завершена обработка аккаунта {account.phone_number}: {successful_sends} успешно, {failed_sends} неудачно, {skipped_groups} пропущено")

            return {
                'success': True,
                'account_phone': account.phone_number,
                'successful_sends': successful_sends,
                'skipped_groups': skipped_groups,
                'failed_sends': failed_sends
            }

        finally:
            await client.disconnect()

    except Exception as e:
        process_logger.error(f"❌ Общая ошибка обработки аккаунта {account.phone_number}: {e}")
        return {'success': False, 'error': str(e)}

async def _create_telegram_client(account, process_logger):
    try:
        proxy_config = None
        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy and proxy.is_working:
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)
            else:
                working_proxies = get_working_proxies()
                if working_proxies:
                    new_proxy = random.choice(working_proxies)
                    proxy_data = {
                        'host': new_proxy.host,
                        'port': new_proxy.port,
                        'username': new_proxy.username,
                        'password': new_proxy.password,
                        'proxy_type': new_proxy.proxy_type
                    }
                    proxy_config = get_telethon_proxy_config(proxy_data)

        client = TelegramClient(
            StringSession(account.session_string),
            account.api_id,
            account.api_hash,
            proxy=proxy_config,
            timeout=30
        )

        await client.connect()

        if not await client.is_user_authorized():
            process_logger.error(f"Аккаунт {account.phone_number} не авторизован")
            return None

        process_logger.info(f"✅ Клиент создан для аккаунта {account.phone_number}")
        return client

    except Exception as e:
        process_logger.error(f"Ошибка создания клиента для аккаунта {account.phone_number}: {e}")
        return None

async def _send_message_to_group_batch(client, account, group_id, message_text, group_settings, process_logger, process_db):
    try:
        process_logger.info(f"📤 Пакетная отправка сообщения в группу {group_id}")

        try:
            from utils.group_id_helper import try_get_entity_by_id, debug_list_all_dialogs

            entity, actual_id = await try_get_entity_by_id(client, str(group_id), process_logger)

            if not entity:
                process_logger.error(f"❌ Группа {group_id} не найдена всеми доступными способами")

                if group_id in ['1447831096', '1526626715']:
                    process_logger.info(f"🔍 === ДОПОЛНИТЕЛЬНАЯ ДИАГНОСТИКА ДЛЯ ГРУППЫ {group_id} ===")
                    await debug_list_all_dialogs(client, process_logger)

                return False

        except Exception as e:
            error_msg = str(e)
            if "invalid peer" in error_msg.lower() or "peer" in error_msg.lower():
                process_logger.warning(f"🔗 Неверный Peer ID для группы {group_id}: {e}")
                return False
            process_logger.error(f"❌ Критическая ошибка получения сущности группы {group_id}: {e}")
            return False

        media_data = None
        media_type = None

        if group_settings and not getattr(group_settings, 'media_blocked', False):
            if group_settings.custom_photo:
                media_data = group_settings.custom_photo
                media_type = 'photo'
            elif group_settings.custom_gif:
                media_data = group_settings.custom_gif
                media_type = 'gif'
            elif group_settings.custom_video:
                media_data = group_settings.custom_video
                media_type = 'video'
            elif account.default_photo:
                media_data = account.default_photo
                media_type = 'photo'
            elif account.default_gif:
                media_data = account.default_gif
                media_type = 'gif'
            elif account.default_video:
                media_data = account.default_video
                media_type = 'video'

        try:
            sent_successfully = False

            if media_data and media_type and not getattr(group_settings, 'media_blocked', False):
                try:
                    if media_type == "photo":
                        file_name = "image.jpg"
                    elif media_type == "gif":
                        file_name = "animation.gif"
                    elif media_type == "video":
                        file_name = "video.mp4"
                    else:
                        file_name = "file.bin"

                    file_obj = io.BytesIO(media_data)
                    file_obj.name = file_name

                    custom_message = convert_html_to_custom_format(message_text)
                    parsed_text, entities = CustomParseMode('html').parse(custom_message)

                    await client.send_file(
                        entity,
                        file_obj,
                        caption=parsed_text,
                        formatting_entities=entities
                    )
                    sent_successfully = True

                except RPCError as media_error:
                    if any(forbidden in str(media_error) for forbidden in [
                        'CHAT_SEND_PHOTOS_FORBIDDEN', 'CHAT_SEND_MEDIA_FORBIDDEN', 'CHAT_SEND_VIDEOS_FORBIDDEN',
                        'PHOTO_EXT_INVALID', 'MEDIA_EMPTY', 'CHAT_RESTRICTED', 'Failure while processing image'
                    ]):
                        process_logger.warning(f"📵 Медиа запрещено в группе {group_id}: {media_error}. Отправляем только текст")

                        session = process_db.get_session()
                        try:
                            settings = session.query(GroupSettings).filter(
                                GroupSettings.account_id == account.id,
                                GroupSettings.group_id == group_id
                            ).first()
                            if settings:
                                settings.media_blocked = True
                                session.commit()
                        except:
                            pass
                        finally:
                            process_db.close_session(session)

                        sent_successfully = False
                    else:
                        raise media_error

                except Exception as other_media_error:
                    process_logger.warning(f"📵 Неожиданная ошибка медиа в группе {group_id}: {other_media_error}. Отправляем только текст")
                    sent_successfully = False

            if not sent_successfully:
                process_logger.info(f"📝 Fallback на текст для группы {group_id}. Исходное сообщение: '{message_text}'")

                custom_message = convert_html_to_custom_format(message_text)
                parsed_text, entities = CustomParseMode('html').parse(custom_message)

                process_logger.info(f"🔧 После конвертации: текст='{parsed_text}', entities={len(entities)}")

                await client.send_message(entity, parsed_text, formatting_entities=entities)
                process_logger.info(f"✅ Текстовое сообщение с форматированием отправлено в группу {group_id}")

            if group_settings:
                session = process_db.get_session()
                try:
                    settings = session.query(GroupSettings).filter(
                        GroupSettings.account_id == account.id,
                        GroupSettings.group_id == group_id
                    ).first()
                    if settings:
                        settings.last_message_time = datetime.now()
                        session.commit()
                finally:
                    process_db.close_session(session)

            try:
                log_message(account.id, group_id, message_text, media_data is not None, 'sent')
            except Exception as log_error:
                process_logger.error(f"❌ Ошибка логирования отправки в группу {group_id}: {log_error}")

            return True

        except FloodWaitError as e:
            process_logger.warning(f"⏳ FloodWait {e.seconds} секунд для группы {group_id}")
            return False

        except (UserBannedInChannelError, ChatWriteForbiddenError, UserNotParticipantError) as e:
            process_logger.warning(f"🚫 Аккаунт ограничен в группе {group_id}: {e}")
            return False

        except Exception as e:
            error_msg = str(e)
            if "invalid peer" in error_msg.lower() or "peer" in error_msg.lower():
                process_logger.warning(f"🔗 Неверный Peer ID для группы {group_id}: {e}")
                return False

            process_logger.error(f"❌ Ошибка отправки в группу {group_id}: {e}")

            try:
                log_message(account.id, group_id, message_text, media_data is not None, 'failed', str(e))
            except Exception as log_error:
                process_logger.error(f"❌ Ошибка логирования неудачи в группу {group_id}: {log_error}")

            return False

    except Exception as e:
        error_msg = str(e)
        if "invalid peer" in error_msg.lower() or "peer" in error_msg.lower():
            process_logger.warning(f"🔗 Неверный Peer ID для группы {group_id} (общий блок): {e}")
            return False
        process_logger.error(f"❌ Общая ошибка пакетной отправки сообщения в группу {group_id}: {e}")
        return False

async def _send_message_to_super_group_batch(client, account, group_id, topic_id, message_text, super_group_settings, process_logger, process_db):
    try:
        process_logger.info(f"📤 Пакетная отправка сообщения в супер группу {group_id} (тема {topic_id})")

        try:
            from utils.group_id_helper import try_get_entity_by_id, debug_list_all_dialogs

            entity, actual_id = await try_get_entity_by_id(client, str(group_id), process_logger)

            if not entity:
                process_logger.error(f"❌ Супер группа {group_id} не найдена")
                return False

        except Exception as e:
            process_logger.error(f"❌ Критическая ошибка получения сущности супер группы {group_id}: {e}")
            return False

        media_data = None
        media_type = None

        if super_group_settings and not getattr(super_group_settings, 'media_blocked', False):
            if super_group_settings.custom_photo:
                media_data = super_group_settings.custom_photo
                media_type = 'photo'
            elif super_group_settings.custom_gif:
                media_data = super_group_settings.custom_gif
                media_type = 'gif'
            elif super_group_settings.custom_video:
                media_data = super_group_settings.custom_video
                media_type = 'video'
            elif account.default_photo:
                media_data = account.default_photo
                media_type = 'photo'
            elif account.default_gif:
                media_data = account.default_gif
                media_type = 'gif'
            elif account.default_video:
                media_data = account.default_video
                media_type = 'video'

        try:
            sent_successfully = False

            if media_data and media_type and not getattr(super_group_settings, 'media_blocked', False):
                try:
                    if media_type == "photo":
                        file_name = "image.jpg"
                    elif media_type == "gif":
                        file_name = "animation.gif"
                    elif media_type == "video":
                        file_name = "video.mp4"
                    else:
                        file_name = "file.bin"

                    file_obj = io.BytesIO(media_data)
                    file_obj.name = file_name

                    custom_message = convert_html_to_custom_format(message_text)
                    parsed_text, entities = CustomParseMode('html').parse(custom_message)

                    await client.send_file(
                        entity,
                        file_obj,
                        caption=parsed_text,
                        formatting_entities=entities,
                        reply_to=int(topic_id) if topic_id else None
                    )
                    sent_successfully = True

                except RPCError as media_error:
                    if any(forbidden in str(media_error) for forbidden in [
                        'CHAT_SEND_PHOTOS_FORBIDDEN', 'CHAT_SEND_MEDIA_FORBIDDEN', 'CHAT_SEND_VIDEOS_FORBIDDEN',
                        'PHOTO_EXT_INVALID', 'MEDIA_EMPTY', 'CHAT_RESTRICTED', 'Failure while processing image'
                    ]):
                        process_logger.warning(f"📵 Медиа запрещено в супер группе {group_id}: {media_error}. Отправляем только текст")

                        session = process_db.get_session()
                        try:
                            from database.models import SuperGroup
                            settings = session.query(SuperGroup).filter(
                                SuperGroup.account_id == account.id,
                                SuperGroup.base_group_id == str(group_id),
                                SuperGroup.topic_id == str(topic_id)
                            ).first()
                            if settings:
                                settings.media_blocked = True
                                session.commit()
                                process_logger.info(f"🚫 Супер группа {group_id} помечена как заблокированная для медиа")
                        except Exception as e:
                            process_logger.warning(f"⚠️ Не удалось пометить супер группу как media_blocked: {e}")
                        finally:
                            process_db.close_session(session)

                        sent_successfully = False
                    else:
                        raise media_error

                except Exception as other_media_error:
                    process_logger.warning(f"📵 Неожиданная ошибка медиа в супер группе {group_id}: {other_media_error}. Отправляем только текст")
                    sent_successfully = False

            if not sent_successfully:
                custom_message = convert_html_to_custom_format(message_text)
                parsed_text, entities = CustomParseMode('html').parse(custom_message)

                await client.send_message(
                    entity,
                    parsed_text,
                    formatting_entities=entities,
                    reply_to=int(topic_id) if topic_id else None
                )

            if super_group_settings:
                session = process_db.get_session()
                try:
                    from database.models import SuperGroup
                    settings = session.query(SuperGroup).filter(
                        SuperGroup.id == super_group_settings.id
                    ).first()
                    if settings:
                        settings.last_message_time = datetime.now()
                        session.commit()
                finally:
                    process_db.close_session(session)

            try:
                log_message(account.id, f"{group_id}_{topic_id}", message_text, media_data is not None, 'sent')
            except Exception as log_error:
                process_logger.error(f"❌ Ошибка логирования отправки в супер группу {group_id}: {log_error}")

            return True

        except FloodWaitError as e:
            process_logger.warning(f"⏳ FloodWait {e.seconds} секунд для супер группы {group_id}")
            return False

        except (UserBannedInChannelError, ChatWriteForbiddenError, UserNotParticipantError) as e:
            process_logger.warning(f"🚫 Аккаунт ограничен в супер группе {group_id}: {e}")
            return False

        except Exception as e:
            process_logger.error(f"❌ Ошибка отправки в супер группу {group_id}: {e}")

            try:
                log_message(account.id, f"{group_id}_{topic_id}", message_text, media_data is not None, 'failed', str(e))
            except Exception as log_error:
                process_logger.error(f"❌ Ошибка логирования неудачи в супер группу {group_id}: {log_error}")

            return False

    except Exception as e:
        process_logger.error(f"❌ Общая ошибка пакетной отправки сообщения в супер группу {group_id}: {e}")
        return False

async def _send_message_to_group_process(client, account, group_id, message_text, group_settings, process_logger, process_db):
    try:
        process_logger.info(f"📤 Отправка сообщения в группу {group_id}")

        if group_settings and group_settings.last_message_time:
            interval_minutes = group_settings.custom_interval if group_settings.custom_interval else account.message_interval
            next_send_time = group_settings.last_message_time + timedelta(minutes=interval_minutes)
            current_time = datetime.now()

            if current_time < next_send_time:
                remaining_seconds = (next_send_time - current_time).total_seconds()
                remaining_minutes = remaining_seconds / 60
                process_logger.info(f"⏰ Cooldown активен для группы {group_id}. Интервал: {interval_minutes} мин, осталось ждать: {remaining_minutes:.1f} мин ({remaining_seconds:.0f} сек)")
                return False

        try:
            from utils.group_id_helper import try_get_entity_by_id, debug_list_all_dialogs

            entity, actual_id = await try_get_entity_by_id(client, str(group_id), process_logger)

            if not entity:
                process_logger.error(f"❌ Группа {group_id} не найдена всеми доступными способами")

                if group_id in ['1447831096', '1526626715']:
                    process_logger.info(f"🔍 === ДОПОЛНИТЕЛЬНАЯ ДИАГНОСТИКА ДЛЯ ГРУППЫ {group_id} ===")
                    await debug_list_all_dialogs(client, process_logger)

                return False

            process_logger.info(f"✅ Группа найдена: {group_id} -> {getattr(entity, 'title', 'Unknown')} (Actual ID: {actual_id})")

        except Exception as e:
            process_logger.error(f"❌ Критическая ошибка получения сущности группы {group_id}: {e}")
            return False

        media_data = None
        media_type = None

        if group_settings and not getattr(group_settings, 'media_blocked', False):
            if group_settings.custom_photo:
                media_data = group_settings.custom_photo
                media_type = 'photo'
            elif group_settings.custom_gif:
                media_data = group_settings.custom_gif
                media_type = 'gif'
            elif group_settings.custom_video:
                media_data = group_settings.custom_video
                media_type = 'video'
            elif account.default_photo:
                media_data = account.default_photo
                media_type = 'photo'
            elif account.default_gif:
                media_data = account.default_gif
                media_type = 'gif'
            elif account.default_video:
                media_data = account.default_video
                media_type = 'video'

        try:
            sent_successfully = False

            if media_data and media_type and not getattr(group_settings, 'media_blocked', False):
                try:
                    if media_type == "photo":
                        file_name = "image.jpg"
                    elif media_type == "gif":
                        file_name = "animation.gif"
                    elif media_type == "video":
                        file_name = "video.mp4"
                    else:
                        file_name = "file.bin"

                    file_obj = io.BytesIO(media_data)
                    file_obj.name = file_name

                    custom_message = convert_html_to_custom_format(message_text)
                    parsed_text, entities = CustomParseMode('html').parse(custom_message)

                    await client.send_file(
                        entity,
                        file_obj,
                        caption=parsed_text,
                        formatting_entities=entities
                    )
                    sent_successfully = True
                    process_logger.info(f"✅ Сообщение с медиа отправлено в группу {group_id}")

                except RPCError as media_error:
                    if any(forbidden in str(media_error) for forbidden in [
                        'CHAT_SEND_PHOTOS_FORBIDDEN', 'CHAT_SEND_MEDIA_FORBIDDEN', 'CHAT_SEND_VIDEOS_FORBIDDEN',
                        'PHOTO_EXT_INVALID', 'MEDIA_EMPTY', 'CHAT_RESTRICTED', 'Failure while processing image'
                    ]):
                        process_logger.warning(f"📵 Медиа запрещено в группе {group_id}: {media_error}. Отправляем только текст")

                        session = process_db.get_session()
                        try:
                            settings = session.query(GroupSettings).filter(
                                GroupSettings.account_id == account.id,
                                GroupSettings.group_id == group_id
                            ).first()
                            if settings:
                                settings.media_blocked = True
                                session.commit()
                        except:
                            pass
                        finally:
                            process_db.close_session(session)

                        sent_successfully = False
                    else:
                        raise media_error

                except Exception as other_media_error:
                    process_logger.warning(f"📵 Неожиданная ошибка медиа в группе {group_id}: {other_media_error}. Отправляем только текст")
                    sent_successfully = False

            if not sent_successfully:
                process_logger.info(f"📝 Fallback на текст для группы {group_id}. Исходное сообщение: '{message_text}'")

                custom_message = convert_html_to_custom_format(message_text)
                parsed_text, entities = CustomParseMode('html').parse(custom_message)

                process_logger.info(f"🔧 После конвертации: текст='{parsed_text}', entities={len(entities)}")

                await client.send_message(entity, parsed_text, formatting_entities=entities)
                process_logger.info(f"✅ Текстовое сообщение с форматированием отправлено в группу {group_id}")

            if group_settings:
                session = process_db.get_session()
                try:
                    settings = session.query(GroupSettings).filter(
                        GroupSettings.account_id == account.id,
                        GroupSettings.group_id == group_id
                    ).first()
                    if settings:
                        settings.last_message_time = datetime.now()
                        session.commit()
                        process_logger.info(f"🕐 Обновлено время последней отправки для группы {group_id}: {settings.last_message_time}")
                finally:
                    process_db.close_session(session)

            try:
                log_message(account.id, group_id, message_text, media_data is not None, 'sent')
            except Exception as log_error:
                process_logger.error(f"❌ Ошибка логирования отправки в группу {group_id}: {log_error}")

            return True

        except FloodWaitError as e:
            process_logger.warning(f"⏳ FloodWait {e.seconds} секунд для группы {group_id}")
            return False

        except (UserBannedInChannelError, ChatWriteForbiddenError, UserNotParticipantError) as e:
            process_logger.warning(f"🚫 Аккаунт ограничен в группе {group_id}: {e}")
            return False

        except Exception as e:
            process_logger.error(f"❌ Ошибка отправки в группу {group_id}: {e}")

            try:
                log_message(account.id, group_id, message_text, media_data is not None, 'failed', str(e))
            except Exception as log_error:
                process_logger.error(f"❌ Ошибка логирования неудачи в группу {group_id}: {log_error}")

            return False

    except Exception as e:
        process_logger.error(f"❌ Общая ошибка отправки сообщения в группу {group_id}: {e}")
        return False

class MessageSender:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.active_processes = {}
        self.flood_wait_accounts = {}

        self.batch_size = int(self.config.get('BATCH_SIZE', 'batch_size', fallback='10'))

        if sys.platform.startswith('win'):
            multiprocessing.set_start_method('spawn', force=True)

        logger.info(f"🚀 MessageSender инициализирован с мультипроцессингом, точными интервалами и batch_size={self.batch_size}")

    def _convert_account_to_dict(self, account: Account) -> dict:
        return {
            'id': account.id,
            'user_id': account.user_id,
            'phone_number': account.phone_number,
            'session_string': account.session_string,
            'is_active': account.is_active,
            'subscription_minutes': account.subscription_minutes,
            'proxy_id': account.proxy_id,
            'api_id': account.api_id,
            'api_hash': account.api_hash,
            'default_message': account.default_message,
            'message_interval': account.message_interval,
            'send_delay': getattr(account, 'send_delay', 2),
            'default_photo': account.default_photo,
            'default_gif': account.default_gif,
            'default_video': account.default_video,
            'cyrillic_substitution': getattr(account, 'cyrillic_substitution', False),
            'autoresponder_enabled': getattr(account, 'autoresponder_enabled', False),
            'autoresponder_first_message': getattr(account, 'autoresponder_first_message', None),
            'autoresponder_away_message': getattr(account, 'autoresponder_away_message', None),
            'autoresponder_away_minutes': getattr(account, 'autoresponder_away_minutes', 30),
            'batch_size': self.batch_size
        }

    async def broadcast_for_account(self, account: Account):
        try:
            logger.info(f"🚀 Запуск процесса рассылки для аккаунта {account.phone_number}")

            account_data = self._convert_account_to_dict(account)

            process = multiprocessing.Process(
                target=process_account_broadcast,
                args=(account_data,),
                name=f"Account-{account.phone_number}"
            )

            process.start()
            self.active_processes[account.id] = process

            logger.info(f"✅ Процесс запущен для аккаунта {account.phone_number} (PID: {process.pid})")

            return process

        except Exception as e:
            logger.error(f"❌ Ошибка запуска процесса для аккаунта {account.phone_number}: {e}")
            return None

    async def run_broadcast_cycle(self):
        try:
            active_accounts = get_active_accounts()

            if not active_accounts:
                logger.info("Нет активных аккаунтов для рассылки")
                return

            logger.info(f"🚀 Запуск мультипроцессинга для {len(active_accounts)} аккаунтов с точными интервалами")

            await self.cleanup_finished_processes()

            new_processes = []
            for account in active_accounts:
                if account.id not in self.active_processes:
                    process = await self.broadcast_for_account(account)
                    if process:
                        new_processes.append(process)
                else:
                    existing_process = self.active_processes[account.id]
                    if not existing_process.is_alive():
                        logger.info(f"🔄 Перезапуск завершенного процесса для аккаунта {account.phone_number}")
                        del self.active_processes[account.id]
                        process = await self.broadcast_for_account(account)
                        if process:
                            new_processes.append(process)

            if new_processes:
                logger.info(f"📊 Запущено {len(new_processes)} новых процессов, всего активных: {len(self.active_processes)}")

            logger.info(f"✅ Все процессы запущены! Активных процессов: {len(self.active_processes)}")

        except Exception as e:
            logger.error(f"❌ Ошибка в цикле мультипроцессинга: {e}")

    async def cleanup_finished_processes(self):
        try:
            finished_accounts = []

            for account_id, process in list(self.active_processes.items()):
                if not process.is_alive():
                    exit_code = process.exitcode
                    if exit_code == 0:
                        logger.info(f"✅ Процесс аккаунта ID-{account_id} завершился успешно")
                    else:
                        logger.warning(f"⚠️ Процесс аккаунта ID-{account_id} завершился с кодом {exit_code}")

                    process.join(timeout=1)
                    finished_accounts.append(account_id)

            for account_id in finished_accounts:
                del self.active_processes[account_id]

            if finished_accounts:
                logger.info(f"🧹 Очищено {len(finished_accounts)} завершенных процессов")

        except Exception as e:
            logger.error(f"❌ Ошибка очистки процессов: {e}")

    async def stop_all_processes(self):
        try:
            logger.info(f"🛑 Остановка {len(self.active_processes)} активных процессов...")

            for account_id, process in list(self.active_processes.items()):
                try:
                    if process.is_alive():
                        logger.info(f"🛑 Остановка процесса аккаунта ID-{account_id} (PID: {process.pid})")
                        process.terminate()
                        process.join(timeout=5)

                        if process.is_alive():
                            logger.warning(f"⚡ Принудительное завершение процесса ID-{account_id}")
                            process.kill()
                            process.join(timeout=2)

                except Exception as e:
                    logger.error(f"❌ Ошибка остановки процесса ID-{account_id}: {e}")

                if account_id in self.active_processes:
                    del self.active_processes[account_id]

            logger.info("✅ Все процессы остановлены")

        except Exception as e:
            logger.error(f"❌ Ошибка остановки процессов: {e}")

    async def get_process_stats(self):
        try:
            alive_count = 0
            dead_count = 0

            for account_id, process in self.active_processes.items():
                if process.is_alive():
                    alive_count += 1
                else:
                    dead_count += 1

            return {
                'total_processes': len(self.active_processes),
                'alive_processes': alive_count,
                'dead_processes': dead_count
            }

        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики процессов: {e}")
            return {'total_processes': 0, 'alive_processes': 0, 'dead_processes': 0}

    async def send_message_to_group(self, account: Account, group_id: str, message_text: str,
                                  media_data: Optional[bytes] = None, media_type: str = None) -> bool:
        logger.warning("⚠️ Используется устаревший метод send_message_to_group. Рекомендуется использовать run_broadcast_cycle()")

        process = await self.broadcast_for_account(account)
        if process:
            process.join()
            return process.exitcode == 0
        return False

    async def cleanup_clients(self):
        await self.stop_all_processes()

message_sender = MessageSender()

async def start_background_broadcasting():
    logger.info("🚀 Запуск фоновой рассылки с мультипроцессингом и точными интервалами...")

    while True:
        try:
            await message_sender.run_broadcast_cycle()

            stats = await message_sender.get_process_stats()
            logger.info(f"📊 Статистика процессов: {stats['alive_processes']} активных, {stats['dead_processes']} завершенных")

            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"❌ Ошибка в фоновой рассылке: {e}")
            await asyncio.sleep(60)

async def stop_background_broadcasting():
    logger.info("🛑 Остановка фоновой рассылки...")
    await message_sender.stop_all_processes()
