import os
import asyncio
import logging
import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError, PhoneCodeExpiredError, FloodWaitError, AuthKeyUnregisteredError, UserDeactivatedError, PhoneNumberBannedError
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.photos import UpdateProfilePhotoRequest
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantRequest
from telethon.tl.types import ChannelParticipantCreator, ChannelParticipantAdmin, ChannelParticipant, ChatBannedRights, ForumTopicDeleted
import configparser
import random
from aiogram.methods import EditMessageMedia
from aiogram.exceptions import TelegramBadRequest
from utils.api_manager import get_api_credentials_with_rotation, log_code_sending, mark_api_failed

from database.database import (
    create_account, get_user_accounts, create_proxy, get_proxy_by_id,
    get_active_accounts, update_account_subscription, get_working_proxies
)
from utils.proxy_validator import proxy_validator, validate_proxy_for_telethon, get_telethon_proxy_config
from keyboards.keyboards import (
    get_account_actions_keyboard, get_account_settings_keyboard,
    get_media_types_keyboard, get_main_menu_keyboard, get_back_to_main_keyboard,
    get_account_list_keyboard, get_account_management_keyboard, get_no_accounts_keyboard,
    get_account_retry_keyboard, get_subscription_periods_keyboard, get_insufficient_balance_keyboard,
    get_delete_account_keyboard, get_group_settings_keyboard,
    get_account_profile_keyboard, get_group_back_keyboard, get_slowmode_warning_keyboard,
    get_common_settings_keyboard, get_account_templates_keyboard, get_template_actions_keyboard,
    get_template_confirm_keyboard, get_account_extra_functions_keyboard, get_groups_selection_keyboard_v2,
    get_group_interval_keyboard, get_individual_group_settings_keyboard,
    get_super_groups_main_keyboard, get_super_groups_list_keyboard, get_super_group_settings_keyboard,
    get_groups_with_topics_keyboard, get_topics_list_keyboard,
    get_super_groups_topics_keyboard, get_topic_settings_keyboard, get_message_edit_cancel_keyboard,
    get_invalid_session_keyboard, get_account_login_method_keyboard, get_qr_login_keyboard
)
from database.models import MessageLog, GroupSettings, AccountTemplate, GroupTemplate, SuperGroup, SelectedTopics

logger = logging.getLogger(__name__)
router = Router()

config = configparser.ConfigParser()
config.read('config.ini')

CACHED_IMAGES = {}

def format_minutes_to_readable(minutes):
    if minutes <= 0:
        return "0 минут"

    days = minutes // (24 * 60)
    hours = (minutes % (24 * 60)) // 60
    remaining_minutes = minutes % 60

    parts = []
    if days > 0:
        parts.append(f"{days} дн")
    if hours > 0:
        parts.append(f"{hours} ч")
    if remaining_minutes > 0:
        parts.append(f"{remaining_minutes} мин")

    return " ".join(parts)

async def get_account_groups(account):
    try:
        proxy_config = None
        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)

        client = TelegramClient(
            StringSession(account.session_string),
            account.api_id,
            account.api_hash,
            proxy=proxy_config,
            timeout=10,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30"
        )

        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            return []

        all_dialogs = []
        async for dialog in client.iter_dialogs():
            all_dialogs.append(dialog)

        writable_groups = []
        me = await client.get_me()

        if me is None:
            logger.warning(f"Не удалось получить информацию об аккаунте {account.phone_number}")
            await client.disconnect()
            return []

        logger.info(f"Найдено {len(all_dialogs)} диалогов для аккаунта {account.phone_number}")

        for dialog in all_dialogs:
            try:
                entity = dialog.entity

                is_group = getattr(entity, 'megagroup', False) or dialog.is_group
                is_channel = getattr(entity, 'broadcast', False) or dialog.is_channel
                is_supergroup = getattr(entity, 'megagroup', False)
                is_bot = getattr(entity, 'bot', False)

                logger.debug(f"Диалог: {dialog.title} (ID: {entity.id})")
                logger.debug(f"  - группа: {is_group}, канал: {is_channel}, супергруппа: {is_supergroup}, бот: {is_bot}")
                logger.debug(f"  - megagroup: {getattr(entity, 'megagroup', 'N/A')}, broadcast: {getattr(entity, 'broadcast', 'N/A')}")

                if is_bot:
                    logger.info(f"Пропущен бот: {dialog.title} (ID: {entity.id})")
                    continue

                if is_channel and getattr(entity, 'broadcast', False) and not getattr(entity, 'megagroup', False):
                    logger.info(f"Пропущен канал: {dialog.title} (ID: {entity.id})")
                    continue

                if is_group or is_supergroup or (is_channel and getattr(entity, 'megagroup', False)):
                    can_write = False

                    try:
                        participant = await client(GetParticipantRequest(
                            channel=entity,
                            participant=me
                        ))
                        participant = participant.participant

                        if isinstance(participant, (ChannelParticipantCreator, ChannelParticipantAdmin)):
                            can_write = True
                        elif isinstance(participant, ChannelParticipant):
                            banned_rights = getattr(participant, 'banned_rights', None)
                            if banned_rights and isinstance(banned_rights, ChatBannedRights):
                                if banned_rights.send_messages is None:
                                    can_write = True
                                else:
                                    can_write = not banned_rights.send_messages
                            else:
                                can_write = True
                        else:
                            can_write = True

                    except Exception as e:
                        logger.warning(f"Не удалось получить информацию о участнике для {dialog.title}: {e}")

                        if is_group or is_supergroup:
                            can_write = True
                        else:
                            can_write = True
                            logger.info(f"Предполагается доступным для {dialog.title} (не удалось определить права)")

                    if can_write:
                        has_forum = False
                        has_topics = False

                        try:
                            from telethon.tl.functions.channels import GetForumTopicsRequest
                            from telethon.tl.types import Channel

                            if isinstance(entity, Channel):
                                has_forum = getattr(entity, 'forum', False)
                                is_supergroup = getattr(entity, 'megagroup', False)

                                if has_forum:
                                    try:
                                        forum_topics = await client(GetForumTopicsRequest(
                                            channel=entity,
                                            offset_date=None,
                                            offset_id=0,
                                            offset_topic=0,
                                            limit=100
                                        ))

                                        if len(forum_topics.topics) > 0:
                                            has_topics = True
                                            logger.info(f"Пропущена группа с темами: {dialog.title} (ID: {entity.id}, Тем: {len(forum_topics.topics)})")

                                    except Exception as e:
                                        logger.debug(f"Не удалось получить темы для группы {dialog.title}: {e}")
                                        has_topics = True
                                        logger.info(f"Пропущена группа с форумом (предполагаемые темы): {dialog.title} (ID: {entity.id})")

                        except Exception as e:
                            logger.debug(f"Ошибка при проверке форума для группы {dialog.title}: {e}")

                        if has_topics:
                            logger.info(f"Пропущена группа с темами: {dialog.title} (ID: {entity.id})")
                            continue

                        from utils.group_id_helper import get_correct_group_id_for_storage
                        storage_id = get_correct_group_id_for_storage(entity)

                        from database.database import db
                        temp_session = db.get_session()
                        try:
                            from database.models import SuperGroup
                            existing_super_group = temp_session.query(SuperGroup).filter(
                                SuperGroup.base_group_id == str(storage_id)
                            ).first()

                            if existing_super_group:
                                logger.info(f"Пропущена группа (найдена в SuperGroup): {dialog.title} (ID: {entity.id})")
                                continue
                        finally:
                            db.close_session(temp_session)

                        if getattr(entity, 'megagroup', False):
                            group_type = 'supergroup'
                        elif dialog.is_group:
                            group_type = 'group'
                        else:
                            group_type = 'unknown'

                        slowmode_seconds = 0
                        slowmode_minutes = 0

                        if type(entity).__name__ == 'Channel':
                            try:
                                full_channel = await client(GetFullChannelRequest(channel=entity))
                                slowmode_seconds = getattr(full_channel.full_chat, 'slowmode_seconds', 0) or 0
                                slowmode_minutes = slowmode_seconds // 60 if slowmode_seconds > 0 else 0
                            except Exception as e:
                                logger.debug(f"Не удалось получить медленный режим для {dialog.title}: {e}")

                        group_info = {
                            'id': storage_id,
                            'original_id': entity.id,
                            'title': dialog.title,
                            'type': group_type,
                            'participants_count': getattr(entity, 'participants_count', 0),
                            'slowmode_seconds': slowmode_seconds,
                            'slowmode_minutes': slowmode_minutes
                        }
                        writable_groups.append(group_info)

                        if slowmode_seconds > 0:
                            logger.info(f"Добавлен доступный группа: {dialog.title} (ID: {entity.id}, Тип: {group_info['type']}, Медленный режим: {slowmode_minutes}m)")
                        else:
                            logger.info(f"Добавлен доступный группа: {dialog.title} (ID: {entity.id}, Тип: {group_info['type']})")
                    else:
                        logger.info(f"Skipped non-writable group: {dialog.title} (ID: {entity.id})")

            except Exception as e:
                logger.warning(f"Не удалось обработать диалог {dialog.title}: {e}")
                continue

        await client.disconnect()
        logger.info(f"Найдено {len(writable_groups)} доступных групп/супергрупп из {len(all_dialogs)} всех диалогов")
        return writable_groups

    except Exception as e:
        logger.error(f"Ошибка получения групп аккаунта: {e}")
        return []

async def get_account_groups_with_topics(account):
    try:
        proxy_config = None
        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)

        client = TelegramClient(
            StringSession(account.session_string),
            account.api_id,
            account.api_hash,
            proxy=proxy_config,
            timeout=10,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30"
        )

        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            return []

        all_dialogs = []
        async for dialog in client.iter_dialogs():
            all_dialogs.append(dialog)

        groups_with_topics = []
        me = await client.get_me()

        if me is None:
            logger.warning(f"Не удалось получить информацию об аккаунте {account.phone_number}")
            await client.disconnect()
            return []

        logger.info(f"Найдено {len(all_dialogs)} диалогов для аккаунта {account.phone_number}")

        for dialog in all_dialogs:
            try:
                entity = dialog.entity

                is_group = getattr(entity, 'megagroup', False) or dialog.is_group
                is_channel = getattr(entity, 'broadcast', False) or dialog.is_channel
                is_supergroup = getattr(entity, 'megagroup', False)
                is_bot = getattr(entity, 'bot', False)

                if is_bot:
                    continue

                if is_channel and getattr(entity, 'broadcast', False) and not getattr(entity, 'megagroup', False):
                    continue

                if is_group or is_supergroup or (is_channel and getattr(entity, 'megagroup', False)):
                    can_write = False

                    try:
                        participant = await client(GetParticipantRequest(
                            channel=entity,
                            participant=me
                        ))
                        participant = participant.participant

                        if isinstance(participant, (ChannelParticipantCreator, ChannelParticipantAdmin)):
                            can_write = True
                        elif isinstance(participant, ChannelParticipant):
                            banned_rights = getattr(participant, 'banned_rights', None)
                            if banned_rights and isinstance(banned_rights, ChatBannedRights):
                                if banned_rights.send_messages is None:
                                    can_write = True
                                else:
                                    can_write = not banned_rights.send_messages
                            else:
                                can_write = True
                        else:
                            can_write = True

                    except Exception as e:
                        logger.warning(f"Не удалось получить информацию о участнике для {dialog.title}: {e}")
                        if is_group or is_supergroup:
                            can_write = True
                        else:
                            can_write = True

                    if can_write:
                        topics = []
                        has_forum = False

                        try:
                            from telethon.tl.functions.channels import GetForumTopicsRequest
                            from telethon.tl.types import Channel

                            if isinstance(entity, Channel):
                                has_forum = getattr(entity, 'forum', False)
                                is_supergroup = getattr(entity, 'megagroup', False)
                                logger.info(f"Обрабатываем группу: {dialog.title}, Супергруппа: {is_supergroup}, Форум: {has_forum}")

                                if has_forum:
                                    try:
                                        forum_topics = await client(GetForumTopicsRequest(
                                            channel=entity,
                                            offset_date=None,
                                            offset_id=0,
                                            offset_topic=0,
                                            limit=100
                                        ))
                                        logger.info(f"Получен ответ от GetForumTopicsRequest для {dialog.title}: {len(forum_topics.topics)} тем")

                                        deleted_topics_count = 0
                                        for topic in forum_topics.topics:
                                            if isinstance(topic, ForumTopicDeleted):
                                                deleted_topics_count += 1
                                                logger.info(f"🗑️ Пропускаем удаленную тему (ID: {getattr(topic, 'id', 'Unknown')})")
                                                continue

                                            can_write_to_topic = await _check_topic_write_permission(client, entity, topic, me, logger)

                                            if can_write_to_topic:
                                                topics.append({
                                                    'id': topic.id,
                                                    'title': topic.title,
                                                    'icon_color': getattr(topic, 'icon_color', 0),
                                                    'icon_emoji_id': getattr(topic, 'icon_emoji_id', None)
                                                })
                                                logger.info(f"✅ Тема доступна для записи: {topic.title} (ID: {topic.id})")
                                            else:
                                                logger.info(f"❌ Тема недоступна для записи: {getattr(topic, 'title', 'Unknown')} (ID: {getattr(topic, 'id', 'Unknown')})")

                                        logger.info(f"Найдено {len(topics)} доступных тем из {len(forum_topics.topics)} всего (удаленных: {deleted_topics_count}) в группе {dialog.title}")
                                    except Exception as e:
                                        logger.warning(f"Не удалось получить темы для группы {dialog.title}: {e}")
                                        topics = [{'id': 1, 'title': 'General', 'icon_color': 0, 'icon_emoji_id': None}]
                                        logger.info(f"Добавлена тема General для группы {dialog.title}")

                        except Exception as e:
                            logger.debug(f"Ошибка при проверке форума для группы {dialog.title}: {e}")

                        from utils.group_id_helper import get_correct_group_id_for_storage
                        storage_id = get_correct_group_id_for_storage(entity)

                        logger.info(f"Группа {dialog.title}: entity.id={entity.id}, storage_id={storage_id}")

                        group_info = {
                            'id': storage_id,
                            'original_id': entity.id,
                            'title': dialog.title,
                            'type': 'supergroup' if getattr(entity, 'megagroup', False) else 'group',
                            'participants_count': getattr(entity, 'participants_count', 0),
                            'topics': topics,
                            'has_forum': has_forum
                        }

                        if len(topics) > 0:
                            groups_with_topics.append(group_info)
                            logger.info(f"Добавлена группа с темами: {dialog.title} (Доступных тем: {len(topics)}, Форум: {has_forum}, Супергруппа: {getattr(entity, 'megagroup', False)})")

            except Exception as e:
                logger.warning(f"Не удалось обработать диалог {dialog.title}: {e}")
                continue

        await client.disconnect()
        logger.info(f"Найдено {len(groups_with_topics)} групп с доступными темами из {len(all_dialogs)} всех диалогов")

        for group in groups_with_topics:
            logger.info(f"Группа: {group['title']}, Доступных тем: {len(group['topics'])}, Форум: {group['has_forum']}")

        return groups_with_topics

    except Exception as e:
        logger.error(f"Ошибка получения групп с темами: {e}")
        return []

async def _check_topic_write_permission(client, channel_entity, topic, me, logger_instance):
    try:
        if isinstance(topic, ForumTopicDeleted):
            logger_instance.info(f"🗑️ Удаленная тема - доступ запрещен")
            return False

        topic_title = getattr(topic, 'title', 'Unknown')
        topic_id = getattr(topic, 'id', 0)

        logger_instance.info(f"🔍 Проверка прав для темы: {topic_title} (ID: {topic_id})")

        if getattr(topic, 'closed', False):
            logger_instance.info(f"🔒 Тема {topic_title} закрыта")
            return False

        if getattr(topic, 'hidden', False):
            logger_instance.info(f"📁 Тема {topic_title} скрыта/архивирована")
            return False

        logger_instance.info(f"📊 Атрибуты темы {topic_title}: closed={getattr(topic, 'closed', 'N/A')}, hidden={getattr(topic, 'hidden', 'N/A')}")

        try:
            participant = await client(GetParticipantRequest(
                channel=channel_entity,
                participant=me
            ))
            participant = participant.participant

            if isinstance(participant, (ChannelParticipantCreator, ChannelParticipantAdmin)):
                logger_instance.info(f"👑 Пользователь админ/создатель - доступ к теме {topic_title}: ДА")
                return True

            elif isinstance(participant, ChannelParticipant):
                banned_rights = getattr(participant, 'banned_rights', None)
                if banned_rights and isinstance(banned_rights, ChatBannedRights):
                    if banned_rights.send_messages:
                        logger_instance.info(f"🚫 Запрещена отправка сообщений - доступ к теме {topic_title}: НЕТ")
                        return False
                    if hasattr(banned_rights, 'send_forum_topics') and banned_rights.send_forum_topics:
                        logger_instance.info(f"🚫 Запрещена отправка в форум темы - доступ к теме {topic_title}: НЕТ")
                        return False

                logger_instance.info(f"✅ Обычный участник без ограничений - доступ к теме {topic_title}: ДА")
                return True
            else:
                logger_instance.info(f"✅ Неопределенный тип участника - доступ к теме {topic_title}: ДА")
                return True

        except Exception as e:
            logger_instance.warning(f"⚠️ Не удалось проверить права для темы {topic_title}: {e}")
            return True

    except Exception as e:
        logger_instance.warning(f"❌ Ошибка проверки прав для темы {getattr(topic, 'title', 'Unknown')}: {e}")
        return True

async def diagnose_topic_access(account, group_id=None):
    try:
        proxy_config = None
        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)

        client = TelegramClient(
            StringSession(account.session_string),
            account.api_id,
            account.api_hash,
            proxy=proxy_config,
            timeout=10,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30"
        )

        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            logger.warning(f"🔐 Аккаунт {account.phone_number} не авторизован")
            return

        me = await client.get_me()

        if me is None:
            logger.warning(f"Не удалось получить информацию об аккаунте {account.phone_number}")
            return

        logger.info(f"🔍 Диагностика доступа к темам для аккаунта: {account.phone_number}")

        async for dialog in client.iter_dialogs():
            entity = dialog.entity

            if getattr(entity, 'bot', False):
                continue
            if getattr(entity, 'broadcast', False) and not getattr(entity, 'megagroup', False):
                continue

            if group_id and str(entity.id) != str(group_id) and str(-100 - entity.id) != str(group_id):
                continue

            is_group = getattr(entity, 'megagroup', False) or dialog.is_group
            is_supergroup = getattr(entity, 'megagroup', False)

            if is_group or is_supergroup:
                logger.info(f"\n📋 === ГРУППА: {dialog.title} ===")
                logger.info(f"🆔 ID: {entity.id}")
                logger.info(f"🏢 Тип: {'Супергруппа' if is_supergroup else 'Группа'}")

                has_forum = getattr(entity, 'forum', False)
                logger.info(f"🏗️ Форум: {'Да' if has_forum else 'Нет'}")

                if has_forum:
                    try:
                        from telethon.tl.functions.channels import GetForumTopicsRequest
                        forum_topics = await client(GetForumTopicsRequest(
                            channel=entity,
                            offset_date=None,
                            offset_id=0,
                            offset_topic=0,
                            limit=100
                        ))

                        logger.info(f"📊 Всего тем: {len(forum_topics.topics)}")

                        available_topics = 0
                        deleted_topics = 0
                        closed_topics = 0

                        for topic in forum_topics.topics:
                            if isinstance(topic, ForumTopicDeleted):
                                deleted_topics += 1
                                logger.info(f"🗑️ Удаленная тема (ID: {getattr(topic, 'id', 'Unknown')})")
                                continue

                            can_write = await _check_topic_write_permission(client, entity, topic, me, logger)
                            if can_write:
                                available_topics += 1
                            else:
                                closed_topics += 1

                        logger.info(f"✅ Доступных для записи: {available_topics}")
                        logger.info(f"🚫 Недоступных: {closed_topics}")
                        logger.info(f"🗑️ Удаленных: {deleted_topics}")

                    except Exception as e:
                        logger.warning(f"❌ Ошибка получения тем: {e}")
                else:
                    logger.info(f"ℹ️ У группы нет форума - темы недоступны")

        await client.disconnect()

    except Exception as e:
        logger.error(f"❌ Ошибка диагностики: {e}")


@router.callback_query(F.data.startswith("diagnose_topics_"))
async def diagnose_topics_callback(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        await safe_edit_message(
            callback.message,
            f"🔍 <b>Запуск диагностики доступа к темам</b>\n\n"
            f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
            "⏳ Анализируем группы и права доступа...\n\n"
            "📋 Результаты будут показаны в логах сервера.",
            None
        )

        await diagnose_topic_access(account)

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔄 Повторить загрузку",
            callback_data=f"super_groups_{account_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"account_settings_{account_id}"
        ))
        builder.adjust(1)

        await safe_edit_message(
            callback.message,
            f"✅ <b>Диагностика завершена</b>\n\n"
            f"📱 Аккаунт: <code>{account.phone_number}</code>\n\n"
            "📋 <b>Результаты диагностики:</b>\n"
            "• Проверены все группы с форумами\n"
            "• Проанализированы права доступа к темам\n"
            "• Показаны только темы доступные для записи\n\n"
            "📄 <i>Подробные результаты смотрите в логах сервера</i>\n\n"
            "💡 <b>Что проверялось:</b>\n"
            "• Статус тем (открыта/закрыта/архивирована)\n"
            "• Права на отправку сообщений\n"
            "• Права на отправку в форум темы\n"
            "• Роль пользователя (админ/участник)",
            builder.as_markup()
        )

    except Exception as e:
        logger.error(f"❌ Ошибка диагностики для аккаунта {account_id}: {e}")
        await callback.answer("❌ Ошибка при выполнении диагностики")
    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("check_session_"))
async def check_session(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        await callback.answer("🔍 Проверяю сессию...")

        proxy_config = None
        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)

        client = TelegramClient(
            StringSession(account.session_string),
            account.api_id,
            account.api_hash,
            proxy=proxy_config,
            timeout=10,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30"
        )

        try:
            await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                username = me.username if me.username else "Не установлен"
                first_name = me.first_name if me.first_name else ""
                last_name = me.last_name if me.last_name else ""

                text = f"✅ <b>Сессия активна</b>\n\n"
                text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
                text += f"👤 <b>Имя:</b> {first_name} {last_name}\n"
                text += f"🔗 <b>Username:</b> @{username}\n"
                text += f"🆔 <b>ID:</b> <code>{me.id}</code>\n\n"
                text += "🎉 <i>Сессия работает корректно!</i>"
            else:
                text = f"❌ <b>Сессия недействительна</b>\n\n"
                text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n"
                text += "⚠️ <i>Сессия устарела или недействительна.\n"
                text += "Необходимо переавторизовать аккаунт.</i>"

                mailer_image = FSInputFile("img_static/mailer.png")
                await callback.bot.edit_message_media(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
                    reply_markup=get_invalid_session_keyboard(account_id)
                )
                return

        except Exception as e:
            text = f"❌ <b>Ошибка проверки сессии</b>\n\n"
            text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
            text += f"🔍 <b>Ошибка:</b> {str(e)}\n\n"
            text += "⚠️ <i>Не удалось проверить сессию.</i>"

        finally:
            try:
                await client.disconnect()
            except:
                pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=get_account_extra_functions_keyboard(account_id)
        )

    finally:
        db.close_session(session)

    await callback.answer()

def get_cached_image(image_name):
    if image_name not in CACHED_IMAGES:
        CACHED_IMAGES[image_name] = FSInputFile(f"img_static/{image_name}")
    return CACHED_IMAGES[image_name]


async def safe_edit_message(message: Message, text: str, reply_markup=None, parse_mode="HTML"):
    try:
        if message.photo or message.video or message.document or message.animation:
            await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await message.answer(text=text, reply_markup=reply_markup, parse_mode=parse_mode)

class AccountStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()
    waiting_for_media = State()
    waiting_for_interval = State()
    waiting_for_group_message = State()
    waiting_for_group_media = State()
    waiting_for_group_interval = State()
    waiting_for_profile_name = State()
    waiting_for_profile_username = State()
    waiting_for_profile_bio = State()
    waiting_for_profile_photo = State()
    waiting_for_common_message = State()
    waiting_for_common_interval = State()
    waiting_for_common_media = State()
    waiting_for_autoresponder_first_message = State()
    waiting_for_autoresponder_away_message = State()
    waiting_for_autoresponder_away_minutes = State()
    waiting_for_template_name = State()
    waiting_for_account_promo = State()

    waiting_for_super_group_message = State()
    waiting_for_super_group_media = State()
    waiting_for_super_group_interval = State()
    waiting_for_topic_message = State()
    waiting_for_topic_media = State()
    waiting_for_topic_interval = State()
    waiting_for_topic_escrow = State()
    waiting_for_group_escrow = State()
    waiting_for_reauth_code = State()
    waiting_for_reauth_password = State()
    waiting_for_qr_password = State()
    waiting_for_session_file = State()

user_sessions = {}

async def check_account_session(account) -> bool:
    try:
        if not account.session_string or not account.api_id or not account.api_hash:
            logger.warning(f"Отсутствуют данные для проверки сессии аккаунта {account.phone_number}")
            return False

        proxy_config = None
        if account.proxy_id:
            from database.database import get_proxy_by_id
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                from utils.proxy_validator import get_telethon_proxy_config
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)

        client = TelegramClient(
            StringSession(account.session_string),
            account.api_id,
            account.api_hash,
            proxy=proxy_config,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30"
        )

        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            logger.warning(f"Аккаунт {account.phone_number} не авторизован")
            return False

        me = await client.get_me()
        await client.disconnect()

        return me is not None

    except (AuthKeyUnregisteredError, UserDeactivatedError, PhoneNumberBannedError) as e:
        logger.warning(f"Проблема с аккаунтом {account.phone_number}: {type(e).__name__} - {e}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при проверке сессии аккаунта {account.phone_number}: {e}")
        return False

@router.callback_query(F.data.startswith("check_session_manual_"))
async def check_account_session_manual(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[3])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        await callback.answer("🔍 Проверяем сессию...")

        logger.info(f"Ручная проверка сессии аккаунта {account.phone_number}")
        session_valid = await check_account_session(account)
        logger.info(f"Результат ручной проверки сессии для {account.phone_number}: {session_valid}")

        if not session_valid:
            logger.warning(f"Сессия аккаунта {account.phone_number} недействительна, показываем меню проблем")
            from keyboards.keyboards import get_account_problem_keyboard
            mailer_image = FSInputFile("img_static/mailer.png")
            await callback.bot.edit_message_media(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                media=InputMediaPhoto(
                    media=mailer_image,
                    caption=f"❌ <b>Проблема с аккаунтом</b> <code>{account.phone_number}</code>\n\n"
                           f"Не удалось подключиться к аккаунту. Возможные причины:\n"
                           f"• Сессия недействительна\n"
                           f"• Аккаунт заблокирован\n"
                           f"• Проблемы с сетью\n\n"
                           f"Выберите действие:",
                    parse_mode="HTML"
                ),
                reply_markup=get_account_problem_keyboard(account_id)
            )
        else:
            status = "🟢 Активен" if account.is_active else "🔴 Неактивен"
            if account.subscription_minutes > 0:
                subscription = f"{account.subscription_minutes} минут ({format_minutes_to_readable(account.subscription_minutes)})"
            else:
                subscription = "Нет подписки"

            text = f"✅ <b>Сессия проверена!</b>\n\n"
            text += f"<b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
            text += f"<b>Статус:</b> {status}\n"
            text += f"<b>Подписка:</b> {subscription}"

            if account.is_active:
                text += f"\n\n🚀 Рассылка запущена для аккаунта <code>{account.phone_number}</code>"

            mailer_image = FSInputFile("img_static/mailer.png")
            await callback.bot.edit_message_media(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
                reply_markup=get_account_actions_keyboard(account_id, is_active=account.is_active, subscription_minutes=account.subscription_minutes)
            )

    finally:
        db.close_session(session)

"""
QR Login handlers
"""

@router.callback_query(F.data == "qr_login")
async def qr_login_callback(callback: CallbackQuery, state: FSMContext):
    user_id = str(callback.from_user.id)

    if user_id not in user_sessions:
        await callback.answer("❌ Сессия не найдена. Начните заново.", show_alert=True)
        return

    session_data = user_sessions[user_id]
    client: TelegramClient = session_data.get('client')

    if client is None:
        await callback.answer("❌ Клиент не инициализирован. Начните заново.", show_alert=True)
        return

    try:
        if not client.is_connected():
            await client.connect()
    except Exception:
        try:
            await client.connect()
        except Exception as e:
            logger.error(f"Не удалось подключиться к TelegramClient для QR входа: {e}")
            await callback.answer("❌ Не удалось подключиться к Telegram.", show_alert=True)
            return

    try:
        qr_login = await client.qr_login()
        qr_url = getattr(qr_login, 'url', None) or getattr(qr_login, 'link', None)

        text = (
            "🔐 <b>Вход по QR</b>\n\n"
            "1) Откройте Telegram на телефоне\n"
            "2) Настройки → Устройства → Подключить устройство\n"
            "3) Отсканируйте QR ниже\n"
            "!!QR действителен в течение 15 сек!!.\n\n"
        )
        text += "После подтверждения входа авторизация завершится автоматически."

        sent = None

        qr_png = None
        if not qr_url:
            await callback.answer("❌ Не удалось получить QR-ссылку от Telegram.", show_alert=True)
            return

        try:
            import qrcode
            from io import BytesIO
        except Exception:
            await callback.answer("❌ Не установлен модуль qrcode. Установите его и повторите.", show_alert=True)
            return

        img = qrcode.make(qr_url)
        bio = BytesIO()
        img.save(bio, format="PNG")
        qr_png = bio.getvalue()

        file = BufferedInputFile(qr_png, filename="qr_login.png")
        try:
            await callback.bot.edit_message_media(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                media=InputMediaPhoto(media=file, caption=text, parse_mode="HTML"),
                reply_markup=get_qr_login_keyboard()
            )
        except Exception:
            sent = await callback.message.answer_photo(photo=file, caption=text, parse_mode="HTML", reply_markup=get_qr_login_keyboard())
            try:
                await callback.message.delete()
            except Exception:
                pass
            callback.message = sent

        await callback.answer()

        async def wait_for_qr_confirmation():
            try:
                await qr_login.wait()

                session_string = client.session.save()
                me = await client.get_me()
                if me is None:
                    await safe_edit_message(callback.message, "❌ Не удалось получить информацию об аккаунте", get_main_menu_keyboard())
                    return

                phone_number = session_data.get('phone_number') or (getattr(me, 'phone', None) or 'unknown')

                account, bonus_applied = create_account(
                    user_id=user_id,
                    phone_number=phone_number,
                    session_string=session_string,
                    api_id=client.api_id,
                    api_hash=client.api_hash
                )

                if session_data.get('proxy_id'):
                    from database.database import db
                    temp = db.get_session()
                    try:
                        account.proxy_id = session_data['proxy_id']
                        temp.commit()
                    finally:
                        db.close_session(temp)

                caption = (
                    f"✅ <b>Аккаунт успешно добавлен!</b>\n\n"
                    f"📱 <b>Номер:</b> {phone_number}\n"
                    f"👤 <b>Имя:</b> {me.first_name or 'Не указано'}\n"
                )
                if bonus_applied:
                    caption += "🎁 <b>Начислен бонус за пополнение аккаунта</b>\n"

                try:
                    await safe_edit_message(callback.message, caption, get_main_menu_keyboard())
                finally:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    user_sessions.pop(user_id, None)

            except asyncio.CancelledError:
                return
            except SessionPasswordNeededError:
                await state.set_state(AccountStates.waiting_for_qr_password)
                await state.update_data(qr_user_id=user_id)
                prompt = (
                    "🔐 <b>Двухэтапная аутентификация</b>\n\n"
                    "Введите пароль для завершения входа:"
                )
                await safe_edit_message(callback.message, prompt, get_back_to_main_keyboard())
                return
            except Exception as e:
                logger.error(f"QR login error: {e}")
                if str(e).strip():
                    await safe_edit_message(callback.message, "❌ Ошибка при входе по QR. Попробуйте позже.", get_main_menu_keyboard())

        asyncio.create_task(wait_for_qr_confirmation())

    except Exception as e:
        logger.error(f"Ошибка при инициации входа по QR: {e}")
        await callback.answer("❌ Не удалось начать вход по QR.", show_alert=True)


@router.message(AccountStates.waiting_for_qr_password)
async def process_qr_password(message: Message, state: FSMContext):
    password = message.text.strip()
    user_id = str(message.from_user.id)

    if user_id not in user_sessions:
        await safe_edit_message(message, "❌ Сессия не найдена. Начните заново.", get_main_menu_keyboard())
        await state.clear()
        return

    session_data = user_sessions[user_id]
    client: TelegramClient = session_data.get('client')
    if client is None:
        await safe_edit_message(message, "❌ Клиент не инициализирован. Начните заново.", get_main_menu_keyboard())
        await state.clear()
        return

    try:
        await client.sign_in(password=password)

        session_string = client.session.save()
        me = await client.get_me()
        if me is None:
            await safe_edit_message(message, "❌ Не удалось получить информацию об аккаунте", get_main_menu_keyboard())
            await state.clear()
            return

        phone_number = session_data.get('phone_number') or (getattr(me, 'phone', None) or 'unknown')

        account, bonus_applied = create_account(
            user_id=user_id,
            phone_number=phone_number,
            session_string=session_string,
            api_id=client.api_id,
            api_hash=client.api_hash
        )

        if session_data.get('proxy_id'):
            from database.database import db
            temp = db.get_session()
            try:
                account.proxy_id = session_data['proxy_id']
                temp.commit()
            finally:
                db.close_session(temp)

        caption = (
            f"✅ <b>Аккаунт успешно добавлен!</b>\n\n"
            f"📱 <b>Номер:</b> {phone_number}\n"
            f"👤 <b>Имя:</b> {me.first_name or 'Не указано'}\n"
        )
        if bonus_applied:
            caption += "🎁 <b>Начислен бонус за пополнение аккаунта</b>\n"

        await safe_edit_message(message, caption, get_main_menu_keyboard())

    except Exception as e:
        logger.error(f"QR 2FA sign_in error: {e}")
        await safe_edit_message(message, "❌ Пароль неверен или истёк сеанс QR. Попробуйте заново.", get_main_menu_keyboard())
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        user_sessions.pop(user_id, None)
        await state.clear()

@router.callback_query(F.data == "refresh_qr")
async def refresh_qr_callback(callback: CallbackQuery, state: FSMContext):
    user_id = str(callback.from_user.id)

    if user_id in user_sessions:
        session_data = user_sessions[user_id]
        old_client = session_data.get('client')

        if old_client:
            try:
                await old_client.disconnect()
            except Exception:
                pass

        del user_sessions[user_id]

    data = await state.get_data()
    proxy_id = data.get('proxy_id')

    if not proxy_id:
        await callback.answer("❌ Данные прокси не найдены. Начните процесс заново.", show_alert=True)
        return

    proxy = get_proxy_by_id(proxy_id)
    if not proxy or not proxy.is_working:
        await callback.answer("❌ Прокси недоступен. Начните процесс заново.", show_alert=True)
        return

    api_credentials = get_api_credentials_with_rotation()
    if not api_credentials:
        await callback.answer("❌ Нет доступных API данных.", show_alert=True)
        return

    api_id, api_hash, api_name = api_credentials

    from utils.proxy_validator import get_telethon_proxy_config
    proxy_config = None
    if proxy:
        proxy_data = {
            'host': proxy.host,
            'port': proxy.port,
            'username': proxy.username,
            'password': proxy.password,
            'proxy_type': proxy.proxy_type
        }
        proxy_config = get_telethon_proxy_config(proxy_data)

    try:
        client = TelegramClient(
            StringSession(),
            api_id,
            api_hash,
            proxy=proxy_config,
            timeout=30,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30"
        )

        await client.connect()

        user_sessions[user_id] = {
            'client': client,
            'proxy_id': proxy_id,
            'api_id': api_id,
            'api_hash': api_hash
        }

        qr_login = await client.qr_login()
        qr_url = getattr(qr_login, 'url', None) or getattr(qr_login, 'link', None)

        if not qr_url:
            await callback.answer("❌ Не удалось получить новый QR код.", show_alert=True)
            return

        text = (
            "🔄 <b>Новый QR код создан!</b>\n\n"
            "🔐 <b>Вход по QR</b>\n\n"
            "1) Откройте Telegram на телефоне\n"
            "2) Настройки → Устройства → Подключить устройство\n"
            "3) Отсканируйте QR ниже\n"
            "!!QR действителен в течение 15 сек!!.\n\n"
            "После подтверждения входа авторизация завершится автоматически."
        )

        try:
            import qrcode
            from io import BytesIO

            img = qrcode.make(qr_url)
            bio = BytesIO()
            img.save(bio, format="PNG")
            qr_png = bio.getvalue()

            file = BufferedInputFile(qr_png, filename="qr_login_new.png")

            await callback.bot.edit_message_media(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                media=InputMediaPhoto(media=file, caption=text, parse_mode="HTML"),
                reply_markup=get_qr_login_keyboard()
            )

            await callback.answer("🔄 QR код обновлен!")

            async def wait_for_new_qr_confirmation():
                try:
                    await qr_login.wait()

                    if await client.is_user_authorized():
                        session_string = client.session.save()
                        me = await client.get_me()

                        if me:
                            phone_number = getattr(me, 'phone', None) or 'unknown'
                            username = getattr(me, 'username', None)
                            first_name = getattr(me, 'first_name', None) or 'Не указано'
                            last_name = getattr(me, 'last_name', None) or ''

                            account, bonus_applied = create_account(
                                user_id=user_id,
                                phone_number=phone_number,
                                session_string=session_string,
                                api_id=api_id,
                                api_hash=api_hash
                            )

                            if account:
                                try:
                                    test_client = TelegramClient(
                                        StringSession(session_string),
                                        api_id,
                                        api_hash,
                                        proxy=proxy_config if proxy_config else None
                                    )
                                    await test_client.connect()
                                    is_authorized = await test_client.is_user_authorized()
                                    await test_client.disconnect()

                                    if not is_authorized:
                                        from database.database import db
                                        session_db = db.get_session()
                                        try:
                                            session_db.delete(account)
                                            session_db.commit()
                                        finally:
                                            db.close_session(session_db)

                                        await callback.message.edit_text(
                                            f"❌ <b>Ошибка добавления аккаунта</b>\n\n"
                                            f"Сессия недействительна или аккаунт заблокирован.\n"
                                            f"Попробуйте авторизоваться заново.",
                                            reply_markup=get_account_retry_keyboard(),
                                            parse_mode="HTML"
                                        )
                                        await client.disconnect()
                                        user_sessions.pop(user_id, None)
                                        return

                                except Exception as session_error:
                                    logger.error(f"Ошибка при проверке сессии: {session_error}")

                                from database.database import db
                                session_db = db.get_session()
                                try:
                                    account.profile_name = first_name
                                    if proxy_id:
                                        account.proxy_id = proxy_id
                                    session_db.commit()
                                except Exception as e:
                                    logger.error(f"Ошибка при обновлении профиля аккаунта: {e}")
                                finally:
                                    db.close_session(session_db)
                                success_message = f"✅ <b>Аккаунт успешно добавлен!</b>\n\n"
                                success_message += f"📱 <b>Номер:</b> {phone_number}\n"
                                success_message += f"👤 <b>Имя:</b> {first_name} {last_name}\n"
                                if username:
                                    success_message += f"🔗 <b>Username:</b> @{username}\n"
                                success_message += f"🔗 <b>Прокси:</b> {proxy.host}:{proxy.port}"

                                if bonus_applied:
                                    success_message += f"\n\n🎁 <b>Бонус получен!</b>\n+30 минут к подписке за первый аккаунт"

                                await callback.message.edit_text(
                                    success_message,
                                    reply_markup=get_account_retry_keyboard(),
                                    parse_mode="HTML"
                                )

                        await client.disconnect()
                        user_sessions.pop(user_id, None)

                except Exception as e:
                    logger.error(f"Ошибка в новом QR подтверждении: {e}")
                    try:
                        await client.disconnect()
                    except:
                        pass
                    user_sessions.pop(user_id, None)

            asyncio.create_task(wait_for_new_qr_confirmation())

        except ImportError:
            await callback.answer("❌ Не установлен модуль qrcode.", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка при создании QR изображения: {e}")
            await callback.answer("❌ Ошибка при создании QR кода.", show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка при обновлении QR кода: {e}")
        await callback.answer("❌ Не удалось создать новый QR код. Попробуйте позже.", show_alert=True)

        if user_id in user_sessions:
            try:
                client = user_sessions[user_id].get('client')
                if client:
                    await client.disconnect()
            except:
                pass
            del user_sessions[user_id]

@router.callback_query(F.data.startswith("reauth_account_"))
async def reauth_account_start(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        phone_number = account.phone_number

        account.session_string = None
        account.is_active = False
        session.commit()

        from database.database import get_working_proxies
        working_proxies = get_working_proxies()

        if not working_proxies:
            await safe_edit_message(
                callback.message,
                "❌ <b>Нет доступных прокси</b>\n\n"
                "В данный момент нет рабочих прокси для авторизации аккаунтов.\n"
                "Обратитесь к администратору для добавления прокси.",
                get_account_retry_keyboard()
            )
            return

        import random
        selected_proxy = random.choice(working_proxies)

        max_attempts = 3
        attempt = 0
        success = False
        last_error = ""

        while attempt < max_attempts and not success:
            attempt += 1

            try:
                api_credentials = get_api_credentials_with_rotation()
                if not api_credentials:
                    logger.error("Нет доступных API credentials для переавторизации")
                    await safe_edit_message(
                        callback.message,
                        "❌ <b>Нет доступных API</b>\n\n"
                        "В данный момент нет доступных API для отправки кода.\n"
                        "Обратитесь к администратору.",
                        get_account_retry_keyboard()
                    )
                    return

                api_id, api_hash, api_name = api_credentials
                logger.info(f"Попытка {attempt}/{max_attempts}: Используем {api_name} для переавторизации {phone_number}")
                logger.info(f"🔗 Используем прокси: {selected_proxy.host}:{selected_proxy.port} ({selected_proxy.proxy_type})")

                proxy_data = {
                    'host': selected_proxy.host,
                    'port': selected_proxy.port,
                    'username': selected_proxy.username,
                    'password': selected_proxy.password,
                    'proxy_type': selected_proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)

                if proxy_config is None:
                    logger.error(f"❌ Ошибка создания конфигурации прокси для {selected_proxy.host}:{selected_proxy.port}")
                    continue

                client = TelegramClient(
                    StringSession(),
                    api_id,
                    api_hash,
                    proxy=proxy_config,
                    system_version="4.16.30-vxCUSTOM",
                    device_model="Desktop",
                    app_version="4.16.30"
                )

                await client.connect()

                user_id = str(callback.from_user.id)
                user_sessions[user_id] = {
                    'client': client,
                    'phone_number': phone_number,
                    'proxy_id': selected_proxy.id,
                    'reauth_account_id': account_id,
                    'api_id': api_id,
                    'api_hash': api_hash,
                    'api_name': api_name
                }

                await client.send_code_request(phone_number, force_sms=False)

                log_code_sending(phone_number, api_name, True)

                await state.update_data(
                    reauth_account_id=account_id,
                    phone_number=phone_number,
                    proxy_username=selected_proxy.username,
                    proxy_password=selected_proxy.password,
                    proxy_type=selected_proxy.proxy_type,
                    api_id=api_id,
                    api_hash=api_hash,
                    api_name=api_name
                )

                proxy_info = f"🔗 <b>Выбран прокси:</b> {selected_proxy.host}:{selected_proxy.port}"
                from keyboards.keyboards import get_code_entry_keyboard
                await safe_edit_message(
                    callback.message,
                    f"🔄 <b>Повторная авторизация аккаунта</b>\n\n"
                    f"📱 <b>Номер:</b> <code>{phone_number}</code>\n"
                    f"{proxy_info}\n"
                    f"📩 Код подтверждения отправлен в Telegram!\n\n"
                    f"💡 <b>Введите код из Telegram:</b>\n"
                    f"<b>ВНИМАНИЕ‼️</b>\n"
                    f"!ЕСЛИ У ВАС ПОДКЛЮЧЕНА ПОЧТА НА АККАУНТЕ, КОД МОЖЕТ НЕ ПРИЙТИ!\n\n"
                    "📱 Код придет через уведомления Telegram на вашем устройстве\n"
                    "⚠️ В любое место в коде добавьте \"_\" , к примеру: 123_45",
                    get_code_entry_keyboard()
                )

                await state.set_state(AccountStates.waiting_for_reauth_code)
                success = True

            except FloodWaitError as e:
                error_msg = f"Превышен лимит запросов. Ожидание {e.seconds} секунд"
                logger.warning(f"FloodWaitError для {phone_number} с {api_name}: {error_msg}")
                log_code_sending(phone_number, api_name, False, error_msg)
                last_error = error_msg

            except Exception as e:
                error_msg = f"Ошибка при отправке кода: {str(e)}"
                logger.error(f"Ошибка переавторизации для {phone_number} с {api_name}: {error_msg}")
                log_code_sending(phone_number, api_name, False, error_msg)
                mark_api_failed(api_id, api_hash, error_msg)
                last_error = error_msg

                try:
                    await client.disconnect()
                except:
                    pass

                if user_id in user_sessions:
                    del user_sessions[user_id]

                if attempt >= max_attempts:
                    await safe_edit_message(
                        callback.message,
                        f"❌ <b>Ошибка при отправке кода</b>\n\n"
                        f"Не удалось отправить код после {max_attempts} попыток.\n"
                        f"Последняя ошибка: {last_error}\n\n"
                        f"Попробуйте позже или обратитесь к поддержке.",
                        get_account_retry_keyboard()
                    )
                    return

        if not success:
            await safe_edit_message(
                callback.message,
                f"❌ <b>Не удалось отправить код</b>\n\n"
                f"Исчерпаны все попытки отправки кода.\n"
                f"Попробуйте позже или обратитесь к администратору.",
                get_account_retry_keyboard()
            )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data == "add_account")
async def add_account_start(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    from database.database import get_user_by_telegram_id, get_user_accounts

    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await callback.answer("❌ Пользователь не найден.")
        return

    accounts = get_user_accounts(telegram_id)

    if len(accounts) >= 1 and user.balance <= 0:

        error_message = (
            "❌ <b>Недостаточно средств</b>\n\n"
            "Для добавления второго и последующих аккаунтов необходимо пополнить баланс.\n\n"
            f"💰 <b>Ваш текущий баланс:</b> {user.balance} $\n"
            f"📱 <b>Подключенных аккаунтов:</b> {len(accounts)}\n\n"
            "Пополните баланс для продолжения работы."
        )

        if callback.message.text:
            await callback.message.edit_text(
                error_message,
                reply_markup=get_account_retry_keyboard(),
                parse_mode="HTML"
            )
        else:
            await callback.message.answer(
                error_message,
                reply_markup=get_account_retry_keyboard(),
                parse_mode="HTML"
            )
        await callback.answer()
        return

    from database.database import get_working_proxies

    working_proxies = get_working_proxies()

    if not working_proxies:
        if callback.message.text:
            await callback.message.edit_text(
                "❌ <b>Нет доступных прокси</b>\n\n"
                "В данный момент нет рабочих прокси для регистрации аккаунтов.\n"
                "Обратитесь к администратору для добавления прокси.",
                reply_markup=get_account_retry_keyboard()
            )
        else:
            await callback.message.answer(
                "❌ <b>Нет доступных прокси</b>\n\n"
                "В данный момент нет рабочих прокси для регистрации аккаунтов.\n"
                "Обратитесь к администратору для добавления прокси.",
                reply_markup=get_account_retry_keyboard()
            )
        await callback.answer()
        return

    import random
    selected_proxy = random.choice(working_proxies)

    await state.update_data(
        proxy_id=selected_proxy.id,
        proxy_host=selected_proxy.host,
        proxy_port=selected_proxy.port,
        proxy_username=selected_proxy.username,
        proxy_password=selected_proxy.password,
        proxy_type=selected_proxy.proxy_type
    )

    if callback.message.text:
        await callback.message.edit_text(
            f"📱 <b>Добавление аккаунта</b>\n\n"
            f"Выберите способ добавления аккаунта:",
            reply_markup=get_account_login_method_keyboard(),
            parse_mode="HTML"
        )
    else:
        await callback.message.answer(
            f"📱 <b>Добавление аккаунта</b>\n\n"
            f"Выберите способ добавления аккаунта:",
            reply_markup=get_account_login_method_keyboard(),
            parse_mode="HTML"
        )

    await callback.answer()

@router.callback_query(F.data == "login_by_phone")
async def login_by_phone_start(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    proxy_host = data.get('proxy_host')
    proxy_port = data.get('proxy_port')

    proxy_info = f"🔗 <b>Выбран прокси:</b> {proxy_host}:{proxy_port}"

    if callback.message.text:
        await callback.message.edit_text(
            f"📱 <b>Добавление аккаунта по номеру телефона</b>\n\n"
            f"{proxy_info}\n\n"
            f"Отправьте номер телефона в международном формате:\n"
            f"<code>+79001234567</code>",
            reply_markup=get_account_retry_keyboard(),
            parse_mode="HTML"
        )
    else:
        await callback.message.answer(
            f"📱 <b>Добавление аккаунта по номеру телефона</b>\n\n"
            f"{proxy_info}\n\n"
            f"Отправьте номер телефона в международном формате:\n"
            f"<code>+79001234567</code>",
            reply_markup=get_account_retry_keyboard(),
            parse_mode="HTML"
        )

    await state.set_state(AccountStates.waiting_for_phone)
    await callback.answer()

@router.callback_query(F.data == "login_by_session")
async def login_by_session_start(callback: CallbackQuery, state: FSMContext):
    from database.database import get_working_proxies
    import random

    working_proxies = get_working_proxies()

    if not working_proxies:
        if callback.message.text:
            await callback.message.edit_text(
                "❌ <b>Нет доступных прокси</b>\n\n"
                "В данный момент нет рабочих прокси для авторизации аккаунтов.\n"
                "Обратитесь к администратору для добавления прокси.",
                reply_markup=get_account_retry_keyboard()
            )
        else:
            await callback.message.answer(
                "❌ <b>Нет доступных прокси</b>\n\n"
                "В данный момент нет рабочих прокси для авторизации аккаунтов.\n"
                "Обратитесь к администратору для добавления прокси.",
                reply_markup=get_account_retry_keyboard()
            )
        await callback.answer()
        return

    selected_proxy = random.choice(working_proxies)

    await state.update_data(
        proxy_id=selected_proxy.id,
        proxy_host=selected_proxy.host,
        proxy_port=selected_proxy.port,
        proxy_username=selected_proxy.username,
        proxy_password=selected_proxy.password,
        proxy_type=selected_proxy.proxy_type
    )

    proxy_info = f"🔗 <b>Выбран прокси:</b> {selected_proxy.host}:{selected_proxy.port}"

    if callback.message.text:
        await callback.message.edit_text(
            f"📁 <b>Добавление аккаунта через .session файл</b>\n\n"
            f"{proxy_info}\n\n"
            f"Отправьте .session файл вашего Telegram аккаунта.\n\n"
            f"ℹ️ <b>Как получить .session файл:</b>\n"
            f"• Используйте любой Telegram клиент на Python (например, Telethon)\n"
            f"• Файл должен иметь расширение .session\n"
            f"• Убедитесь, что аккаунт авторизован в этом файле",
            reply_markup=get_account_retry_keyboard(),
            parse_mode="HTML"
        )
    else:
        await callback.message.answer(
            f"📁 <b>Добавление аккаунта через .session файл</b>\n\n"
            f"{proxy_info}\n\n"
            f"Отправьте .session файл вашего Telegram аккаунта.\n\n"
            f"ℹ️ <b>Как получить .session файл:</b>\n"
            f"• Используйте любой Telegram клиент на Python (например, Telethon)\n"
            f"• Файл должен иметь расширение .session\n"
            f"• Убедитесь, что аккаунт авторизован в этом файле",
            reply_markup=get_account_retry_keyboard(),
            parse_mode="HTML"
        )

    await state.set_state(AccountStates.waiting_for_session_file)
    await callback.answer()

@router.callback_query(F.data == "list_accounts")
async def list_accounts_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    accounts = get_user_accounts(telegram_id)
    if not accounts:
        await safe_edit_message(
            callback.message,
            "У вас нет подключенных аккаунтов 😔",
            get_no_accounts_keyboard()
        )
    else:
        from keyboards.keyboards import get_account_list_keyboard
        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=f"📱 <b>Ваши аккаунты</b> ({len(accounts)}):", parse_mode="HTML"),
            reply_markup=get_account_list_keyboard(accounts)
        )
    await callback.answer()

@router.message(AccountStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone_number = message.text.strip()

    if not phone_number.startswith('+') or len(phone_number) < 10:
        await message.answer(
            "❌ <b>Неверный формат номера телефона</b>\n\n"
            "Используйте международный формат:\n"
            "<code>+79001234567</code>",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        return

    data = await state.get_data()
    proxy_id = data.get('proxy_id')

    if not proxy_id:
        await message.answer(
            "❌ <b>Ошибка: прокси не найден</b>\n\n"
            "Попробуйте начать процесс заново.",
            reply_markup=get_account_retry_keyboard()
        )
        await state.clear()
        return

    proxy = get_proxy_by_id(proxy_id)
    if not proxy or not proxy.is_working:
        await message.answer(
            "❌ <b>Прокси недоступен</b>\n\n"
            "Выбранный прокси больше не работает.\n"
            "Попробуйте начать процесс заново.",
            reply_markup=get_account_retry_keyboard()
        )
        await state.clear()
        return

    await state.update_data(phone_number=phone_number)

    max_attempts = 3
    attempt = 0
    success = False
    last_error = ""

    while attempt < max_attempts and not success:
        attempt += 1

        try:
            api_credentials = get_api_credentials_with_rotation()
            if not api_credentials:
                logger.error("Нет доступных API credentials")
                await message.answer(
                    "❌ <b>Нет доступных API</b>\n\n"
                    "В данный момент нет доступных API для отправки кода.\n"
                    "Обратитесь к администратору.",
                    reply_markup=get_account_retry_keyboard()
                )
                await state.clear()
                return

            api_id, api_hash, api_name = api_credentials
            logger.info(f"Попытка {attempt}/{max_attempts}: Используем {api_name} для {phone_number}")
            logger.info(f"🔗 Используем прокси: {proxy.host}:{proxy.port} ({proxy.proxy_type})")

            proxy_config = get_telethon_proxy_config({
                'host': proxy.host,
                'port': proxy.port,
                'username': proxy.username,
                'password': proxy.password,
                'proxy_type': proxy.proxy_type
            })

            if proxy_config is None:
                logger.error(f"❌ Ошибка создания конфигурации прокси для {proxy.host}:{proxy.port}")
                continue

            client = TelegramClient(
                StringSession(),
                api_id,
                api_hash,
                proxy=proxy_config,
                timeout=30,
                system_version="4.16.30-vxCUSTOM",
                device_model="Desktop",
                app_version="4.16.30"
            )

            user_id = str(message.from_user.id)
            user_sessions[user_id] = {
                'client': client,
                'phone_number': phone_number,
                'proxy_id': proxy_id,
                'api_id': api_id,
                'api_hash': api_hash,
                'api_name': api_name
            }

            await client.connect()

            is_authorized = await client.is_user_authorized()
            logger.info(f"🔍 Статус авторизации для {phone_number}: {'Авторизован' if is_authorized else 'Не авторизован'}")

            if not is_authorized:
                logger.info(f"🔐 Аккаунт не авторизован, отправляем код для {phone_number}")

                try:
                    result = await client.send_code_request(phone_number)
                except Exception as e:
                    if "ResendCodeRequest" in str(e):
                        logger.info(f"🔄 Попробуем повторную отправку кода через resend_code")
                        try:
                            result = await client.resend_code(phone_number)
                            logger.info(f"📨 Повторная отправка успешна: {type(result).__name__}")
                        except Exception as resend_error:
                            logger.error(f"❌ Ошибка повторной отправки: {resend_error}")
                            raise e
                    else:
                        raise e

                logger.info(f"📨 Ответ от Telegram: {type(result).__name__}")
                if hasattr(result, 'type'):
                    logger.info(f"📨 Тип кода: {result.type}")
                if hasattr(result, 'phone_code_hash'):
                    logger.info(f"📨 Hash кода: {result.phone_code_hash[:10]}...")

                log_code_sending(phone_number, api_name, True)

                code_type_message = "📱 Код придет через уведомления Telegram на вашем устройстве"
                if hasattr(result, 'type'):
                    if 'Sms' in str(result.type):
                        code_type_message = "📱 Код придет по SMS на ваш номер телефона"
                    elif 'Call' in str(result.type):
                        code_type_message = "📞 Код придет через голосовой звонок"
                    elif 'App' in str(result.type):
                        code_type_message = "📱 Код придет через уведомления Telegram на вашем устройстве"

                from keyboards.keyboards import get_code_entry_keyboard
                await message.answer(
                    f"📱 <b>Код подтверждения отправлен</b>\n\n"
                    f"📞 <b>Номер:</b> {phone_number}\n"
                    f"💡 <b>Введите код:</b>\n"
                    f"<b>ВНИМАНИЕ‼️</b>\n"
                    f"{code_type_message}\n"
                    f"!ЕСЛИ У ВАС ПОДКЛЮЧЕНА ПОЧТА НА АККАУНТЕ, КОД МОЖЕТ НЕ ПРИЙТИ!\n\n"
                    f"⚠️ В любое место в коде добавьте \"_\" , к примеру: 123_45\n\n"
                    f"🔄 <b>Не получили код?</b> Попробуйте войти через QR",
                    reply_markup=get_code_entry_keyboard()
                )

                await state.set_state(AccountStates.waiting_for_code)
                success = True

            else:
                session_string = client.session.save()

                me = await client.get_me()

                if me is None:
                    await client.disconnect()
                    await message.answer("❌ Не удалось получить информацию об аккаунте")
                    await state.clear()
                    return

                await client.disconnect()

                account, bonus_applied = create_account(
                    user_id=user_id,
                    phone_number=phone_number,
                    session_string=session_string,
                    api_id=api_id,
                    api_hash=api_hash
                )

                if proxy_id:
                    from database.database import db
                    session = db.get_session()
                    try:
                        account.proxy_id = proxy_id
                        session.commit()
                    finally:
                        db.close_session(session)

                del user_sessions[user_id]

                caption = (
                    f"✅ <b>Аккаунт успешно подключен!</b>\n\n"
                    f"📱 <b>Номер:</b> {phone_number}\n"
                    f"👤 <b>Имя:</b> {me.first_name or 'Не указано'}\n"
                    f"🔐 <b>Статус:</b> Уже авторизован\n"
                )

                if bonus_applied:
                    caption += f"🎁 <b>Бонус:</b> {account.subscription_minutes} минут начислено!\n\n"

                caption += "Теперь вы можете настроить аккаунт и начать рассылку."

                mailer_image = FSInputFile("img_static/mailer.png")
                await message.answer_photo(
                    photo=mailer_image,
                    caption=caption,
                    reply_markup=get_account_management_keyboard()
                )
                await state.clear()
                success = True

        except FloodWaitError as e:
            error_msg = f"Превышен лимит запросов. Ожидание {e.seconds} секунд"
            logger.warning(f"FloodWaitError для {phone_number} с {api_name}: {error_msg}")
            log_code_sending(phone_number, api_name, False, error_msg)
            last_error = error_msg

            await message.answer(
                f"⏰ <b>Превышен лимит запросов</b>\n\n"
                f"Telegram временно ограничил отправку кодов.\n"
                f"⏳ Ожидание: {e.seconds} секунд\n\n"
                f"Попробуйте позже.",
                reply_markup=get_account_retry_keyboard()
            )
            await state.clear()
            return

        except PhoneNumberInvalidError as e:
            error_msg = f"Неверный номер телефона: {str(e)}"
            logger.error(f"PhoneNumberInvalidError для {phone_number} с {api_name}: {error_msg}")
            log_code_sending(phone_number, api_name, False, error_msg)
            mark_api_failed(api_id, api_hash, error_msg)
            last_error = error_msg

            try:
                await client.disconnect()
            except:
                pass

            if user_id in user_sessions:
                del user_sessions[user_id]

            if attempt >= max_attempts:
                await message.answer(
                    "❌ <b>Неверный номер телефона</b>\n\n"
                    "Проверьте правильность номера и попробуйте снова.",
                    reply_markup=get_account_retry_keyboard()
                )
                await state.clear()
                return

        except Exception as e:
            error_msg = f"Ошибка подключения: {str(e)}"
            logger.error(f"Ошибка в process_phone для {phone_number} с {api_name}: {error_msg}")
            log_code_sending(phone_number, api_name, False, error_msg)
            mark_api_failed(api_id, api_hash, error_msg)
            last_error = error_msg

            try:
                await client.disconnect()
            except:
                pass

            if user_id in user_sessions:
                del user_sessions[user_id]

            if attempt >= max_attempts:
                await message.answer(
                    f"❌ <b>Ошибка подключения</b>\n\n"
                    f"Не удалось подключиться к Telegram после {max_attempts} попыток.\n"
                    f"Последняя ошибка: {last_error}\n\n"
                    f"Возможные причины:\n"
                    f"• Прокси не работает\n"
                    f"• Проблемы с сетью\n"
                    f"• Все API временно недоступны\n\n"
                    f"Попробуйте позже или обратитесь к администратору.",
                    reply_markup=get_account_retry_keyboard()
                )
                await state.clear()
                return

    if not success:
        await message.answer(
            f"❌ <b>Не удалось отправить код</b>\n\n"
            f"Исчерпаны все попытки отправки кода.\n"
            f"Попробуйте позже или обратитесь к администратору.",
            reply_markup=get_account_retry_keyboard()
        )
        await state.clear()

@router.message(AccountStates.waiting_for_reauth_code)
async def process_reauth_code(message: Message, state: FSMContext):
    from utils.code_obfuscator import CodeObfuscator
    import asyncio

    input_code = message.text.strip()

    if CodeObfuscator.is_valid_code_format(input_code):
        code = CodeObfuscator.deobfuscate_code(input_code)
        logger.info(f"Деобфускация кода при переавторизации: {input_code} -> {code}")
    else:
        code = input_code

    if not code.isdigit() or len(code) < 4:
        await message.answer(
            "❌ <b>Неверный формат кода</b>\n\n"
            "Код должен содержать только цифры (обычно 5-6 цифр).",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        return

    user_id = str(message.from_user.id)

    if user_id not in user_sessions:
        await message.answer(
            "❌ <b>Сессия не найдена</b>\n\n"
            "Начните процесс переавторизации заново.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        return

    session_data = user_sessions[user_id]
    client = session_data['client']
    phone_number = session_data['phone_number']
    account_id = session_data['reauth_account_id']

    try:
        logger.info(f"Начинаем переавторизацию с кодом для {phone_number}")

        await client.sign_in(phone_number, code)
        logger.info(f"Успешно переавторизованы с кодом для {phone_number}")

        session_string = client.session.save()
        me = await client.get_me()

        if me is None:
            logger.error(f"get_me() вернул None для {phone_number}")
            await client.disconnect()
            await message.answer("❌ Не удалось получить информацию об аккаунте")
            await state.clear()
            return

        logger.info(f"Получена информация об аккаунте {phone_number}: {me.first_name}")
        await client.disconnect()

        from database.database import db
        session = db.get_session()
        try:
            from database.models import Account
            account = session.query(Account).filter(Account.id == account_id).first()
            if account:
                account.session_string = session_string
                account.is_active = True
                account.proxy_id = session_data.get('proxy_id')
                account.api_id = client.api_id
                account.api_hash = client.api_hash
                session.commit()

                await message.answer(
                    f"✅ <b>Аккаунт успешно переавторизован!</b>\n\n"
                    f"📱 <b>Номер:</b> <code>{phone_number}</code>\n"
                    f"👤 <b>Имя:</b> {me.first_name or 'Не указано'}\n\n"
                    f"Теперь вы можете настроить аккаунт и начать рассылку.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
        finally:
            db.close_session(session)

        await client.disconnect()
        if user_id in user_sessions:
            del user_sessions[user_id]

        await state.clear()

    except PhoneCodeExpiredError:
        logger.info(f"Код истек для номера {phone_number} при переавторизации, отправляем новый код")
        try:
            import time
            current_time = time.time()
            last_request_time = session_data.get('last_code_request_time', 0)

            if current_time - last_request_time < 60:
                await message.answer(
                    "⏰ <b>Слишком частые запросы кода</b>\n\n"
                    "Подождите минуту перед повторным запросом кода.",
                    reply_markup=get_back_to_main_keyboard()
                )
                return

            await client.send_code_request(phone_number, force_sms=False)
            session_data['last_code_request_time'] = current_time
            await message.answer(
                "⏰ <b>Код подтверждения истек</b>\n\n"
                "📱 <b>Новый код отправлен в Telegram!</b>\n\n"
                "💡 <b>Введите код из SMS или Telegram:</b>\n"
                "<b>ВНИМАНИЕ‼️</b>\n"
                "⚠️ В любое место в коде добавьте \"_\" , к примеру: 123_45",
                reply_markup=get_back_to_main_keyboard()
            )
            return
        except Exception as retry_e:
            logger.error(f"Ошибка при повторной отправке кода: {retry_e}")
            await message.answer(
                "❌ <b>Не удалось отправить новый код</b>\n\n"
                "Попробуйте начать процесс переавторизации заново.",
                reply_markup=get_main_menu_keyboard()
            )
            try:
                await client.disconnect()
            except:
                pass
            if user_id in user_sessions:
                del user_sessions[user_id]
            await state.clear()
            return

    except Exception as e:
        if "SESSION_PASSWORD_NEEDED" in str(e):
            temp_session = client.session.save()

            await state.update_data(
                temp_session_string=temp_session,
                reauth_account_id=account_id,
                user_id=user_id
            )

            await message.answer(
                "🔐 <b>Требуется двухфакторная аутентификация</b>\n\n"
                "Введите пароль от аккаунта:",
                reply_markup=get_account_retry_keyboard()
            )
            await state.set_state(AccountStates.waiting_for_reauth_password)
        else:
            logger.error(f"Ошибка при повторной авторизации: {e}")

            error_text = str(e).lower()
            if "expired" in error_text or "истек" in error_text:
                try:
                    await client.send_code_request(phone_number, force_sms=False)
                    await message.answer(
                        "⏰ <b>Код подтверждения истек</b>\n\n"
                        "📱 <b>Новый код отправлен в Telegram!</b>\n\n"
                        "💡 <b>Введите код из SMS или Telegram:</b>\n"
                        "<b>ВНИМАНИЕ‼️</b>\n"
                        "⚠️ В любое место в коде добавьте \"_\" , к примеру: 123_45",
                        reply_markup=get_back_to_main_keyboard()
                    )
                    return
                except Exception as retry_e:
                    logger.error(f"Ошибка при повторной отправке кода в переавторизации: {retry_e}")

            try:
                await client.disconnect()
            except:
                pass
            if user_id in user_sessions:
                del user_sessions[user_id]
            await message.answer(
                f"❌ <b>Ошибка авторизации</b>\n\n"
                f"Произошла ошибка: {str(e)}\n"
                f"Попробуйте еще раз или обратитесь к поддержке.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()

@router.message(AccountStates.waiting_for_reauth_password)
async def process_reauth_password(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    account_id = data.get('reauth_account_id')

    if not account_id:
        await message.answer(
            "❌ <b>Данные сессии не найдены</b>\n\n"
            "Начните процесс повторной авторизации заново.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        return

    try:
        api_id = data.get('api_id')
        api_hash = data.get('api_hash')
        phone_number = data.get('phone_number')
        temp_session_string = data.get('temp_session_string')

        if not temp_session_string:
            await message.answer(
                "❌ <b>Ошибка сессии</b>\n\n"
                "Временная сессия не найдена. Начните авторизацию заново.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
            return

        proxy_data = {
            'host': data.get('proxy_host'),
            'port': data.get('proxy_port'),
            'username': data.get('proxy_username'),
            'password': data.get('proxy_password'),
            'proxy_type': data.get('proxy_type')
        }
        proxy_config = get_telethon_proxy_config(proxy_data)

        client = TelegramClient(
            StringSession(temp_session_string),
            api_id,
            api_hash,
            proxy=proxy_config,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30"
        )

        await client.connect()
        await client.sign_in(password=password)

        session_string = client.session.save()
        me = await client.get_me()

        if me is None:
            await client.disconnect()
            await message.answer("❌ Не удалось получить информацию об аккаунте")
            await state.clear()
            return

        await client.disconnect()

        from database.database import db
        session = db.get_session()
        try:
            from database.models import Account
            account = session.query(Account).filter(Account.id == account_id).first()
            if account:
                account.session_string = session_string
                account.is_active = True
                account.api_id = client.api_id
                account.api_hash = client.api_hash
                session.commit()

                await message.answer(
                    f"✅ <b>Аккаунт успешно переавторизован!</b>\n\n"
                    f"📱 <b>Номер:</b> <code>{account.phone_number}</code>\n"
                    f"👤 <b>Имя:</b> {me.first_name or 'Не указано'}\n"
                    f"🔐 <b>2FA:</b> Включена\n\n"
                    f"Теперь вы можете настроить аккаунт и начать рассылку.",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
        finally:
            db.close_session(session)

        user_id = data.get('user_id')
        if user_id and user_id in user_sessions:
            del user_sessions[user_id]

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка при вводе пароля 2FA: {e}")
        try:
            await client.disconnect()
        except:
            pass
        user_id = data.get('user_id')
        if user_id and user_id in user_sessions:
            del user_sessions[user_id]
        await message.answer(
            f"❌ <b>Неверный пароль</b>\n\n"
            f"Ошибка: {str(e)}\n"
            f"Попробуйте еще раз или начните авторизацию заново.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()

@router.message(AccountStates.waiting_for_session_file)
async def process_session_file(message: Message, state: FSMContext):
    if not message.document:
        await message.answer(
            "❌ <b>Ошибка</b>\n\n"
            "Пожалуйста, отправьте .session файл как документ.",
            reply_markup=get_account_retry_keyboard(),
            parse_mode="HTML"
        )
        return

    file_name = message.document.file_name
    if not file_name or not file_name.endswith('.session'):
        await message.answer(
            "❌ <b>Неверный тип файла</b>\n\n"
            "Пожалуйста, отправьте файл с расширением .session",
            reply_markup=get_account_retry_keyboard(),
            parse_mode="HTML"
        )
        return

    if message.document.file_size > 1024 * 1024:
        await message.answer(
            "❌ <b>Файл слишком большой</b>\n\n"
            "Размер .session файла не должен превышать 1MB",
            reply_markup=get_account_retry_keyboard(),
            parse_mode="HTML"
        )
        return

    try:
        file = await message.bot.get_file(message.document.file_id)
        file_content = await message.bot.download_file(file.file_path)

        import tempfile
        import os

        temp_dir = tempfile.gettempdir()
        session_path = os.path.join(temp_dir, f"temp_{message.from_user.id}_{file_name}")

        with open(session_path, 'wb') as f:
            f.write(file_content.read())

        data = await state.get_data()
        proxy_id = data.get('proxy_id')

        if not proxy_id:
            os.remove(session_path)
            await message.answer(
                "❌ <b>Ошибка: прокси не найден</b>\n\n"
                "Попробуйте начать процесс заново.",
                reply_markup=get_account_retry_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return

        proxy = get_proxy_by_id(proxy_id)
        if not proxy or not proxy.is_working:
            os.remove(session_path)
            await message.answer(
                "❌ <b>Прокси недоступен</b>\n\n"
                "Выбранный прокси больше не работает.\n"
                "Попробуйте начать процесс заново.",
                reply_markup=get_account_retry_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return

        from utils.proxy_validator import get_telethon_proxy_config

        proxy_config = None
        if proxy:
            proxy_data = {
                'host': proxy.host,
                'port': proxy.port,
                'username': proxy.username,
                'password': proxy.password,
                'proxy_type': proxy.proxy_type
            }
            proxy_config = get_telethon_proxy_config(proxy_data)

        api_credentials = get_api_credentials_with_rotation()
        if not api_credentials:
            api_id = api_hash = api_name = None
        else:
            api_id, api_hash, api_name = api_credentials

        if not api_id or not api_hash:
            os.remove(session_path)
            await message.answer(
                "❌ <b>Нет доступных API данных</b>\n\n"
                "Обратитесь к администратору для добавления API данных.",
                reply_markup=get_account_retry_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return

        await message.answer(
            "🔄 <b>Проверка .session файла...</b>\n\n"
            "Подождите, идет проверка валидности аккаунта.",
            parse_mode="HTML"
        )

        try:
            client = TelegramClient(
                session_path,
                api_id,
                api_hash,
                proxy=proxy_config,
                timeout=30,
                system_version="4.16.30-vxCUSTOM",
                device_model="Desktop",
                app_version="4.16.30"
            )

            await client.connect()

            if not await client.is_user_authorized():
                await client.disconnect()
                os.remove(session_path)
                await message.answer(
                    "❌ <b>Сессия не авторизована</b>\n\n"
                    "Загруженный .session файл не содержит авторизованного аккаунта.\n"
                    "Убедитесь, что вы загружаете файл от активного аккаунта.",
                    reply_markup=get_account_retry_keyboard(),
                    parse_mode="HTML"
                )
                await state.clear()
                return

            me = await client.get_me()
            if not me:
                await client.disconnect()
                os.remove(session_path)
                await message.answer(
                    "❌ <b>Не удалось получить данные аккаунта</b>\n\n"
                    "Попробуйте загрузить другой .session файл.",
                    reply_markup=get_account_retry_keyboard(),
                    parse_mode="HTML"
                )
                await state.clear()
                return

            phone_number = me.phone or "Не указан"
            username = me.username or "Не указан"
            first_name = me.first_name or "Не указано"
            last_name = me.last_name or ""

            string_session_client = TelegramClient(
                StringSession(),
                api_id,
                api_hash,
                proxy=proxy_config
            )

            string_session_client.session.set_dc(
                client.session.dc_id,
                client.session.server_address,
                client.session.port
            )
            string_session_client.session.auth_key = client.session.auth_key

            session_string = string_session_client.session.save()

            await client.disconnect()
            os.remove(session_path)

            telegram_id = str(message.from_user.id)
            existing_accounts = get_user_accounts(telegram_id)

            for account in existing_accounts:
                if account.phone_number == phone_number:
                    await message.answer(
                        f"❌ <b>Аккаунт уже добавлен</b>\n\n"
                        f"Аккаунт с номером {phone_number} уже существует в вашем списке.",
                        reply_markup=get_account_retry_keyboard(),
                        parse_mode="HTML"
                    )
                    await state.clear()
                    return

            from database.database import get_user_by_telegram_id

            user = get_user_by_telegram_id(telegram_id)
            if not user:
                await message.answer(
                    "❌ <b>Пользователь не найден</b>",
                    reply_markup=get_account_retry_keyboard(),
                    parse_mode="HTML"
                )
                await state.clear()
                return

            account, bonus_applied = create_account(
                user_id=telegram_id,
                phone_number=phone_number,
                session_string=session_string,
                api_id=api_id,
                api_hash=api_hash
            )

            if account:
                try:
                    test_client = TelegramClient(
                        StringSession(session_string),
                        api_id,
                        api_hash,
                        proxy=proxy_config if 'proxy_config' in locals() else None
                    )
                    await test_client.connect()
                    is_authorized = await test_client.is_user_authorized()
                    await test_client.disconnect()

                    if not is_authorized:
                        from database.database import db
                        session_db = db.get_session()
                        try:
                            session_db.delete(account)
                            session_db.commit()
                        finally:
                            db.close_session(session_db)

                        await message.answer(
                            f"❌ <b>Ошибка добавления аккаунта</b>\n\n"
                            f"Сессия недействительна или аккаунт заблокирован.\n"
                            f"Попробуйте авторизоваться заново.",
                            reply_markup=get_account_retry_keyboard(),
                            parse_mode="HTML"
                        )
                        await state.clear()
                        return

                except Exception as session_error:
                    logger.error(f"Ошибка при проверке сессии: {session_error}")

                from database.database import db
                session_db = db.get_session()
                try:
                    account.profile_name = first_name
                    if proxy_id:
                        account.proxy_id = proxy_id
                    session_db.commit()
                except Exception as e:
                    logger.error(f"Ошибка при обновлении профиля аккаунта: {e}")
                finally:
                    db.close_session(session_db)
                success_message = f"✅ <b>Аккаунт успешно добавлен!</b>\n\n"
                success_message += f"📱 <b>Номер:</b> {phone_number}\n"
                success_message += f"👤 <b>Имя:</b> {first_name} {last_name}\n"
                if username != "Не указан":
                    success_message += f"🔗 <b>Username:</b> @{username}\n"
                success_message += f"🔗 <b>Прокси:</b> {proxy.host}:{proxy.port}"

                if bonus_applied:
                    success_message += f"\n\n🎁 <b>Бонус получен!</b>\n+30 минут к подписке за первый аккаунт"

                await message.answer(
                    success_message,
                    reply_markup=get_account_retry_keyboard(),
                    parse_mode="HTML"
                )

            else:
                await message.answer(
                    "❌ <b>Ошибка при сохранении аккаунта</b>\n\n"
                    "Не удалось сохранить аккаунт в базе данных.",
                    reply_markup=get_account_retry_keyboard(),
                    parse_mode="HTML"
                )

        except Exception as e:
            if 'session_path' in locals() and os.path.exists(session_path):
                os.remove(session_path)

            logger.error(f"Ошибка при проверке session файла: {e}")

            error_msg = "❌ <b>Ошибка при проверке аккаунта</b>\n\n"

            if "AUTH_KEY_UNREGISTERED" in str(e):
                error_msg += "Сессия устарела или была сброшена.\nПопробуйте создать новую сессию."
            elif "USER_DEACTIVATED" in str(e):
                error_msg += "Аккаунт деактивирован или заблокирован."
            elif "PHONE_NUMBER_BANNED" in str(e):
                error_msg += "Номер телефона заблокирован в Telegram."
            else:
                error_msg += f"Произошла ошибка: {str(e)}"

            await message.answer(
                error_msg,
                reply_markup=get_account_retry_keyboard(),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка при обработке session файла: {e}")
        await message.answer(
            "❌ <b>Ошибка при загрузке файла</b>\n\n"
            "Не удалось обработать загруженный файл.\n"
            "Убедитесь, что это корректный .session файл.",
            reply_markup=get_account_retry_keyboard(),
            parse_mode="HTML"
        )

    await state.clear()

@router.message(AccountStates.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    from utils.code_obfuscator import CodeObfuscator
    import asyncio

    input_code = message.text.strip()

    if CodeObfuscator.is_valid_code_format(input_code):
        code = CodeObfuscator.deobfuscate_code(input_code)
        logger.info(f"Деобфускация кода: {input_code} -> {code}")
    else:
        code = input_code

    if not code.isdigit() or len(code) < 4:
        await message.answer(
            "❌ <b>Неверный формат кода</b>\n\n"
            "Код должен содержать только цифры (обычно 5-6 цифр).",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        return

    user_id = str(message.from_user.id)

    if user_id not in user_sessions:
        await message.answer(
            "❌ <b>Сессия не найдена</b>\n\n"
            "Начните процесс добавления аккаунта заново.",
            reply_markup=get_account_retry_keyboard()
        )
        await state.clear()
        return

    session_data = user_sessions[user_id]
    client = session_data['client']
    phone_number = session_data['phone_number']

    try:
        await client.sign_in(phone_number, code)
        logger.info(f"Успешная авторизация аккаунта: {phone_number}")

        session_string = client.session.save()

        me = await client.get_me()

        if me is None:
            await message.answer("❌ Не удалось получить информацию об аккаунте")
            await client.disconnect()
            return

        account, bonus_applied = create_account(
            user_id=user_id,
            phone_number=phone_number,
            session_string=session_string,
            api_id=client.api_id,
            api_hash=client.api_hash
        )

        if session_data.get('proxy_id'):
            from database.database import db
            session = db.get_session()
            try:
                account.proxy_id = session_data['proxy_id']
                session.commit()
            finally:
                db.close_session(session)

        await client.disconnect()

        del user_sessions[user_id]

        caption = (
            f"✅ <b>Аккаунт успешно добавлен!</b>\n\n"
            f"📱 <b>Номер:</b> {phone_number}\n"
            f"👤 <b>Имя:</b> {me.first_name or 'Не указано'}\n"
            f"🔐 <b>2FA:</b> Включена\n\n"
        )

        if bonus_applied:
            caption += f"🎁 <b>Бонус:</b> {account.subscription_minutes} минут начислено!\n\n"

        caption += "Теперь вы можете настроить аккаунт и начать рассылку."

        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            photo=mailer_image,
            caption=caption,
            reply_markup=get_account_management_keyboard()
        )
        await state.clear()

    except PhoneCodeInvalidError:
        await message.answer(
            "❌ <b>Неверный код подтверждения</b>\n\n"
            "Проверьте код и попробуйте снова.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()

    except SessionPasswordNeededError:
        await state.set_state(AccountStates.waiting_for_password)
        await message.answer(
            "🔐 <b>Включена двухфакторная аутентификация</b>\n\n"
            "Введите пароль от двухфакторной аутентификации:"
        )

    except PhoneCodeExpiredError:
        logger.info(f"Код истек для номера {phone_number}, отправляем новый код")
        try:
            import time
            current_time = time.time()
            last_request_time = session_data.get('last_code_request_time', 0)

            if current_time - last_request_time < 60:
                await message.answer(
                    "⏰ <b>Слишком частые запросы кода</b>\n\n"
                    "Подождите минуту перед повторным запросом кода.",
                    reply_markup=get_back_to_main_keyboard()
                )
                return

            await client.send_code_request(phone_number, force_sms=False)
            session_data['last_code_request_time'] = current_time
            await message.answer(
                "⏰ <b>Код подтверждения истек</b>\n\n"
                "📱 <b>Новый код отправлен в Telegram!</b>\n\n"
                "💡 <b>Введите код из SMS или Telegram:</b>\n"
                "<b>ВНИМАНИЕ‼️</b>\n"
                "⚠️ В любое место в коде добавьте \"_\" , к примеру: 123_45",
                reply_markup=get_back_to_main_keyboard()
            )
            return
        except Exception as retry_e:
            logger.error(f"Ошибка при повторной отправке кода: {retry_e}")
            await message.answer(
                "❌ <b>Не удалось отправить новый код</b>\n\n"
                "Попробуйте начать процесс добавления аккаунта заново.",
                reply_markup=get_account_retry_keyboard()
            )
            try:
                await client.disconnect()
            except:
                pass
            if user_id in user_sessions:
                del user_sessions[user_id]
            await state.clear()
            return

    except Exception as e:
        logger.error(f"Ошибка в process_code: {e}")
        error_text = str(e).lower()

        if "phone_number_unoccupied" in error_text or "phone_number_invalid" in error_text:
            await message.answer(
                "❌ <b>Номер не зарегистрирован</b>\n\n"
                "Данный номер телефона не зарегистрирован в Telegram.\n"
                "Бот работает только с уже существующими аккаунтами.\n\n"
                "Убедитесь, что номер правильный и аккаунт зарегистрирован.",
                reply_markup=get_account_retry_keyboard()
            )
        elif "expired" in error_text or "истек" in error_text:
            try:
                await client.send_code_request(phone_number, force_sms=False)
                from keyboards.keyboards import get_code_entry_keyboard
                await message.answer(
                    "⏰ <b>Код подтверждения истек</b>\n\n"
                    "📱 <b>Новый код отправлен в Telegram!</b>\n\n"
                    "💡 <b>Введите код из SMS или Telegram:</b>\n"
                    "<b>ВНИМАНИЕ‼️</b>\n"
                    "⚠️ В любое место в коде добавьте \"_\" , к примеру: 123_45",
                    reply_markup=get_code_entry_keyboard()
                )
                return
            except Exception as retry_e:
                logger.error(f"Ошибка при повторной отправке кода в общем обработчике: {retry_e}")
        else:
            await message.answer(
                f"❌ <b>Ошибка при авторизации</b>\n\n"
                f"Не удалось авторизовать аккаунт.\n"
                f"Ошибка: {str(e)}\n\n"
                f"Убедитесь, что аккаунт существует и попробуйте позже.",
                reply_markup=get_account_retry_keyboard()
            )

        try:
            await client.disconnect()
        except:
            pass
        if user_id in user_sessions:
            del user_sessions[user_id]
        await state.clear()


@router.message(AccountStates.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    password = message.text.strip()

    user_id = str(message.from_user.id)

    if user_id not in user_sessions:
        await message.answer(
            "❌ <b>Сессия не найдена</b>\n\n"
            "Начните процесс добавления аккаунта заново.",
            reply_markup=get_account_retry_keyboard()
        )
        await state.clear()
        return

    session_data = user_sessions[user_id]
    client = session_data['client']
    phone_number = session_data['phone_number']

    try:
        await client.sign_in(password=password)

        session_string = client.session.save()

        me = await client.get_me()

        if me is None:
            await message.answer("❌ Не удалось получить информацию об аккаунте")
            await client.disconnect()
            return

        account, bonus_applied = create_account(
            user_id=user_id,
            phone_number=phone_number,
            session_string=session_string,
            api_id=client.api_id,
            api_hash=client.api_hash
        )

        if session_data.get('proxy_id'):
            from database.database import db
            session = db.get_session()
            try:
                account.proxy_id = session_data['proxy_id']
                session.commit()
            finally:
                db.close_session(session)

        await client.disconnect()

        del user_sessions[user_id]

        caption = (
            f"✅ <b>Аккаунт успешно добавлен!</b>\n\n"
            f"📱 <b>Номер:</b> {phone_number}\n"
            f"👤 <b>Имя:</b> {me.first_name or 'Не указано'}\n"
            f"🔐 <b>2FA:</b> Включена\n\n"
        )

        if bonus_applied:
            caption += f"🎁 <b>Бонус:</b> {account.subscription_minutes} минут начислено!\n\n"

        caption += "Теперь вы можете настроить аккаунт и начать рассылку."

        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            photo=mailer_image,
            caption=caption,
            reply_markup=get_account_management_keyboard()
        )
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка в process_password: {e}")
        await message.answer(
            f"❌ <b>Ошибка при авторизации</b>\n\n"
            f"Неверный пароль или произошла ошибка.\n"
            f"Попробуйте еще раз или обратитесь к администратору.",
            reply_markup=get_account_retry_keyboard()
        )

        try:
            await client.disconnect()
        except:
            pass
        if user_id in user_sessions:
            del user_sessions[user_id]
        await state.clear()

@router.callback_query(F.data.startswith("account_actions_"))
async def account_actions(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        if not account.session_string:
            logger.warning(f"Аккаунт {account.phone_number} не имеет session_string, показываем меню проблем")
            from keyboards.keyboards import get_account_problem_keyboard
            mailer_image = FSInputFile("img_static/mailer.png")
            await callback.bot.edit_message_media(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                media=InputMediaPhoto(
                    media=mailer_image,
                    caption=f"❌ <b>Аккаунт не авторизован</b> <code>{account.phone_number}</code>\n\n"
                           f"Аккаунт не прошел авторизацию или сессия была удалена.\n\n"
                           f"Выберите действие:",
                    parse_mode="HTML"
                ),
                reply_markup=get_account_problem_keyboard(account_id)
            )
            try:
                await callback.answer()
            except Exception as e:
                logger.error(f"Ошибка при ответе на callback: {e}")
            return

        status = "🟢 Активен" if account.is_active else "🔴 Неактивен"
        if account.subscription_minutes > 0:
            subscription = f"{account.subscription_minutes} минут ({format_minutes_to_readable(account.subscription_minutes)})"
        else:
            subscription = "Нет подписки"

        text = f"<b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
        text += f"<b>Статус:</b> {status}\n"
        text += f"<b>Подписка:</b> {subscription}"

        if account.is_active:
            text += f"\n\n🚀 Рассылка запущена для аккаунта <code>{account.phone_number}</code>"

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=get_account_actions_keyboard(account_id, is_active=account.is_active, subscription_minutes=account.subscription_minutes)
        )
    finally:
        db.close_session(session)

    try:
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при ответе на callback в функции account_actions: {e}")

@router.callback_query(F.data.startswith("account_settings_") & ~F.data.startswith("account_settings_page_"))
async def account_settings(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        proxy_config = None
        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                from utils.proxy_validator import get_telethon_proxy_config
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)
        try:
            from telethon.tl.functions.users import GetFullUserRequest
            client = TelegramClient(
                StringSession(account.session_string),
                account.api_id,
                account.api_hash,
                proxy=proxy_config,
                system_version="4.16.30-vxCUSTOM",
                device_model="Desktop",
                app_version="4.16.30"
            )
            await client.connect()
            me = await client.get_me()

            if me is None:
                await client.disconnect()
                from keyboards.keyboards import get_account_problem_keyboard
                await safe_edit_message(
                    callback.message,
                    f"❌ <b>Проблема с аккаунтом</b> <code>{account.phone_number}</code>\n\n"
                    f"Не удалось подключиться к аккаунту. Возможные причины:\n"
                    f"• Сессия недействительна\n"
                    f"• Аккаунт заблокирован\n"
                    f"• Проблемы с сетью\n\n"
                    f"Выберите действие:",
                    get_account_problem_keyboard(account_id)
                )
                return

            full = await client(GetFullUserRequest(me.id))
            await client.disconnect()
            name = me.first_name or "—"
            username = me.username or "—"
            bio = getattr(full, 'about', None)
            if not bio and hasattr(full, 'full_user'):
                bio = getattr(full.full_user, 'about', None)
            if not bio and hasattr(full, 'users') and full.users:
                bio = getattr(full.users[0], 'about', None)
            if not bio:
                bio = "—"
            photo_status = "✅" if me.photo else "❌"
            text = (
                f"👤 <b>Профиль аккаунта</b> <code>{account.phone_number}</code>\n\n"
                f"Имя: <b>{name}</b>\n"
                f"Username: <b>@{username}</b>\n"
                f"Биография: <b>{bio}</b>\n"
                f"Фото профиля: {photo_status}\n\n"
                "Выберите, что хотите изменить:"
            )
            from keyboards.keyboards import get_account_profile_keyboard
            await safe_edit_message(
                callback.message,
                text,
                get_account_profile_keyboard(account_id)
            )
        except Exception as e:
            from keyboards.keyboards import get_account_problem_keyboard
            await safe_edit_message(
                callback.message,
                f"❌ <b>Ошибка подключения к аккаунту</b> <code>{account.phone_number}</code>\n\n"
                f"Произошла ошибка: {str(e)}\n\n"
                f"Выберите действие:",
                get_account_problem_keyboard(account_id)
            )
            return
    finally:
        db.close_session(session)
    await callback.answer()


@router.callback_query(F.data.startswith("start_spam_"))
async def start_spam(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        if account.subscription_minutes <= 0:
            await callback.answer("❌ Нет активной подписки")
            return

        total_enabled_groups = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.is_enabled == True
        ).count()
        groups_with_messages = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.is_enabled == True,
            GroupSettings.custom_message.isnot(None)
        ).count()

        total_enabled_super_groups = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.is_enabled == True
        ).count()
        super_groups_with_messages = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.is_enabled == True,
            SuperGroup.custom_message.isnot(None)
        ).count()

        total_all = total_enabled_groups + total_enabled_super_groups
        total_with_messages = groups_with_messages + super_groups_with_messages

        if total_all == 0:
            await callback.answer("❌ Нет активных групп или тем для рассылки")
            return

        if total_with_messages == 0:
            if not account.default_message:
                await callback.answer("❌ Не настроены ни индивидуальные сообщения для групп/тем, ни общее сообщение аккаунта")
                return
            else:
                await callback.answer("✅ Рассылка запущена!")
        elif total_with_messages < total_all:
            if account.default_message:
                await callback.answer(f"✅ Рассылка запущена!")
            else:
                await callback.answer(f"✅ Рассылка запущена!")
        else:
            await callback.answer("✅ Рассылка запущена!")

        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                is_valid, error = await validate_proxy_for_telethon(proxy_data)
                if not is_valid:
                    await callback.answer(f"❌ Прокси не работает: {error}")
                    return
        account.is_active = True
        session.commit()


        status = "🟢 Активен"
        subscription = f"{account.subscription_minutes} минут ({format_minutes_to_readable(account.subscription_minutes)})" if account.subscription_minutes > 0 else "Нет подписки"
        text = f"<b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
        text += f"<b>Статус:</b> {status}\n"
        text += f"<b>Подписка:</b> {subscription}\n\n"
        text += f"🚀 Рассылка запущена для аккаунта <code>{account.phone_number}</code>"
        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=get_account_actions_keyboard(account_id, is_active=True, subscription_minutes=account.subscription_minutes)
        )
    finally:
        db.close_session(session)
    await callback.answer()

@router.callback_query(F.data.startswith("stop_spam_"))
async def stop_spam(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        account.is_active = False
        session.commit()


        status = "🔴 Неактивен"
        subscription = f"{account.subscription_minutes} минут ({format_minutes_to_readable(account.subscription_minutes)})" if account.subscription_minutes > 0 else "Нет подписки"
        text = f"<b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
        text += f"<b>Статус:</b> {status}\n"
        text += f"<b>Подписка:</b> {subscription}\n\n"
        text += f"⏹️ Рассылка остановлена для аккаунта <code>{account.phone_number}</code>"
        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=get_account_actions_keyboard(account_id, is_active=False, subscription_minutes=account.subscription_minutes)
        )
    finally:
        db.close_session(session)
    await callback.answer()

@router.callback_query(F.data.startswith("buy_subscription_"))
async def buy_subscription(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])

    telegram_id = str(callback.from_user.id)
    from database.database import get_user_by_telegram_id
    user = get_user_by_telegram_id(telegram_id)

    if not user:
        await callback.answer("❌ Пользователь не найден")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        text = f"💎 <b>Покупка подписки</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"Выберите период подписки:"

        await safe_edit_message(
            callback.message,
            text,
            get_subscription_periods_keyboard(account_id)
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("account_promo_"))
async def account_promo_handler(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        text = f"🎫 <b>Активация промо-кода</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"ℹ️ <i>Введите промо-код для активации подписки или получения скидки.</i>\n\n" \
               f"✏️ Отправьте промо-код:"

        await safe_edit_message(
            callback.message,
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data=f"buy_subscription_{account_id}")]
                ]
            )
        )

        await state.set_state(AccountStates.waiting_for_account_promo)
        await state.update_data(account_id=account_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("account_sub_"))
async def buy_account_subscription(callback: CallbackQuery):
    parts = callback.data.split("_")
    days = int(parts[2])
    account_id = int(parts[3])

    config = configparser.ConfigParser()
    config.read('config.ini')

    price_map = {
        1: float(config.get('PRICING', 'day_1', fallback='1.5')),
        7: float(config.get('PRICING', 'day_7', fallback='10')),
        14: float(config.get('PRICING', 'day_14', fallback='19')),
        30: float(config.get('PRICING', 'day_30', fallback='35'))
    }

    price = price_map.get(days, 1.5)

    telegram_id = str(callback.from_user.id)
    from database.database import get_user_by_telegram_id
    user = get_user_by_telegram_id(telegram_id)

    if not user:
        await callback.answer("❌ Пользователь не найден")
        return

    if user.balance < price:
        await safe_edit_message(
            callback.message,
            f"❌ <b>Недостаточно средств на балансе</b>\n\n"
            f"💰 <b>Ваш баланс:</b> {user.balance}$\n"
            f"💎 <b>Стоимость подписки:</b> {price}$\n"
            f"📊 <b>Не хватает:</b> {price - user.balance}$",
            get_insufficient_balance_keyboard(account_id)
        )
        await callback.answer()
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, User

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        db_user = session.query(User).filter(User.telegram_id == telegram_id).first()
        if not db_user:
            await callback.answer("❌ Пользователь не найден")
            return

        db_user.balance -= price

        subscription_minutes = days * 24 * 60
        account.subscription_minutes += subscription_minutes

        session.commit()

        await safe_edit_message(
            callback.message,
            f"✅ <b>Подписка успешно приобретена!</b>\n\n"
            f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
            f"📅 <b>Период:</b> {days} дней\n"
            f"💰 <b>Стоимость:</b> {price}$\n"
            f"💳 <b>Остаток баланса:</b> {db_user.balance}$\n"
            f"⏱️ <b>Добавлено минут:</b> {subscription_minutes} ({format_minutes_to_readable(subscription_minutes)})\n"
            f"🔄 <b>Всего минут:</b> {account.subscription_minutes} ({format_minutes_to_readable(account.subscription_minutes)})",
            get_account_actions_keyboard(account_id, is_active=account.is_active, subscription_minutes=account.subscription_minutes)
        )

    except Exception as e:
        logger.error(f"Ошибка в process_subscription_purchase: {e}")
        await callback.answer("❌ Ошибка при покупке подписки")
        session.rollback()
    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("delete_account_"))
async def delete_account_confirm(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Удалить", callback_data=f"confirm_delete_{account_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="list_accounts")]
            ]
        )
        await safe_edit_message(
            callback.message,
            f"⚠️ <b>Подтвердите удаление аккаунта</b>\n\n"
            f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
            f"⏱️ <b>Подписка:</b> {account.subscription_minutes} мин\n\n"
            f"❗️ <b>Это действие нельзя отменить!</b>\n"
            f"Все данные аккаунта будут удалены.",
            keyboard
        )
        await callback.answer()
    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, MessageLog, GroupSettings, AutoresponderDialog, SuperGroup, SelectedTopics
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        session.query(MessageLog).filter(MessageLog.account_id == account_id).delete()
        session.query(GroupSettings).filter(GroupSettings.account_id == account_id).delete()
        session.query(AutoresponderDialog).filter(AutoresponderDialog.account_id == account_id).delete()
        session.query(SuperGroup).filter(SuperGroup.account_id == account_id).delete()
        session.query(SelectedTopics).filter(SelectedTopics.account_id == account_id).delete()

        session.delete(account)
        session.commit()

        telegram_id = str(callback.from_user.id)
        from database.database import get_user_accounts
        updated_accounts = get_user_accounts(telegram_id)

        await safe_edit_message(
            callback.message,
            "✅ <b>Аккаунт успешно удалён!</b>",
            get_account_list_keyboard(updated_accounts)
        )
        await callback.answer("Аккаунт удалён", show_alert=False)
    except Exception as e:
        logger.error(f"Ошибка при удалении аккаунта: {e}")
        await callback.answer("❌ Ошибка при удалении аккаунта")
        session.rollback()
    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("account_groups_"))
async def show_account_groups(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return
        await safe_edit_message(
            callback.message,
            f"🔄 <b>Загружаем группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
            "⏳ Получаем все диалоги...\n"
            "🔍 Фильтруем группы и супергруппы...\n"
            "🔍 Проверяем права на отправку сообщений...\n"
            "Подождите, это может занять некоторое время...",
            None
        )

        groups = await get_account_groups(account)

        if not groups:
            await safe_edit_message(
                callback.message,
                f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n"
                "❌ <b>Доступные группы не найдены</b>\n\n"
                "Возможные причины:\n"
                "• Аккаунт не состоит в группах/каналах\n"
                "• Аккаунт заблокирован в группах\n"
                "• Ошибка подключения к Telegram\n"
                "• Проблемы с прокси (если используется)\n\n"
                "💡 <i>Проверьте подключение аккаунта и попробуйте снова</i>",
                get_account_actions_keyboard(account_id, is_active=account.is_active, subscription_minutes=account.subscription_minutes)
            )
            return

        selected_group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.is_enabled == True
        ).all()
        selected_groups = []
        for setting in selected_group_settings:
            try:
                group_id_int = int(setting.group_id)
                selected_groups.append(group_id_int)
            except ValueError:
                logger.warning(f"Не удалось преобразовать group_id '{setting.group_id}' в число")
                continue

        await state.update_data(
            account_id=account_id,
            groups=groups,
            selected_groups=selected_groups
        )

        await safe_edit_message(
            callback.message,
            f"👥 <b>Группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
            f"📊 <b>Найдено доступных групп:</b> {len(groups)}\n"
            f"✅ <b>Выбрано:</b> {len(selected_groups)}\n\n"
            "💡 <i>Показаны только группы, где аккаунт может отправлять сообщения</i>\n\n"
            "Выберите группы для рассылки:",
            get_groups_selection_keyboard_v2(groups, account_id, 0, selected_groups)
        )

    finally:
        db.close_session(session)

    await callback.answer()


@router.callback_query(F.data.startswith("save_groups_"))
async def save_groups_selection(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])

    data = await state.get_data()
    groups = data.get('groups', [])
    selected_groups = data.get('selected_groups', [])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        groups_dict = {g['id']: g for g in groups}

        existing_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id
        ).all()
        existing_dict = {int(setting.group_id): setting for setting in existing_settings}

        for group_id in selected_groups:
            if group_id in existing_dict:
                existing_dict[group_id].is_enabled = True
            else:
                from utils.group_id_helper import normalize_group_id
                normalized_group_id = normalize_group_id(group_id)

                double_check = session.query(GroupSettings).filter(
                    GroupSettings.account_id == account_id,
                    GroupSettings.group_id == normalized_group_id
                ).first()

                if double_check:
                    double_check.is_enabled = True
                    existing_dict[group_id] = double_check
                else:
                    group_info = groups_dict.get(group_id, {})
                    new_setting = GroupSettings(
                        account_id=account_id,
                        group_id=normalized_group_id,
                        group_name=group_info.get('title', 'Unknown'),
                        is_enabled=True,
                        custom_message=account.default_message,
                        custom_interval=None,
                        slowmode_seconds=group_info.get('slowmode_seconds', 0),
                        slowmode_minutes=group_info.get('slowmode_minutes', 0)
                    )
                    session.add(new_setting)

        for group_id, setting in existing_dict.items():
            if group_id not in selected_groups:
                setting.is_enabled = False

        session.commit()

        await state.clear()

        await safe_edit_message(
            callback.message,
            f"✅ <b>Настройки групп сохранены</b>\n\n"
            f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
            f"✅ <b>Активных групп:</b> {len(selected_groups)}\n\n"
            "Теперь вы можете настроить индивидуальные сообщения для каждой группы.",
            get_account_actions_keyboard(account_id, is_active=account.is_active, subscription_minutes=account.subscription_minutes)
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении групп: {e}")
        await callback.answer("❌ Ошибка при сохранении")
        session.rollback()
    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("group_settings_"))
async def group_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = parts[3]
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return
        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()
        if not group_settings:
            await callback.answer("❌ Настройки группы не найдены")
            return

        text = build_group_settings_text(account_id, group_id)

        try:
            mailer_image = FSInputFile("img_static/mailer.png")
            await callback.bot.edit_message_media(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
                reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True)
            )
        except TelegramBadRequest as e:
            try:
                await callback.message.delete()
            except:
                pass

            mailer_image = FSInputFile("img_static/mailer.png")
            await callback.bot.send_photo(
                chat_id=callback.message.chat.id,
                photo=mailer_image,
                caption=text,
                reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True),
                parse_mode="HTML"
            )
    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("group_message_"))
async def group_message_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = parts[3]

    from database.database import db
    session = db.get_session()
    try:
        from database.models import GroupSettings

        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()

        if not group_settings:
            await callback.answer("❌ Настройки группы не найдены")
            return

        from utils.emoji_processor import html_with_tg_emoji_to_plain_text
        current_raw = group_settings.custom_message or "Не настроено"
        current_message = html_with_tg_emoji_to_plain_text(current_raw)
        safe_current_message = escape_html_for_pre(current_message)
        truncated_current_message = truncate_message_for_display(safe_current_message)

        text = f"📝 <b>Настройка сообщения для группы</b>\n\n" \
               f"👥 <b>Группа ID:</b> <code>{group_id}</code>\n\n" \
               f"📝 <b>Текущее сообщение:</b>\n<pre>{truncated_current_message}</pre>\n\n" \
               f"✏️ Отправьте новое сообщение или '0' для удаления:"

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=text,
            reply_markup=get_group_back_keyboard(account_id, group_id),
            parse_mode="HTML"
        )

        await state.set_state(AccountStates.waiting_for_group_message)
        await state.update_data(account_id=account_id, group_id=group_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("group_media_"))
async def group_media_settings(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = parts[3]

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings

        account = session.query(Account).filter(Account.id == account_id).first()
        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()

        if not account or not group_settings:
            await callback.answer("❌ Аккаунт или группа не найдены")
            return

        current_media = "❌ Нет медиа"
        if account.default_photo:
            current_media = "📸 Фото загружено"
        elif account.default_gif:
            current_media = "🎬 GIF загружен"
        elif account.default_video:
            current_media = "🎥 Видео загружено"

        text = f"🖼️ <b>Настройка медиа для группы</b>\n\n" \
               f"👥 <b>Группа ID:</b> <code>{group_id}</code>\n\n" \
               f"🖼️ <b>Текущее медиа:</b> {current_media}\n\n" \
               f"📱 Отправьте фото, GIF или видео для замены, или '0' для удаления медиа:"

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=text,
            reply_markup=get_group_back_keyboard(account_id, group_id),
            parse_mode="HTML"
        )

        await state.set_state(AccountStates.waiting_for_group_media)
        await state.update_data(account_id=account_id, group_id=group_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("group_interval_"))
async def group_interval_settings(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = parts[3]

    from database.database import db
    session = db.get_session()
    try:
        from database.models import GroupSettings

        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()

        if not group_settings:
            await callback.answer("❌ Настройки группы не найдены")
            return

        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        default_interval = account.message_interval if account else 60
        current_interval = group_settings.custom_interval or default_interval

        if group_settings.custom_interval:
            interval_source = f"{current_interval} минут (индивидуальный)"
        else:
            interval_source = f"{current_interval} минут (общий)"

        text = f"⏱️ <b>Настройка интервала для группы</b>\n\n" \
               f"👥 <b>Группа ID:</b> <code>{group_id}</code>\n\n" \
               f"⏱️ <b>Текущий интервал:</b> {interval_source}"

        slowmode_minutes = group_settings.slowmode_minutes or 0
        if slowmode_minutes > 0:
            text += f"\n🐌 <b>Slow mode группы:</b> {slowmode_minutes} минут"

            if current_interval < slowmode_minutes:
                text += f"\n\n⚠️ <b>Внимание:</b> Текущий интервал меньше slow mode!"

        text += "\n\nОтправьте новый интервал в минутах (от 1 до 1440):"

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=text,
            reply_markup=get_group_interval_keyboard(account_id, group_id, group_settings.custom_interval is not None),
            parse_mode="HTML"
        )

        await state.set_state(AccountStates.waiting_for_group_interval)
        await state.update_data(account_id=account_id, group_id=group_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("group_escrow_"))
async def group_escrow_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = parts[3]

    await state.update_data(
        current_group_id=group_id,
        current_account_id=account_id
    )

    await state.set_state(AccountStates.waiting_for_group_escrow)

    try:
        await callback.message.delete()
    except:
        pass

    mailer_image = FSInputFile("img_static/mailer.png")
    await callback.bot.send_photo(
        chat_id=callback.message.chat.id,
        photo=mailer_image,
        caption=f"💯 <b>Настройка гаранта для группы</b>\n\n"
                f"👥 <b>Группа ID:</b> <code>{group_id}</code>\n\n"
                "Отправьте @username гаранта:\n\n"
                "💡 <i>Для удаления гаранта отправьте 0</i>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"group_settings_{account_id}_{group_id}"
                )]
            ]
        ),
        parse_mode="HTML"
    )

    await callback.answer()

@router.message(AccountStates.waiting_for_group_escrow)
async def process_group_escrow(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('current_account_id')
    group_id = data.get('current_group_id')

    if not account_id or not group_id:
        await message.answer("❌ Ошибка: данные не найдены")
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import GroupSettings

        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()

        if not group_settings:
            await message.answer("❌ Настройки группы не найдены")
            await state.clear()
            return

        if message.text.strip() == "0":
            group_settings.escrow_username = None

            if group_settings.custom_message:
                lines = group_settings.custom_message.split('\n')
                filtered_lines = []
                for line in lines:
                    if not (line.strip().startswith('<b>escrow/гарант :') or
                            line.strip().startswith('escrow/гарант :')):
                        filtered_lines.append(line)

                while filtered_lines and not filtered_lines[-1].strip():
                    filtered_lines.pop()

                group_settings.custom_message = '\n'.join(filtered_lines) if filtered_lines else None

            session.commit()

            try:
                await message.bot.delete_message(message.chat.id, message.message_id - 1)
            except:
                pass
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

            text = build_group_settings_text(account_id, group_id)

            mailer_image = FSInputFile("img_static/mailer.png")
            await message.answer_photo(
                photo=mailer_image,
                caption=text,
                reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True),
                parse_mode="HTML"
            )

        else:
            escrow_username = message.text.strip()

            if not escrow_username.startswith('@'):
                escrow_username = '@' + escrow_username

            from database.models import Account
            account = session.query(Account).filter(Account.id == account_id).first()

            has_group_message = group_settings.custom_message
            has_common_message = account and account.default_message

            if not has_group_message and not has_common_message:
                await message.answer("❌ Сначала настройте сообщение для группы или общее сообщение аккаунта")
                await state.clear()
                return

            if group_settings.custom_message:
                lines = group_settings.custom_message.split('\n')
                filtered_lines = []
                for line in lines:
                    if not (line.strip().startswith('<b>escrow/гарант :') or
                            line.strip().startswith('escrow/гарант :')):
                        filtered_lines.append(line)

                while filtered_lines and not filtered_lines[-1].strip():
                    filtered_lines.pop()

                filtered_lines.append('')
                filtered_lines.append(f'<b>escrow/гарант : {escrow_username}</b>')

                group_settings.custom_message = '\n'.join(filtered_lines)

            group_settings.escrow_username = escrow_username
            session.commit()

            logger.info(f"💾 Добавлен гарант для группы: '{escrow_username}'")

            try:
                await message.bot.delete_message(message.chat.id, message.message_id - 1)
            except:
                pass
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

            text = build_group_settings_text(account_id, group_id)

            mailer_image = FSInputFile("img_static/mailer.png")
            await message.answer_photo(
                photo=mailer_image,
                caption=text,
                reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True),
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка при сохранении гаранта группы: {e}")
        await message.answer("❌ Ошибка при сохранении гаранта")
        await state.clear()
    finally:
        db.close_session(session)

    await state.clear()

@router.message(AccountStates.waiting_for_group_message)
async def process_group_message(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')
    group_id = data.get('group_id')
    super_group_id = data.get('super_group_id')

    if not account_id or (not group_id and not super_group_id):
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        if super_group_id:
            from database.models import SuperGroup
            super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()
            if super_group:
                if message.text.strip() == "0":
                    super_group.custom_message = None
                    session.commit()
                else:
                    logger.info(f"👤 Пользовательский ввод для супер группы: '{message.text}'")

                    from utils.markdown_converter import safe_convert_markdown_to_html
                    markdown_converted = safe_convert_markdown_to_html(message.text.strip())

                    if message.entities:
                        from utils.emoji_processor import correct_entity_positions
                        corrected_entities = correct_entity_positions(message)
                        logger.info(f"📋 Сообщение содержит {len(corrected_entities)} сущностей")
                        for i, entity in enumerate(corrected_entities):
                            if entity.type == "custom_emoji":
                                logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}")
                            else:
                                logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}-{entity.offset + entity.length}")
                            if entity.type == "custom_emoji":
                                logger.info(f"  🎭 ID пользовательского эмодзи: {entity.custom_emoji_id}")

                        from utils.text_formatter_wrapper import format_message_with_nodejs
                        processed_message = format_message_with_nodejs(message)
                        super_group.custom_message = processed_message
                    else:
                        super_group.custom_message = markdown_converted

                    session.commit()

                    logger.info(f"💾 Сохранено сообщение супер группы: '{super_group.custom_message}'")

                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                status = "✅ Включена" if super_group.is_enabled else "❌ Отключена"
                text = f"⚙️ <b>Настройки супер группы</b>\n\n📱 Аккаунт: <code>{account_id}</code>\n👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n📊 Статус: {status}\n\nВыберите настройку для изменения:"

                await message.answer_photo(
                    photo=mailer_image,
                    caption=text,
                    reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "❌ Супер группа не найдена",
                    reply_markup=get_main_menu_keyboard()
                )
        else:
            from database.models import GroupSettings
            group_settings = session.query(GroupSettings).filter(
                GroupSettings.account_id == account_id,
                GroupSettings.group_id == group_id
            ).first()
            if group_settings:
                if message.text.strip() == "0":
                    group_settings.custom_message = None
                    session.commit()
                else:
                    logger.info(f"👤 Пользовательский ввод для группового сообщения: '{message.text}'")

                    from utils.markdown_converter import safe_convert_markdown_to_html
                    markdown_converted = safe_convert_markdown_to_html(message.text.strip())

                    if message.entities:
                        from utils.emoji_processor import correct_entity_positions
                        corrected_entities = correct_entity_positions(message)
                        logger.info(f"📋 Сообщение содержит {len(corrected_entities)} сущностей")
                        for i, entity in enumerate(corrected_entities):
                            if entity.type == "custom_emoji":
                                logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}")
                            else:
                                logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}-{entity.offset + entity.length}")
                            if entity.type == "custom_emoji":
                                logger.info(f"  🎭 ID пользовательского эмодзи: {entity.custom_emoji_id}")

                        from utils.text_formatter_wrapper import format_message_with_nodejs
                        processed_message = format_message_with_nodejs(message)
                        group_settings.custom_message = processed_message
                    else:
                        group_settings.custom_message = markdown_converted

                    session.commit()

                    logger.info(f"💾 Сохранено групповое сообщение: '{group_settings.custom_message}'")

                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                text = build_group_settings_text(account_id, group_id)
                await message.answer_photo(
                    photo=mailer_image,
                    caption=text,
                    reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True),
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "❌ Настройки группы не найдены",
                    reply_markup=get_main_menu_keyboard()
                )
    except Exception as e:
        logger.error(f"Ошибка при обновлении сообщения: {e}")
        await message.answer(
            "❌ Ошибка при сохранении сообщения",
            reply_markup=get_main_menu_keyboard()
        )
        session.rollback()
    finally:
        db.close_session(session)
    await state.clear()

@router.message(AccountStates.waiting_for_group_media)
async def process_group_media(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')
    group_id = data.get('group_id')
    super_group_id = data.get('super_group_id')
    media_type = data.get('media_type')

    if not account_id or (not group_id and not super_group_id):
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        if super_group_id:
            from database.models import Account, SuperGroup
            account = session.query(Account).filter(Account.id == account_id).first()
            super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

            if not account or not super_group:
                await message.answer("❌ Аккаунт или супер группа не найдены", reply_markup=get_main_menu_keyboard())
                await state.clear()
                return

            if message.text and message.text.strip() == "0":
                super_group.custom_photo = None
                super_group.custom_gif = None
                super_group.custom_video = None
                session.commit()
                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                status = "✅ Включена" if super_group.is_enabled else "❌ Отключена"
                text = f"⚙️ <b>Настройки супер группы</b>\n\n📱 Аккаунт: <code>{account.phone_number}</code>\n👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n📊 Статус: {status}\n\nВыберите настройку для изменения:"

                await message.answer_photo(
                    photo=mailer_image,
                    caption=text,
                    reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
                    parse_mode="HTML"
                )
            else:
                media_data = None
                if message.photo:
                    media_data = message.photo[-1].file_id
                    media_bytes = await message.bot.download_file_by_id(media_data)
                    media_data = media_bytes.read()
                elif message.animation:
                    media_data = message.animation.file_id
                    media_bytes = await message.bot.download_file_by_id(media_data)
                    media_data = media_bytes.read()
                elif message.video:
                    media_data = message.video.file_id
                    media_bytes = await message.bot.download_file_by_id(media_data)
                    media_data = media_bytes.read()
                else:
                    await message.answer("❌ Поддерживаются только фото, GIF и видео", reply_markup=get_main_menu_keyboard())
                    await state.clear()
                    return

                if media_type == "photo" and message.photo:
                    super_group.custom_photo = media_data
                elif media_type == "gif" and message.animation:
                    super_group.custom_gif = media_data
                elif media_type == "video" and message.video:
                    super_group.custom_video = media_data

                session.commit()

                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                status = "✅ Включена" if super_group.is_enabled else "❌ Отключена"
                text = f"⚙️ <b>Настройки супер группы</b>\n\n📱 Аккаунт: <code>{account.phone_number}</code>\n👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n📊 Статус: {status}\n\nВыберите настройку для изменения:"

                await message.answer_photo(
                    photo=mailer_image,
                    caption=text,
                    reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
                    parse_mode="HTML"
                )
        else:
            from database.models import Account, GroupSettings
            account = session.query(Account).filter(Account.id == account_id).first()
            group_settings = session.query(GroupSettings).filter(
                GroupSettings.account_id == account_id,
                GroupSettings.group_id == group_id
            ).first()
            if not account or not group_settings:
                await message.answer("❌ Аккаунт или группа не найдены", reply_markup=get_main_menu_keyboard())
                await state.clear()
                return
            if message.text and message.text.strip() == "0":
                group_settings.custom_photo = None
                group_settings.custom_gif = None
                group_settings.custom_video = None
                session.commit()
                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                text = build_group_settings_text(account_id, group_id)
                await message.answer_photo(
                    photo=mailer_image,
                    caption=text,
                    reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True),
                    parse_mode="HTML"
                )
                await state.clear()
                return
        media_type = None
        media_data = None
        if message.photo:
            media_type = "photo"
            file_info = await message.bot.get_file(message.photo[-1].file_id)
            media_data = await message.bot.download_file(file_info.file_path)
        elif message.animation:
            media_type = "gif"
            file_info = await message.bot.get_file(message.animation.file_id)
            media_data = await message.bot.download_file(file_info.file_path)
        elif message.video:
            media_type = "video"
            file_info = await message.bot.get_file(message.video.file_id)
            media_data = await message.bot.download_file(file_info.file_path)
        else:
            await message.answer(
                "❌ Неподдерживаемый тип медиа. Отправьте фото, GIF или видео.",
                reply_markup=get_main_menu_keyboard()
            )
            return
        group_settings.custom_photo = None
        group_settings.custom_gif = None
        group_settings.custom_video = None
        if media_type == "photo":
            group_settings.custom_photo = media_data.read()
        elif media_type == "gif":
            group_settings.custom_gif = media_data.read()
        elif media_type == "video":
            group_settings.custom_video = media_data.read()
        session.commit()
        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass
        mailer_image = FSInputFile("img_static/mailer.png")
        text = build_group_settings_text(account_id, group_id)
        await message.answer_photo(
            photo=mailer_image,
            caption=text,
            reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True),
            parse_mode="HTML"
        )
        await state.clear()
        return
    except Exception as e:
        logger.error(f"Ошибка при обновлении группового медиа: {e}")
        mailer_image = FSInputFile("img_static/mailer.png")
        try:
            await message.answer_photo(
                photo=mailer_image,
                caption="❌ Ошибка при сохранении медиа",
                reply_markup=get_main_menu_keyboard()
            )
        except:
            await message.answer(
                "❌ Ошибка при сохранении медиа",
                reply_markup=get_main_menu_keyboard()
            )
        session.rollback()
    finally:
        db.close_session(session)

@router.message(AccountStates.waiting_for_group_interval)
async def process_group_interval(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')
    group_id = data.get('group_id')
    super_group_id = data.get('super_group_id')

    if not account_id or (not group_id and not super_group_id):
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        if super_group_id:
            from database.models import SuperGroup
            super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

            if not super_group:
                await message.answer("❌ Супер группа не найдена", reply_markup=get_main_menu_keyboard())
                await state.clear()
                return

            if message.text.strip() == "0":
                super_group.custom_interval = None
                session.commit()

                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                text = build_super_group_settings_text(account_id, super_group_id)
                await message.answer_photo(
                    photo=mailer_image,
                    caption=text,
                    reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
                    parse_mode="HTML"
                )
                await state.clear()
                return

            try:
                interval = int(message.text.strip())
                if interval < 1 or interval > 1440:
                    await message.answer("❌ Интервал должен быть от 1 до 1440 минут")
                    return

                super_group.custom_interval = interval
                session.commit()

                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                text = build_super_group_settings_text(account_id, super_group_id)
                await message.answer_photo(
                    photo=mailer_image,
                    caption=text,
                    reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
                    parse_mode="HTML"
                )
                await state.clear()
                return

            except ValueError:
                await message.answer("❌ Введите корректное число")
                return

        else:
            from database.models import GroupSettings
            group_settings = session.query(GroupSettings).filter(
                GroupSettings.account_id == account_id,
                GroupSettings.group_id == group_id
            ).first()

            if not group_settings:
                await message.answer("❌ Настройки группы не найдены", reply_markup=get_main_menu_keyboard())
                await state.clear()
                return

            if message.text.strip() == "0":
                group_settings.custom_interval = None
                session.commit()

                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                text = build_group_settings_text(account_id, group_id)
                await message.answer_photo(
                    mailer_image,
                    caption=text,
                    reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True),
                    parse_mode="HTML"
                )
                await state.clear()
                return

            try:
                interval = int(message.text)
                if interval < 1 or interval > 1440:
                    await message.answer("❌ Интервал должен быть от 1 до 1440 минут или '0' для сброса", reply_markup=get_main_menu_keyboard())
                    await state.clear()
                    return

                slowmode_minutes = group_settings.slowmode_minutes or 0
                if slowmode_minutes > 0 and interval < slowmode_minutes:
                    text = f"⚠️ <b>Предупреждение</b>\n\n" \
                           f"👥 <b>Группа ID:</b> <code>{group_id}</code>\n\n" \
                           f"🐌 <b>Slow mode группы:</b> {slowmode_minutes} минут\n" \
                           f"⏱️ <b>Ваш интервал:</b> {interval} минут\n\n" \
                           f"❌ <b>Ошибка:</b> Интервал не может быть меньше slow mode группы!\n\n" \
                           f"Укажите интервал не менее {slowmode_minutes} минут."

                    keyboard = get_slowmode_warning_keyboard(account_id, group_id, interval)
                    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
                    await state.clear()
                    return

                group_settings.custom_interval = interval
                session.commit()

                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                mailer_image = FSInputFile("img_static/mailer.png")
                text = build_group_settings_text(account_id, group_id)
                await message.answer_photo(
                    mailer_image,
                    caption=text,
                    reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True),
                    parse_mode="HTML"
                )
                await state.clear()
                return

            except ValueError:
                await message.answer("❌ Введите корректное число или '0' для сброса", reply_markup=get_main_menu_keyboard())
                await state.clear()
                return

    except Exception as e:
        logger.error(f"Ошибка в process_group_interval: {e}")
        await message.answer("❌ Ошибка при обработке интервала", reply_markup=get_main_menu_keyboard())
        await state.clear()
    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("export_session_"))
async def export_session_callback(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    telegram_id = str(callback.from_user.id)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(
            Account.id == account_id,
            Account.user_id == telegram_id
        ).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден", show_alert=True)
            return

        if not account.session_string:
            await callback.answer("❌ Сессия аккаунта не найдена", show_alert=True)
            return

        import tempfile
        import os

        temp_dir = tempfile.gettempdir()
        session_filename = f"{account.phone_number.replace('+', '')}.session"
        temp_session_path = os.path.join(temp_dir, f"temp_{telegram_id}_{session_filename}")

        try:
            string_session = StringSession(account.session_string)
            temp_client = TelegramClient(
                string_session,
                account.api_id,
                account.api_hash
            )

            await temp_client.connect()

            if not await temp_client.is_user_authorized():
                await temp_client.disconnect()
                await callback.answer("❌ Сессия недействительна", show_alert=True)
                return

            me = await temp_client.get_me()
            await temp_client.disconnect()

            file_client = TelegramClient(
                temp_session_path,
                account.api_id,
                account.api_hash
            )

            await file_client.connect()

            if hasattr(string_session, '_dc_id') and string_session._dc_id:
                file_client.session.set_dc(
                    string_session._dc_id,
                    string_session._server_address,
                    string_session._port
                )
                file_client.session.auth_key = string_session._auth_key
                file_client.session.save()

            await file_client.disconnect()

            with open(temp_session_path, 'rb') as f:
                session_file_data = f.read()

            os.remove(temp_session_path)

            from aiogram.types import BufferedInputFile

            file = BufferedInputFile(session_file_data, filename=session_filename)

            await callback.message.answer_document(
                document=file,
                caption=(
                    f"📁 <b>Экспорт сессии аккаунта</b>\n\n"
                    f"📱 <b>Номер:</b> {account.phone_number}\n"
                    f"👤 <b>Имя:</b> {account.profile_name or 'Не указано'}\n\n"
                    f"⚠️ <b>ВАЖНО:</b>\n"
                    f"• Никому не передавайте этот файл\n"
                    f"• Файл содержит полный доступ к вашему аккаунту\n"
                    f"• Используйте файл только для резервного копирования"
                ),
                parse_mode="HTML"
            )

            await callback.answer("✅ Файл сессии успешно экспортирован")

        except Exception as e:
            logger.error(f"Ошибка при создании session файла: {e}")

            if os.path.exists(temp_session_path):
                try:
                    os.remove(temp_session_path)
                except:
                    pass

            await callback.answer(
                "❌ Ошибка при создании файла сессии. Попробуйте позже.",
                show_alert=True
            )

    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("edit_profile_"))
async def edit_profile_menu(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        proxy_config = None
        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                from utils.proxy_validator import get_telethon_proxy_config
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)
        try:
            from telethon.tl.functions.users import GetFullUserRequest
            client = TelegramClient(
                StringSession(account.session_string),
                account.api_id,
                account.api_hash,
                proxy=proxy_config,
                system_version="4.16.30-vxCUSTOM",
                device_model="Desktop",
                app_version="4.16.30"
            )
            await client.connect()
            me = await client.get_me()

            if me is None:
                await client.disconnect()
                from keyboards.keyboards import get_account_problem_keyboard
                await safe_edit_message(
                    callback.message,
                    f"❌ <b>Проблема с аккаунтом</b> <code>{account.phone_number}</code>\n\n"
                    f"Не удалось подключиться к аккаунту. Возможные причины:\n"
                    f"• Сессия недействительна\n"
                    f"• Аккаунт заблокирован\n"
                    f"• Проблемы с сетью\n\n"
                    f"Выберите действие:",
                    get_account_problem_keyboard(account_id)
                )
                return

            full = await client(GetFullUserRequest(me.id))
            await client.disconnect()
        except Exception as e:
            from keyboards.keyboards import get_account_problem_keyboard
            await safe_edit_message(
                callback.message,
                f"❌ <b>Ошибка подключения к аккаунту</b> <code>{account.phone_number}</code>\n\n"
                f"Произошла ошибка: {str(e)}\n\n"
                f"Выберите действие:",
                get_account_problem_keyboard(account_id)
            )
            return
        name = me.first_name or "—"
        username = me.username or "—"
        bio = getattr(full, 'about', None)
        if not bio and hasattr(full, 'full_user'):
            bio = getattr(full.full_user, 'about', None)
        if not bio and hasattr(full, 'users') and full.users:
            bio = getattr(full.users[0], 'about', None)
        if not bio:
            bio = "—"
        photo_status = "✅" if me.photo else "❌"
        text = (
            f"👤 <b>Профиль аккаунта</b> <code>{account.phone_number}</code>\n\n"
            f"Имя: <b>{name}</b>\n"
            f"Username: <b>@{username}</b>\n"
            f"Биография: <b>{bio}</b>\n"
            f"Фото профиля: {photo_status}\n\n"
            "Выберите, что хотите изменить:"
        )
        from keyboards.keyboards import get_account_profile_keyboard
        await safe_edit_message(
            callback.message,
            text,
            get_account_profile_keyboard(account_id)
        )
    finally:
        db.close_session(session)
    await callback.answer()

@router.callback_query(F.data.startswith("profile_name_"))
async def profile_name_start(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    await state.set_state(AccountStates.waiting_for_profile_name)
    await state.update_data(account_id=account_id)
    await safe_edit_message(callback.message, "✏️ Введите новое имя для профиля:", get_back_to_main_keyboard())
    await callback.answer()

@router.message(AccountStates.waiting_for_profile_name)
async def profile_name_save(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")
    new_name = message.text.strip()
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        account.profile_name = new_name
        session.commit()

        try:
            import configparser
            config = configparser.ConfigParser()
            config.read('config.ini')
            api_id = int(config.get('TELEGRAM', 'api_id'))
            api_hash = config.get('TELEGRAM', 'api_hash')
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(
                StringSession(account.session_string),
                api_id,
                api_hash,
                system_version="4.16.30-vxCUSTOM",
                device_model="Desktop",
                app_version="4.16.30"
            )
            await client.start()
            await client(UpdateProfileRequest(first_name=new_name))
            await client.disconnect()
            profile_image = FSInputFile("img_static/profile.png")
            await message.answer_photo(
                photo=profile_image,
                caption=f"✅ Имя профиля обновлено на: <b>{new_name}</b>\n📱 Изменения применены к аккаунту Telegram",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка при обновлении имени профиля через Telethon: {e}")
            await message.answer(
                f"⚠️ Имя сохранено в базе данных, но не удалось применить к аккаунту Telegram: {str(e)}",
                reply_markup=get_main_menu_keyboard()
            )

    finally:
        db.close_session(session)
    await state.clear()

@router.callback_query(F.data.startswith("profile_username_"))
async def profile_username_start(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    await state.set_state(AccountStates.waiting_for_profile_username)
    await state.update_data(account_id=account_id)
    await safe_edit_message(callback.message, "🆔 Введите новый username для профиля:", get_back_to_main_keyboard())
    await callback.answer()

@router.message(AccountStates.waiting_for_profile_username)
async def profile_username_save(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")
    new_username = message.text.strip()
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        account.profile_username = new_username
        session.commit()

        try:
            import configparser
            config = configparser.ConfigParser()
            config.read('config.ini')
            api_id = int(config.get('TELEGRAM', 'api_id'))
            api_hash = config.get('TELEGRAM', 'api_hash')
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(
                StringSession(account.session_string),
                api_id,
                api_hash,
                system_version="4.16.30-vxCUSTOM",
                device_model="Desktop",
                app_version="4.16.30"
            )
            await client.start()
            await client(UpdateUsernameRequest(username=new_username))
            await client.disconnect()
            profile_image = FSInputFile("img_static/profile.png")
            await message.answer_photo(
                photo=profile_image,
                caption=f"✅ Username профиля обновлен на: <b>{new_username}</b>\n📱 Изменения применены к аккаунту Telegram",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка при обновлении username через Telethon: {e}")
            await message.answer(
                f"⚠️ Username сохранен в базе данных, но не удалось применить к аккаунту Telegram: {str(e)}",
                reply_markup=get_main_menu_keyboard()
            )

    finally:
        db.close_session(session)
    await state.clear()

@router.callback_query(F.data.startswith("profile_bio_"))
async def profile_bio_start(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    await state.set_state(AccountStates.waiting_for_profile_bio)
    await state.update_data(account_id=account_id)
    await safe_edit_message(callback.message, "📝 Введите новую биографию для профиля:", get_back_to_main_keyboard())
    await callback.answer()

@router.message(AccountStates.waiting_for_profile_bio)
async def profile_bio_save(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")
    new_bio = message.text.strip()
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        account.profile_bio = new_bio
        session.commit()

        try:
            import configparser
            config = configparser.ConfigParser()
            config.read('config.ini')
            api_id = int(config.get('TELEGRAM', 'api_id'))
            api_hash = config.get('TELEGRAM', 'api_hash')
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(
                StringSession(account.session_string),
                api_id,
                api_hash,
                system_version="4.16.30-vxCUSTOM",
                device_model="Desktop",
                app_version="4.16.30"
            )
            await client.start()
            await client(UpdateProfileRequest(about=new_bio))
            await client.disconnect()
            profile_image = FSInputFile("img_static/profile.png")
            await message.answer_photo(
                photo=profile_image,
                caption=f"✅ Биография профиля обновлена!\n📱 Изменения применены к аккаунту Telegram",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка при обновлении биографии через Telethon: {e}")
            await message.answer(
                f"⚠️ Биография сохранена в базе данных, но не удалось применить к аккаунту Telegram: {str(e)}",
                reply_markup=get_main_menu_keyboard()
            )

    finally:
        db.close_session(session)
    await state.clear()

@router.callback_query(F.data.startswith("profile_photo_"))
async def profile_photo_start(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    await state.set_state(AccountStates.waiting_for_profile_photo)
    await state.update_data(account_id=account_id)
    await safe_edit_message(callback.message, "🖼️ Отправьте новое фото профиля (или текст 'удалить' для удаления):", get_back_to_main_keyboard())
    await callback.answer()

@router.message(AccountStates.waiting_for_profile_photo)
async def profile_photo_save(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        if message.text and message.text.lower() == "удалить":
            account.profile_photo = None
            session.commit()

            try:
                import configparser
                config = configparser.ConfigParser()
                config.read('config.ini')
                api_id = int(config.get('TELEGRAM', 'api_id'))
                api_hash = config.get('TELEGRAM', 'api_hash')
                from telethon import TelegramClient
                from telethon.sessions import StringSession
                client = TelegramClient(
                    StringSession(account.session_string),
                    api_id,
                    api_hash,
                    system_version="4.16.30-vxCUSTOM",
                    device_model="Desktop",
                    app_version="4.16.30"
                )
                await client.start()
                await client(UpdateProfilePhotoRequest(id=None))
                await client.disconnect()
                await message.answer(
                    "✅ Фото профиля удалено!\n"
                    f"📱 Изменения применены к аккаунту Telegram",
                    reply_markup=get_main_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"Ошибка при удалении фото профиля через Telethon: {e}")
                await message.answer(
                    f"⚠️ Фото удалено из базы данных, но не удалось применить к аккаунту Telegram: {str(e)}",
                    reply_markup=get_main_menu_keyboard()
                )

            await state.clear()
            return

        if message.photo:
            file_info = await message.bot.get_file(message.photo[-1].file_id)
            photo_data = await message.bot.download_file(file_info.file_path)
            photo_bytes = photo_data.read()

            account.profile_photo = photo_bytes
            session.commit()

            try:
                import configparser
                config = configparser.ConfigParser()
                config.read('config.ini')
                api_id = int(config.get('TELEGRAM', 'api_id'))
                api_hash = config.get('TELEGRAM', 'api_hash')
                from telethon import TelegramClient
                from telethon.sessions import StringSession
                import io
                client = TelegramClient(
                    StringSession(account.session_string),
                    api_id,
                    api_hash,
                    system_version="4.16.30-vxCUSTOM",
                    device_model="Desktop",
                    app_version="4.16.30"
                )
                await client.start()
                photo_file = io.BytesIO(photo_bytes)
                photo_file.name = "profile_photo.jpg"
                uploaded_photo = await client.upload_file(photo_file)
                await client(UpdateProfilePhotoRequest(id=uploaded_photo))
                await client.disconnect()
                await message.answer(
                    "✅ Фото профиля обновлено!\n"
                    f"📱 Изменения применены к аккаунту Telegram",
                    reply_markup=get_main_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"Ошибка при обновлении фото профиля через Telethon: {e}")
                await message.answer(
                    f"⚠️ Фото сохранено в базе данных, но не удалось применить к аккаунту Telegram: {str(e)}",
                    reply_markup=get_main_menu_keyboard()
                )
        else:
            await message.answer("❌ Отправьте фото или текст 'удалить'!", reply_markup=get_main_menu_keyboard())
            return
    finally:
        db.close_session(session)
    await state.clear()

@router.callback_query(F.data.startswith("cyrillic_substitution_"))
async def cyrillic_substitution_menu(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        current_status = account.cyrillic_substitution
        status_text = "✅ Включена" if current_status else "❌ Выключена"
        status_emoji = "🔴" if current_status else "🟢"
        toggle_text = "Выключить" if current_status else "Включить"

        text = f"🔤 <b>Замена кириллицы на латиницу</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"🔤 <b>Статус:</b> {status_text}\n\n" \
               f"ℹ️ <i>При включении кириллические символы в сообщениях будут заменяться на похожие латинские символы.</i>\n\n" \
               f"Выберите действие:"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{status_emoji} {toggle_text}",
                    callback_data=f"toggle_cyrillic_{account_id}_{int(not current_status)}"
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"account_actions_{account_id}"
                )]
            ]
        )

        await safe_edit_message(
            callback.message,
            text,
            keyboard
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("toggle_cyrillic_"))
async def toggle_cyrillic_substitution(callback: CallbackQuery):
    data_parts = callback.data.split("_")
    account_id = int(data_parts[2])
    new_status = bool(int(data_parts[3]))

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        account.cyrillic_substitution = new_status
        session.commit()

        status_text = "включена" if new_status else "выключена"
        success_text = f"✅ Подмена кириллицы {status_text} для аккаунта {account.phone_number}"

        await callback.answer(success_text)

        await cyrillic_substitution_menu(callback)

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close_session(session)


@router.callback_query(F.data.startswith("toggle_autoresponder_"))
async def toggle_autoresponder(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    data_parts = callback.data.split("_")
    account_id = int(data_parts[2])
    new_status = bool(int(data_parts[3]))

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        account.autoresponder_enabled = new_status
        session.commit()

        status_text = "включен" if new_status else "выключен"
        success_text = f"✅ Автоответчик {status_text} для аккаунта {account.phone_number}"

        await callback.answer(success_text)

        if new_status:
            from services.autoresponder_service import restart_account_autoresponder
            logger.info(f"Включение автоответчика для аккаунта {account_id}")
            await restart_account_autoresponder(account_id)
        else:
            from services.autoresponder_service import autoresponder_service
            logger.info(f"Выключение автоответчика для аккаунта {account_id}")
            await autoresponder_service.stop_autoresponder_for_account(account_id)

        enabled = account.autoresponder_enabled
        first_message = account.autoresponder_first_message or "Не настроено"
        away_message = account.autoresponder_away_message or "Не настроено"
        away_minutes = account.autoresponder_away_minutes or 30

        safe_first_message = escape_html_for_pre(first_message)
        safe_away_message = escape_html_for_pre(away_message)

        truncated_first_message = truncate_message_for_display(safe_first_message)
        truncated_away_message = truncate_message_for_display(safe_away_message)

        status_text = "✅ Включен" if enabled else "❌ Выключен"
        status_emoji = "🔴" if enabled else "🟢"
        toggle_text = "Выключить" if enabled else "Включить"

        text = f"🤖 <b>Автоответчик</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"🤖 <b>Статус:</b> {status_text}\n\n" \
               f"📝 <b>Первое сообщение:</b>\n<pre>{truncated_first_message}</pre>\n\n" \
               f"💬 <b>Сообщение при отсутствии:</b>\n<pre>{truncated_away_message}</pre>\n\n" \
               f"⏰ <b>Время отсутствия:</b> {away_minutes} минут\n\n" \
               f"Выберите настройку для изменения:"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{status_emoji} {toggle_text}",
                    callback_data=f"toggle_autoresponder_{account_id}_{int(not enabled)}"
                )],
                [InlineKeyboardButton(
                    text="📝 Сообщение для новых диалогов",
                    callback_data=f"autoresponder_first_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="💬 Сообщение при отсутствии",
                    callback_data=f"autoresponder_away_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="⏰ Время отсутствия",
                    callback_data=f"autoresponder_time_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"account_actions_{account_id}"
                )]
            ]
        )

        await safe_edit_message(
            callback.message,
            text,
            keyboard
        )

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("autoresponder_first_"))
async def autoresponder_first_message(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        current_message = account.autoresponder_first_message or "Не настроено"

        safe_current_message = escape_html_for_pre(current_message)
        truncated_current_message = truncate_message_for_display(safe_current_message)

        text = f"📝 <b>Первое сообщение автоответчика</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"📝 <b>Текущее сообщение:</b>\n<pre>{truncated_current_message}</pre>\n\n" \
               f"ℹ️ <i>Это сообщение отправляется при первом контакте с новым собеседником.</i>\n\n" \
               f"✏️ Отправьте новое сообщение или '0' для удаления:"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"autoresponder_{account_id}"
                )]
            ]
        )

        await safe_edit_message(
            callback.message,
            text,
            keyboard
        )

        await state.set_state(AccountStates.waiting_for_autoresponder_first_message)
        await state.update_data(account_id=account_id)


    finally:
        db.close_session(session)

    await callback.answer()

@router.message(AccountStates.waiting_for_autoresponder_first_message)
async def save_autoresponder_first_message(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        new_message = message.text.strip()

        if new_message == "0":
            account.autoresponder_first_message = None
        else:
            logger.info(f"👤 Пользовательский ввод для первого сообщения автоответчика: '{message.text}'")

            from utils.markdown_converter import safe_convert_markdown_to_html
            markdown_converted = safe_convert_markdown_to_html(new_message)

            if message.entities:
                from utils.emoji_processor import correct_entity_positions
                corrected_entities = correct_entity_positions(message)
                logger.info(f"📋 Сообщение содержит {len(corrected_entities)} сущностей")
                for i, entity in enumerate(corrected_entities):
                    if entity.type == "custom_emoji":
                        logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}")
                    else:
                        logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}-{entity.offset + entity.length}")
                    if entity.type == "custom_emoji":
                        logger.info(f"  🎭 ID пользовательского эмодзи: {entity.custom_emoji_id}")

                from utils.text_formatter_wrapper import format_message_with_nodejs
                processed_message = format_message_with_nodejs(message)
                account.autoresponder_first_message = processed_message
            else:
                account.autoresponder_first_message = markdown_converted

            logger.info(f"💾 Сохранено первое сообщение автоответчика: '{account.autoresponder_first_message}'")

        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        enabled = account.autoresponder_enabled
        first_message = account.autoresponder_first_message or "Не настроено"
        away_message = account.autoresponder_away_message or "Не настроено"
        away_minutes = account.autoresponder_away_minutes or 30

        safe_first_message = escape_html_for_pre(first_message)
        safe_away_message = escape_html_for_pre(away_message)

        truncated_first_message = truncate_message_for_display(safe_first_message)
        truncated_away_message = truncate_message_for_display(safe_away_message)

        status_text = "✅ Включен" if enabled else "❌ Выключен"
        status_emoji = "🔴" if enabled else "🟢"
        toggle_text = "Выключить" if enabled else "Включить"

        text = f"✅ <b>Первое сообщение сохранено!</b>\n\n" \
               f"🤖 <b>Автоответчик</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"🤖 <b>Статус:</b> {status_text}\n\n" \
               f"📝 <b>Первое сообщение:</b>\n<pre>{truncated_first_message}</pre>\n\n" \
               f"💬 <b>Сообщение при отсутствии:</b>\n<pre>{truncated_away_message}</pre>\n\n" \
               f"⏰ <b>Время отсутствия:</b> {away_minutes} минут\n\n" \
               f"Выберите настройку для изменения:"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{status_emoji} {toggle_text}",
                    callback_data=f"toggle_autoresponder_{account_id}_{int(not enabled)}"
                )],
                [InlineKeyboardButton(
                    text="📝 Сообщение для новых диалогов",
                    callback_data=f"autoresponder_first_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="💬 Сообщение при отсутствии",
                    callback_data=f"autoresponder_away_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="⏰ Время отсутствия",
                    callback_data=f"autoresponder_time_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"account_actions_{account_id}"
                )]
            ]
        )

        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            photo=mailer_image,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_menu_keyboard())
    finally:
        db.close_session(session)

    await state.clear()

@router.callback_query(F.data.startswith("autoresponder_away_"))
async def autoresponder_away_message(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        current_message = account.autoresponder_away_message or "Не настроено"

        safe_current_message = escape_html_for_pre(current_message)
        truncated_current_message = truncate_message_for_display(safe_current_message)

        text = f"💬 <b>Сообщение при отсутствии</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"💬 <b>Текущее сообщение:</b>\n<pre>{truncated_current_message}</pre>\n\n" \
               f"ℹ️ <i>Это сообщение отправляется, когда пользователь не отвечает в течение установленного времени.</i>\n\n" \
               f"✏️ Отправьте новое сообщение или '0' для удаления:"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"autoresponder_{account_id}"
                )]
            ]
        )

        await safe_edit_message(
            callback.message,
            text,
            keyboard
        )

        await state.set_state(AccountStates.waiting_for_autoresponder_away_message)
        await state.update_data(account_id=account_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.message(AccountStates.waiting_for_autoresponder_away_message)
async def save_autoresponder_away_message(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        new_message = message.text.strip()

        if new_message == "0":
            account.autoresponder_away_message = None
        else:
            logger.info(f"👤 Пользовательский ввод для сообщения при отсутствии: '{message.text}'")

            from utils.markdown_converter import safe_convert_markdown_to_html
            markdown_converted = safe_convert_markdown_to_html(new_message)

            if message.entities:
                from utils.emoji_processor import correct_entity_positions
                corrected_entities = correct_entity_positions(message)
                logger.info(f"📋 Сообщение содержит {len(corrected_entities)} сущностей")
                for i, entity in enumerate(corrected_entities):
                    if entity.type == "custom_emoji":
                        logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}")
                    else:
                        logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}-{entity.offset + entity.length}")
                    if entity.type == "custom_emoji":
                        logger.info(f"  🎭 ID пользовательского эмодзи: {entity.custom_emoji_id}")

                from utils.text_formatter_wrapper import format_message_with_nodejs
                processed_message = format_message_with_nodejs(message)
                account.autoresponder_away_message = processed_message
            else:
                account.autoresponder_away_message = markdown_converted

            logger.info(f"💾 Сохранено сообщение при отсутствии: '{account.autoresponder_away_message}'")

        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        enabled = account.autoresponder_enabled
        first_message = account.autoresponder_first_message or "Не настроено"
        away_message = account.autoresponder_away_message or "Не настроено"
        away_minutes = account.autoresponder_away_minutes or 30

        status_text = "✅ Включен" if enabled else "❌ Выключен"
        status_emoji = "🔴" if enabled else "🟢"
        toggle_text = "Выключить" if enabled else "Включить"

        safe_first_message = escape_html_for_pre(first_message)
        safe_away_message = escape_html_for_pre(away_message)

        truncated_first_message = truncate_message_for_display(safe_first_message)
        truncated_away_message = truncate_message_for_display(safe_away_message)

        text = f"✅ <b>Сообщение при отсутствии сохранено!</b>\n\n" \
               f"🤖 <b>Автоответчик</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"🤖 <b>Статус:</b> {status_text}\n\n" \
               f"📝 <b>Первое сообщение:</b>\n<pre>{truncated_first_message}</pre>\n\n" \
               f"💬 <b>Сообщение при отсутствии:</b>\n<pre>{truncated_away_message}</pre>\n\n" \
               f"⏰ <b>Время отсутствия:</b> {away_minutes} минут\n\n" \
               f"Выберите настройку для изменения:"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{status_emoji} {toggle_text}",
                    callback_data=f"toggle_autoresponder_{account_id}_{int(not enabled)}"
                )],
                [InlineKeyboardButton(
                    text="📝 Сообщение для новых диалогов",
                    callback_data=f"autoresponder_first_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="💬 Сообщение при отсутствии",
                    callback_data=f"autoresponder_away_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="⏰ Время отсутствия",
                    callback_data=f"autoresponder_time_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"account_actions_{account_id}"
                )]
            ]
        )

        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            photo=mailer_image,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_menu_keyboard())
    finally:
        db.close_session(session)

    await state.clear()

@router.callback_query(F.data.startswith("autoresponder_time_"))
async def autoresponder_time_setting(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        current_time = account.autoresponder_away_minutes or 30

        text = f"⏰ <b>Время отсутствия автоответчика</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"⏰ <b>Текущее время:</b> {current_time} минут\n\n" \
               f"ℹ️ <i>Через сколько минут после последнего сообщения отправлять сообщение об отсутствии.</i>\n\n" \
               f"✏️ Отправьте новое время в минутах (от 1 до 1440):"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"autoresponder_{account_id}"
                )]
            ]
        )

        await safe_edit_message(
            callback.message,
            text,
            keyboard
        )

        await state.set_state(AccountStates.waiting_for_autoresponder_away_minutes)
        await state.update_data(account_id=account_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.message(AccountStates.waiting_for_autoresponder_away_minutes)
async def save_autoresponder_away_time(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        try:
            new_time = int(message.text.strip())
            if new_time < 1 or new_time > 1440:
                await message.answer("❌ Время должно быть от 1 до 1440 минут", reply_markup=get_main_menu_keyboard())
                await state.clear()
                return

            account.autoresponder_away_minutes = new_time
            session.commit()

            try:
                await message.bot.delete_message(message.chat.id, message.message_id-1)
            except:
                pass
            try:
                await message.delete()
            except:
                pass

            enabled = account.autoresponder_enabled
            first_message = account.autoresponder_first_message or "Не настроено"
            away_message = account.autoresponder_away_message or "Не настроено"
            away_minutes = account.autoresponder_away_minutes or 30

            safe_first_message = escape_html_for_pre(first_message)
            safe_away_message = escape_html_for_pre(away_message)

            truncated_first_message = truncate_message_for_display(safe_first_message)
            truncated_away_message = truncate_message_for_display(safe_away_message)

            status_text = "✅ Включен" if enabled else "❌ Выключен"
            status_emoji = "🔴" if enabled else "🟢"
            toggle_text = "Выключить" if enabled else "Включить"

            text = f"✅ <b>Время отсутствия изменено!</b>\n\n" \
                   f"🤖 <b>Автоответчик</b>\n\n" \
                   f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
                   f"🤖 <b>Статус:</b> {status_text}\n\n" \
                   f"📝 <b>Первое сообщение:</b>\n<pre>{truncated_first_message}</pre>\n\n" \
                   f"💬 <b>Сообщение при отсутствии:</b>\n<pre>{truncated_away_message}</pre>\n\n" \
                   f"⏰ <b>Время отсутствия:</b> {away_minutes} минут\n\n" \
                   f"Выберите настройку для изменения:"

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"{status_emoji} {toggle_text}",
                        callback_data=f"toggle_autoresponder_{account_id}_{int(not enabled)}"
                    )],
                    [InlineKeyboardButton(
                        text="📝 Сообщение для новых диалогов",
                        callback_data=f"autoresponder_first_{account_id}"
                    )],
                    [InlineKeyboardButton(
                        text="💬 Сообщение при отсутствии",
                        callback_data=f"autoresponder_away_{account_id}"
                    )],
                    [InlineKeyboardButton(
                        text="⏰ Время отсутствия",
                        callback_data=f"autoresponder_time_{account_id}"
                    )],
                    [InlineKeyboardButton(
                        text="🔙 Назад",
                        callback_data=f"account_actions_{account_id}"
                    )]
                ]
            )

            mailer_image = FSInputFile("img_static/mailer.png")
            await message.answer_photo(
                photo=mailer_image,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        except ValueError:
            await message.answer("❌ Введите корректное число", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close_session(session)

    await state.clear()

def escape_html_for_pre(text: str) -> str:
    if not text or text == "Не настроено":
        return text

    import re

    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

    text = re.sub(r'</(?:p|div)>', '\n', text, flags=re.IGNORECASE)

    text = re.sub(r'<[^>]+>', '', text)

    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        cleaned_line = line.strip()
        cleaned_line = re.sub(r'\s+', ' ', cleaned_line)
        cleaned_lines.append(cleaned_line)

    text = '\n'.join(cleaned_lines)
    text = text.strip()

    text = re.sub(r'\n{3,}', '\n\n', text)

    return text

@router.callback_query(F.data.startswith("autoresponder_"))
async def autoresponder_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    account_id = int(callback.data.split("_")[1])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        enabled = account.autoresponder_enabled
        first_message = account.autoresponder_first_message or "Не настроено"
        away_message = account.autoresponder_away_message or "Не настроено"
        away_minutes = account.autoresponder_away_minutes or 30

        safe_first_message = escape_html_for_pre(first_message)
        safe_away_message = escape_html_for_pre(away_message)

        truncated_first_message = truncate_message_for_display(safe_first_message)
        truncated_away_message = truncate_message_for_display(safe_away_message)

        status_text = "✅ Включен" if enabled else "❌ Выключен"
        status_emoji = "🔴" if enabled else "🟢"
        toggle_text = "Выключить" if enabled else "Включить"

        text = f"🤖 <b>Автоответчик</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"🤖 <b>Статус:</b> {status_text}\n\n" \
               f"📝 <b>Первое сообщение:</b>\n<pre>{truncated_first_message}</pre>\n\n" \
               f"💬 <b>Сообщение при отсутствии:</b>\n<pre>{truncated_away_message}</pre>\n\n" \
               f"⏰ <b>Время отсутствия:</b> {away_minutes} минут\n\n" \
               f"Выберите настройку для изменения:"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{status_emoji} {toggle_text}",
                    callback_data=f"toggle_autoresponder_{account_id}_{int(not enabled)}"
                )],
                [InlineKeyboardButton(
                    text="📝 Сообщение для новых диалогов",
                    callback_data=f"autoresponder_first_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="💬 Сообщение при отсутствии",
                    callback_data=f"autoresponder_away_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="⏰ Время отсутствия",
                    callback_data=f"autoresponder_time_{account_id}"
                )],
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"account_actions_{account_id}"
                )]
            ]
        )

        await safe_edit_message(
            callback.message,
            text,
            keyboard
        )

    finally:
        db.close_session(session)

    await callback.answer()

def truncate_message_for_display(text: str, max_length: int = 770) -> str:
    if not text:
        return text

    if len(text) <= max_length:
        return text

    if '<' in text and '>' in text:
        from utils.html_truncator import safe_truncate_html
        return safe_truncate_html(text, max_length, "...")
    else:
        return text[:max_length] + "..."

def build_group_settings_text(account_id, group_id):
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings
        account = session.query(Account).filter(Account.id == account_id).first()
        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()
        if not account or not group_settings:
            return "❌ Настройки группы не найдены"
        media_status = "<pre>Нет медиа</pre>"
        if group_settings.custom_photo:
            media_status = "<pre>Фото (индивидуальное)</pre>"
        elif group_settings.custom_gif:
            media_status = "<pre>GIF (индивидуальное)</pre>"
        elif group_settings.custom_video:
            media_status = "<pre>Видео (индивидуальное)</pre>"
        elif account.default_photo:
            media_status = "<pre>Фото (общее)</pre>"
        elif account.default_gif:
            media_status = "<pre>GIF (общее)</pre>"
        elif account.default_video:
            media_status = "<pre>Видео (общее)</pre>"

        if group_settings.custom_message:
            from utils.emoji_processor import html_with_tg_emoji_to_plain_text
            plain_message = html_with_tg_emoji_to_plain_text(group_settings.custom_message)
            safe_plain_message = escape_html_for_pre(plain_message)
            truncated_message = truncate_message_for_display(safe_plain_message)
            message_status = f"<pre>{truncated_message}</pre> (индивидуальное)"
        elif account.default_message:
            from utils.emoji_processor import html_with_tg_emoji_to_plain_text
            plain_message = html_with_tg_emoji_to_plain_text(account.default_message)
            safe_plain_message = escape_html_for_pre(plain_message)
            truncated_message = truncate_message_for_display(safe_plain_message)
            message_status = f"<pre>{truncated_message}</pre> (общее)"
        else:
            message_status = "<pre>Не настроено</pre>"

        current_interval = group_settings.custom_interval or account.message_interval
        slowmode_minutes = group_settings.slowmode_minutes or 0

        if group_settings.custom_interval:
            interval_source = f"{current_interval} мин (индивидуальный)"
        else:
            interval_source = f"{current_interval} мин (общий)"

        if slowmode_minutes > 0:
            if current_interval < slowmode_minutes:
                interval_text = f"{interval_source} ⚠️"
                slowmode_warning = f"🐌 <b>Slow mode:</b> {slowmode_minutes} мин (интервал меньше slow mode!)"
            else:
                interval_text = f"{interval_source} ✅"
                slowmode_warning = f"🐌 <b>Slow mode:</b> {slowmode_minutes} мин"
        else:
            interval_text = interval_source
            slowmode_warning = "🐌 <b>Slow mode:</b> Отключен"

        text = f"⚙️ <b>Настройки группы</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n" \
               f"👥 <b>Группа:</b> {group_settings.group_name}\n\n" \
               f"📝 <b>Сообщение:</b> {message_status}\n" \
               f"🖼️ <b>Медиа:</b> {media_status}\n" \
               f"⏱️ <b>Интервал:</b> {interval_text}\n" \
               f"{slowmode_warning}\n\n" \
               f"Выберите что изменить:"
        return text
    finally:
        db.close_session(session)

def build_topic_settings_text(account_id, topic_data, for_caption=False):
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()

        group_id, topic_id = topic_data.split('_')
        group_id = int(group_id)
        topic_id = int(topic_id)

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        if not account:
            return "❌ Аккаунт не найден"

        group_name = super_group.base_group_name if super_group else f"Группа {group_id}"
        topic_name = super_group.topic_name if super_group else f"Тема {topic_id}"

        media_status = "<pre>Нет медиа</pre>"
        if super_group and super_group.custom_photo:
            media_status = "<pre>Фото</pre>"
        elif super_group and super_group.custom_gif:
            media_status = "<pre>GIF</pre>"
        elif super_group and super_group.custom_video:
            media_status = "<pre>Видео</pre>"

        if super_group and super_group.custom_message:
            from utils.emoji_processor import html_with_tg_emoji_to_plain_text
            plain_message = html_with_tg_emoji_to_plain_text(super_group.custom_message)
            safe_plain_message = escape_html_for_pre(plain_message)

            if for_caption:
                truncated_message = safe_plain_message[:770] + "..." if len(safe_plain_message) > 770 else safe_plain_message
            else:
                truncated_message = truncate_message_for_display(safe_plain_message)
            message_status = f"<pre>{truncated_message}</pre>"
        else:
            message_status = "<pre>Не настроено</pre>"

        if super_group and super_group.custom_interval:
            interval_text = f"{super_group.custom_interval} мин"
        else:
            interval_text = "15 мин (автоматический)"

        if for_caption:
            from utils.html_truncator import safe_truncate_text_in_html

            safe_group_name = safe_truncate_text_in_html(group_name, 20, "...") if len(group_name) > 20 else group_name
            safe_topic_name = safe_truncate_text_in_html(topic_name, 20, "...") if len(topic_name) > 20 else topic_name

            text = f"📝 <b>Настройки темы</b>\n\n" \
                   f"👥 <b>Группа:</b> {safe_group_name}\n" \
                   f"📝 <b>Тема:</b> {safe_topic_name}\n\n" \
                   f"📝 <b>Сообщение:</b> {message_status}\n" \
                   f"🖼️ <b>Медиа:</b> {media_status}\n" \
                   f"⏱️ <b>Интервал:</b> {interval_text}\n\n" \
                   f"Выберите что изменить:"
        else:
            text = f"📝 <b>Настройки {group_name} | {topic_name}</b>\n\n" \
                   f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
                   f"ℹ️ <b>Эти настройки будут использоваться для рассылки в выбранную тему, если сообщение не настроено, рассылку не делать.</b>\n\n" \
                   f"📝 <b>Сообщение:</b> {message_status}\n" \
                   f"🖼️ <b>Медиа:</b> {media_status}\n" \
                   f"⏱️ <b>Интервал:</b> {interval_text}\n\n" \
                   f"Выберите что изменить:"

        if for_caption and len(text) > 1000:
            from utils.html_truncator import safe_truncate_html
            text = safe_truncate_html(text, 950, "\n\n...\n\nВыберите что изменить:")

        return text
    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("confirm_interval_"))
async def confirm_interval(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = parts[3]
    interval = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import GroupSettings
        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()

        if group_settings:
            group_settings.custom_interval = interval
            session.commit()

            mailer_image = FSInputFile("img_static/mailer.png")
            text = build_group_settings_text(account_id, group_id)
            await callback.bot.edit_message_media(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
                reply_markup=get_group_settings_keyboard(account_id, group_id, back_to_account=True)
            )
        else:
            await callback.answer("❌ Настройки группы не найдены")

    except Exception as e:
        logger.error(f"Ошибка при подтверждении интервала: {e}")
        await callback.answer("❌ Ошибка при сохранении интервала")
        session.rollback()
    finally:
        db.close_session(session)

    await callback.answer("✅ Интервал сохранен")

@router.callback_query(F.data.startswith("common_settings_"))
async def common_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return


        text = f"📝 <b>Общие настройки аккаунта</b>\n\n"
        text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n"
        text += f"ℹ️ <i>Эти настройки будут использоваться для рассылки в группы, где не настроены индивидуальные параметры.</i>\n\n"

        if account.default_message:
            safe_default_message = escape_html_for_pre(account.default_message)
            truncated_default_message = truncate_message_for_display(safe_default_message)
            text += f"📝 <b>Сообщение:</b> <pre>{truncated_default_message}</pre>\n"
        else:
            text += f"📝 <b>Сообщение:</b> <pre>Не настроено</pre>\n"

        if account.default_photo:
            text += f"🖼️ <b>Медиа:</b> <pre>Фото</pre>\n"
        elif account.default_gif:
            text += f"🖼️ <b>Медиа:</b> <pre>GIF</pre>\n"
        elif account.default_video:
            text += f"🖼️ <b>Медиа:</b> <pre>Видео</pre>\n"
        else:
            text += f"🖼️ <b>Медиа:</b> <pre>Нет медиа</pre>\n"

        text += f"⏱️ <b>Интервал:</b> <pre>{account.message_interval} минут</pre>\n\n"
        text += f"Выберите что изменить:"

        keyboard = get_common_settings_keyboard(account_id)

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=keyboard
        )
    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("common_message_"))
async def common_message(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        current_message = account.default_message or "Не настроено"

        safe_current_message = escape_html_for_pre(current_message)
        truncated_current_message = truncate_message_for_display(safe_current_message)

        text = f"📝 <b>Общее сообщение аккаунта</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"📝 <b>Текущее сообщение:</b>\n<pre>{truncated_current_message}</pre>\n\n" \
               f"✏️ Отправьте новое сообщение или '0' для удаления:"

        await safe_edit_message(
            callback.message,
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data=f"common_settings_{account_id}")]
                ]
            )
        )

        await state.set_state(AccountStates.waiting_for_common_message)
        await state.update_data(account_id=account_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("common_interval_"))
async def common_interval(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        current_interval = account.message_interval or 60

        text = f"⏱️ <b>Общий интервал аккаунта</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"⏱️ <b>Текущий интервал:</b> {current_interval} минут\n\n" \
               f"ℹ️ <i>Интервал между сообщениями для групп без индивидуальных настроек.</i>\n\n" \
               f"✏️ Отправьте новый интервал в минутах (от 1 до 1440):"

        await safe_edit_message(
            callback.message,
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data=f"common_settings_{account_id}")]
                ]
            )
        )

        await state.set_state(AccountStates.waiting_for_common_interval)
        await state.update_data(account_id=account_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("common_media_"))
async def common_media(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        current_media = "Нет медиа"
        if account.default_photo:
            current_media = "Фото"
        elif account.default_gif:
            current_media = "GIF"
        elif account.default_video:
            current_media = "Видео"

        text = f"🖼️ <b>Общее медиа аккаунта</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"🖼️ <b>Текущее медиа:</b> {current_media}\n\n" \
               f"ℹ️ <i>Медиа будет использоваться для рассылки в группы без индивидуальных настроек.</i>\n\n" \
               f"📱 Отправьте фото, GIF или видео для замены, или '0' для удаления:"

        await safe_edit_message(
            callback.message,
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data=f"common_settings_{account_id}")]
                ]
            )
        )

        await state.set_state(AccountStates.waiting_for_common_media)
        await state.update_data(account_id=account_id)

    finally:
        db.close_session(session)

    await callback.answer()

@router.message(AccountStates.waiting_for_common_message)
async def process_common_message(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')

    if not account_id:
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        if message.text.strip() == "0":
            account.default_message = None
        else:
            logger.info(f"👤 Пользовательский ввод для общего сообщения: '{message.text}'")

            if message.entities:
                from utils.emoji_processor import correct_entity_positions
                corrected_entities = correct_entity_positions(message)
                logger.info(f"📋 Сообщение содержит {len(corrected_entities)} сущностей")
                for i, entity in enumerate(corrected_entities):
                    if entity.type == "custom_emoji":
                        logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}")
                    else:
                        logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}-{entity.offset + entity.length}")
                    if entity.type == "custom_emoji":
                        logger.info(f"  🎭 ID пользовательского эмодзи: {entity.custom_emoji_id}")

                from utils.text_formatter_wrapper import format_message_with_nodejs
                processed_message = format_message_with_nodejs(message)
                account.default_message = processed_message
            else:
                from utils.markdown_converter import safe_convert_markdown_to_html
                markdown_converted = safe_convert_markdown_to_html(message.text.strip())
                account.default_message = markdown_converted

            logger.info(f"💾 Сохранено общее сообщение: '{account.default_message}'")

        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        await message.answer_photo(
            FSInputFile("img_static/mailer.png"),
            caption=build_common_settings_text(account_id),
            reply_markup=get_common_settings_keyboard(account_id),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при обновлении общего сообщения: {e}")
        await message.answer("❌ Ошибка при обновлении сообщения")
    finally:
        db.close_session(session)

    await state.clear()

@router.message(AccountStates.waiting_for_common_interval)
async def process_common_interval(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')

    if not account_id:
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    if message.text.strip() == "0":
        from database.database import db
        session = db.get_session()
        try:
            from database.models import Account
            account = session.query(Account).filter(Account.id == account_id).first()
            if not account:
                await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
                await state.clear()
                return

            account.message_interval = 60
            session.commit()

            try:
                await message.bot.delete_message(message.chat.id, message.message_id-1)
            except:
                pass
            try:
                await message.delete()
            except:
                pass

            await message.answer_photo(
                FSInputFile("img_static/mailer.png"),
                caption=build_common_settings_text(account_id),
                reply_markup=get_common_settings_keyboard(account_id),
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Ошибка при сбросе общего интервала: {e}")
            await message.answer("❌ Ошибка при сбросе интервала")
        finally:
            db.close_session(session)

        await state.clear()
        return

    try:
        interval = int(message.text)
        if interval < 1 or interval > 1440:
            await message.answer("❌ Интервал должен быть от 1 до 1440 минут", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return
    except ValueError:
        await message.answer("❌ Введите корректное число или '0' для сброса", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        account.message_interval = interval
        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        await message.answer_photo(
            FSInputFile("img_static/mailer.png"),
            caption=build_common_settings_text(account_id),
            reply_markup=get_common_settings_keyboard(account_id),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при обновлении общего интервала: {e}")
        await message.answer("❌ Ошибка при обновлении интервала")
    finally:
        db.close_session(session)

    await state.clear()

@router.message(AccountStates.waiting_for_account_promo)
async def process_account_promo(message: Message, state: FSMContext):
    promo_code = message.text.strip().upper()
    data = await state.get_data()
    account_id = data.get('account_id')

    if not account_id:
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    telegram_id = str(message.from_user.id)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode, Account, User

        promo = session.query(PromoCode).filter(
            PromoCode.code == promo_code,
            PromoCode.is_active == True
        ).first()

        if not promo:
            try:
                await message.bot.delete_message(message.chat.id, message.message_id-1)
            except:
                pass
            try:
                await message.delete()
            except:
                pass

            await message.answer_photo(
                FSInputFile("img_static/mailer.png"),
                caption=f"❌ Промокод '<code>{promo_code}</code>' не найден или неактивен.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return

        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            try:
                await message.bot.delete_message(message.chat.id, message.message_id-1)
            except:
                pass
            try:
                await message.delete()
            except:
                pass

            await message.answer_photo(
                FSInputFile("img_static/mailer.png"),
                caption=f"❌ Промокод '<code>{promo_code}</code>' превысил лимит использований.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            try:
                await message.bot.delete_message(message.chat.id, message.message_id-1)
            except:
                pass
            try:
                await message.delete()
            except:
                pass

            await message.answer_photo(
                FSInputFile("img_static/mailer.png"),
                caption="❌ Аккаунт не найден",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
            await state.clear()
            return

        if promo.type == "balance":
            user = session.query(User).filter(User.telegram_id == telegram_id).first()
            if user:
                user.balance += promo.value
                bonus_text = f"{promo.value} $ к балансу"
                user_bonus = f"баланс увеличен на {promo.value} $"
            else:
                try:
                    await message.bot.delete_message(message.chat.id, message.message_id-1)
                except:
                    pass
                try:
                    await message.delete()
                except:
                    pass

                await message.answer_photo(
                    FSInputFile("img_static/mailer.png"),
                    caption="❌ Пользователь не найден",
                    reply_markup=get_main_menu_keyboard(),
                    parse_mode="HTML"
                )
                await state.clear()
                return
        else:
            subscription_minutes = int(promo.value)
            account.subscription_minutes += subscription_minutes

            bonus_text = f"{subscription_minutes} минут"
            user_bonus = f"добавлено {subscription_minutes} минут к аккаунту {account.phone_number}"

        promo.used_count += 1

        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        text = f"✅ <b>Промо-код активирован!</b>\n\n" \
               f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
               f"🎫 <b>Промо-код:</b> <code>{promo.code}</code>\n\n" \
               f"💰 <b>Получено:</b> {bonus_text}\n\n" \
               f"ℹ️ <i>{user_bonus}</i>\n\n" \
               f"Возвращайтесь в главное меню:"

        await message.answer_photo(
            FSInputFile("img_static/mailer.png"),
            caption=text,
            reply_markup=get_account_actions_keyboard(account_id, is_active=account.is_active, subscription_minutes=account.subscription_minutes),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке промокода для аккаунта: {e}")
        await message.answer(
            f"❌ Произошла ошибка при активации промокода: {str(e)}",
            reply_markup=get_main_menu_keyboard()
        )
    finally:
        db.close_session(session)

    await state.clear()

@router.message(AccountStates.waiting_for_common_media)
async def process_common_media(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')

    if not account_id:
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        if message.text and message.text.strip() == "0":
            account.default_photo = None
            account.default_gif = None
            account.default_video = None
            session.commit()

            try:
                await message.bot.delete_message(message.chat.id, message.message_id-1)
            except:
                pass
            try:
                await message.delete()
            except:
                pass

            await message.answer_photo(
                FSInputFile("img_static/mailer.png"),
                caption=build_common_settings_text(account_id),
                reply_markup=get_common_settings_keyboard(account_id),
                parse_mode="HTML"
            )
            await state.clear()
            return

        media_data = None
        if message.photo:
            media_data = await message.bot.download(message.photo[-1].file_id)
            account.default_photo = media_data.read()
            account.default_gif = None
            account.default_video = None
        elif message.animation:
            media_data = await message.bot.download(message.animation.file_id)
            account.default_gif = media_data.read()
            account.default_photo = None
            account.default_video = None
        elif message.video:
            media_data = await message.bot.download(message.video.file_id)
            account.default_video = media_data.read()
            account.default_photo = None
            account.default_gif = None
        else:
            await message.answer("❌ Отправьте фото, GIF или видео, или '0' для удаления")
            return

        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id-1)
        except:
            pass
        try:
            await message.delete()
        except:
            pass

        await message.answer_photo(
            FSInputFile("img_static/mailer.png"),
            caption=build_common_settings_text(account_id),
            reply_markup=get_common_settings_keyboard(account_id),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при обновлении общего медиа: {e}")
        await message.answer("❌ Ошибка при обновлении медиа")
    finally:
        db.close_session(session)

    await state.clear()

def build_common_settings_text(account_id):
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            return "❌ Аккаунт не найден"

        text = f"📄 <b>Общие настройки аккаунта</b>\n\n"
        text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n"
        text += f"ℹ️ <i>Эти настройки будут использоваться для рассылки в группы, где не настроены индивидуальные параметры.</i>\n\n"

        if account.default_message:
            safe_default_message = escape_html_for_pre(account.default_message)
            truncated_default_message = truncate_message_for_display(safe_default_message)
            text += f"📝 <b>Сообщение:</b> <pre>{truncated_default_message}</pre>\n"
        else:
            text += f"📝 <b>Сообщение:</b> <pre>Не настроено</pre>\n"

        if account.default_photo:
            text += f"🖼️ <b>Медиа:</b> <pre>Фото</pre>\n"
        elif account.default_gif:
            text += f"🖼️ <b>Медиа:</b> <pre>GIF</pre>\n"
        elif account.default_video:
            text += f"🖼️ <b>Медиа:</b> <pre>Видео</pre>\n"
        else:
            text += f"🖼️ <b>Медиа:</b> <pre>Нет медиа</pre>\n"

        text += f"⏱️ <b>Интервал:</b> <pre>{account.message_interval} минут</pre>\n\n"
        text += f"Выберите что изменить:"

        return text
    finally:
        db.close_session(session)


@router.callback_query(F.data.startswith("account_templates_"))
async def account_templates_menu(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    from database.database import db

    session = db.get_session()
    try:
        from database.models import Account, AccountTemplate
        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        templates = session.query(AccountTemplate).filter(
            AccountTemplate.user_id == account.user_id
        ).all()

        text = f"📋 <b>Шаблоны аккаунтов</b>\n\n"
        text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n"

        if templates:
            text += f"📋 <b>Найдено шаблонов:</b> {len(templates)}\n\n"
            text += "Выберите шаблон для применения или создайте новый:"
        else:
            text += "📋 <b>Шаблоны не найдены</b>\n\n"
            text += "Создайте первый шаблон для сохранения настроек аккаунта:"

        await safe_edit_message(
            callback.message,
            text,
            get_account_templates_keyboard(account_id, templates)
        )
    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("create_template_"))
async def create_template_start(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])
    await state.set_state(AccountStates.waiting_for_template_name)
    await state.update_data(account_id=account_id)

    await safe_edit_message(
        callback.message,
        "📝 Введите название для нового шаблона:",
        get_back_to_main_keyboard()
    )
    await callback.answer()

@router.message(AccountStates.waiting_for_template_name)
async def create_template_save(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get("account_id")
    template_name = message.text.strip()

    if len(template_name) < 1 or len(template_name) > 50:
        await message.answer("❌ Название шаблона должно быть от 1 до 50 символов")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, AccountTemplate, GroupSettings, GroupTemplate

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await message.answer("❌ Аккаунт не найден", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        template = AccountTemplate(
            name=template_name,
            user_id=account.user_id,
            profile_name=account.profile_name,
            profile_username=account.profile_username,
            profile_bio=account.profile_bio,
            profile_photo=account.profile_photo,
            default_message=account.default_message,
            message_interval=account.message_interval,
            default_photo=account.default_photo,
            default_gif=account.default_gif,
            default_video=account.default_video,
            cyrillic_substitution=account.cyrillic_substitution,
            autoresponder_enabled=account.autoresponder_enabled,
            autoresponder_first_message=account.autoresponder_first_message,
            autoresponder_away_message=account.autoresponder_away_message,
            autoresponder_away_minutes=account.autoresponder_away_minutes
        )

        session.add(template)
        session.flush()

        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id
        ).all()

        for group_setting in group_settings:
            group_template = GroupTemplate(
                template_id=template.id,
                group_id=group_setting.group_id,
                group_name=group_setting.group_name,
                custom_message=group_setting.custom_message,
                custom_photo=group_setting.custom_photo,
                custom_gif=group_setting.custom_gif,
                custom_video=group_setting.custom_video,
                custom_interval=group_setting.custom_interval,
                is_enabled=group_setting.is_enabled
            )
            session.add(group_template)

        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id - 1)
            await message.bot.delete_message(message.chat.id, message.message_id)
        except:
            pass

        groups_data = [
            {'group_id': group.group_id, 'group_name': group.group_name}
            for group in group_settings
        ]

        if groups_data:
            settings_text = f"<b>⚙️ Настройки аккаунта</b> <code>{account.phone_number}</code>\n\n" \
                           f"👥 <b>Активные группы:</b> {len(groups_data)}\n\nВыберите группу для настройки сообщения, медиа и интервала:"
        else:
            settings_text = f"<b>⚙️ Настройки аккаунта</b> <code>{account.phone_number}</code>\n\n❌ <b>Группы не выбраны</b>\n\nСначала выберите группы в разделе 'Группы' в меню аккаунта."

        success_text = f"✅ Шаблон '<b>{template_name}</b>' успешно создан!\n\n"
        success_text += f"📋 Сохранено:\n"
        success_text += f"• Настройки профиля\n"
        success_text += f"• Общие сообщения и медиа\n"
        success_text += f"• Настройки автоответчика\n"
        success_text += f"• Подмена кириллицы\n"
        success_text += f"• Настройки {len(group_settings)} групп\n\n"
        success_text += settings_text

        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            photo=mailer_image,
            caption=success_text,
            reply_markup=get_account_profile_keyboard(account_id),
            parse_mode="HTML"
        )

    finally:
        db.close_session(session)

    await state.clear()

@router.callback_query(F.data.startswith("apply_template_"))
async def apply_template_preview(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    template_id = int(parts[3])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, AccountTemplate, GroupTemplate

        account = session.query(Account).filter(Account.id == account_id).first()
        template = session.query(AccountTemplate).filter(AccountTemplate.id == template_id).first()

        if not account or not template:
            await callback.answer("❌ Аккаунт или шаблон не найден")
            return

        template_groups = session.query(GroupTemplate).filter(
            GroupTemplate.template_id == template_id
        ).all()

        from database.models import GroupSettings
        account_groups = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id
        ).all()

        account_group_ids = {g.group_id for g in account_groups}
        template_group_ids = {g.group_id for g in template_groups}

        missing_groups = template_group_ids - account_group_ids
        extra_groups = account_group_ids - template_group_ids

        text = f"📋 <b>Предварительный просмотр шаблона</b>\n\n"
        text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
        text += f"📋 <b>Шаблон:</b> {template.name}\n\n"

        text += f"📊 <b>Что будет применено:</b>\n"
        text += f"• Настройки профиля\n"
        text += f"• Общие сообщения и медиа\n"
        text += f"• Настройки автоответчика\n"
        text += f"• Подмена кириллицы\n"
        text += f"• Настройки {len(template_groups)} групп\n\n"

        if missing_groups:
            text += f"⚠️ <b>Внимание:</b> Аккаунт не состоит в {len(missing_groups)} группах из шаблона:\n"
            for group in template_groups:
                if group.group_id in missing_groups:
                    text += f"• {group.group_name or group.group_id}\n"
            text += "\n"

        if extra_groups:
            text += f"ℹ️ <b>Инфо:</b> Настройки {len(extra_groups)} групп аккаунта не будут изменены\n\n"

        text += "Применить шаблон?"

        await safe_edit_message(
            callback.message,
            text,
            get_template_actions_keyboard(account_id, template_id)
        )
    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("confirm_apply_template_"))
async def confirm_apply_template(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    template_id = int(parts[4])

    await safe_edit_message(
        callback.message,
        "⚠️ <b>Подтверждение применения шаблона</b>\n\n"
        "Все текущие настройки аккаунта будут заменены настройками из шаблона.\n\n"
        "Это действие нельзя отменить!\n\n"
        "Вы уверены, что хотите применить шаблон?",
        get_template_confirm_keyboard(account_id, template_id)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("final_apply_template_"))
async def final_apply_template(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    template_id = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, AccountTemplate, GroupTemplate, GroupSettings

        account = session.query(Account).filter(Account.id == account_id).first()
        template = session.query(AccountTemplate).filter(AccountTemplate.id == template_id).first()

        if not account or not template:
            await callback.answer("❌ Аккаунт или шаблон не найден")
            return

        account.profile_name = template.profile_name
        account.profile_username = template.profile_username
        account.profile_bio = template.profile_bio
        account.profile_photo = template.profile_photo
        account.default_message = template.default_message
        account.message_interval = template.message_interval
        account.default_photo = template.default_photo
        account.default_gif = template.default_gif
        account.default_video = template.default_video
        account.cyrillic_substitution = template.cyrillic_substitution
        account.autoresponder_enabled = template.autoresponder_enabled
        account.autoresponder_first_message = template.autoresponder_first_message
        account.autoresponder_away_message = template.autoresponder_away_message
        account.autoresponder_away_minutes = template.autoresponder_away_minutes

        template_groups = session.query(GroupTemplate).filter(
            GroupTemplate.template_id == template_id
        ).all()

        applied_groups = 0
        for template_group in template_groups:
            group_setting = session.query(GroupSettings).filter(
                GroupSettings.account_id == account_id,
                GroupSettings.group_id == template_group.group_id
            ).first()

            if group_setting:
                group_setting.custom_message = template_group.custom_message
                group_setting.custom_photo = template_group.custom_photo
                group_setting.custom_gif = template_group.custom_gif
                group_setting.custom_video = template_group.custom_video
                group_setting.custom_interval = template_group.custom_interval
                group_setting.is_enabled = template_group.is_enabled
                applied_groups += 1

        session.commit()

        account_groups = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id
        ).all()

        groups_data = [
            {'group_id': group.group_id, 'group_name': group.group_name}
            for group in account_groups
        ]

        if groups_data:
            settings_text = f"<b>⚙️ Настройки аккаунта</b> <code>{account.phone_number}</code>\n\n" \
                           f"👥 <b>Активные группы:</b> {len(groups_data)}\n\nВыберите группу для настройки сообщения, медиа и интервала:"
        else:
            settings_text = f"<b>⚙️ Настройки аккаунта</b> <code>{account.phone_number}</code>\n\n❌ <b>Группы не выбраны</b>\n\nСначала выберите группы в разделе 'Группы' в меню аккаунта."

        success_text = f"✅ <b>Шаблон успешно применен!</b>\n\n"
        success_text += f"📋 <b>Шаблон:</b> {template.name}\n"
        success_text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n"
        success_text += f"📊 <b>Применено:</b>\n"
        success_text += f"• Настройки профиля\n"
        success_text += f"• Общие сообщения и медиа\n"
        success_text += f"• Настройки автоответчика\n"
        success_text += f"• Подмена кириллицы\n"
        success_text += f"• Настройки {applied_groups} групп\n\n"
        success_text += settings_text

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=success_text, parse_mode="HTML"),
            reply_markup=get_account_profile_keyboard(account_id)
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("delete_template_"))
async def delete_template(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    template_id = int(parts[3])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import AccountTemplate, GroupTemplate, GroupSettings, Account

        template = session.query(AccountTemplate).filter(AccountTemplate.id == template_id).first()
        if not template:
            await callback.answer("❌ Шаблон не найден")
            return

        template_name = template.name

        session.query(GroupTemplate).filter(GroupTemplate.template_id == template_id).delete()

        session.delete(template)
        session.commit()

        account_groups = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id
        ).all()

        groups_data = [
            {'group_id': group.group_id, 'group_name': group.group_name}
            for group in account_groups
        ]

        if groups_data:
            settings_text = f"<b>⚙️ Настройки аккаунта</b> <code>{account.phone_number}</code>\n\n" \
                           f"👥 <b>Активные группы:</b> {len(groups_data)}\n\nВыберите группу для настройки сообщения, медиа и интервала:"
        else:
            settings_text = f"<b>⚙️ Настройки аккаунта</b> <code>{account.phone_number}</code>\n\n❌ <b>Группы не выбраны</b>\n\nСначала выберите группы в разделе 'Группы' в меню аккаунта."

        success_text = f"✅ Шаблон '<b>{template_name}</b>' успешно удален!\n\n"
        success_text += settings_text

        account = session.query(Account).filter(Account.id == account_id).first()

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=success_text, parse_mode="HTML"),
            reply_markup=get_account_profile_keyboard(account_id)
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("account_extra_functions_"))
async def account_extra_functions(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[3])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        text = f"🔧 <b>Дополнительные функции</b>\n\n"
        text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n"
        text += "Выберите нужную функцию:"

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=get_account_extra_functions_keyboard(account_id)
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("auto_spam_unlock_"))
async def auto_spam_unlock_toggle(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[3])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        if hasattr(account, 'auto_spam_unlock'):
            account.auto_spam_unlock = not account.auto_spam_unlock
        else:
            account.auto_spam_unlock = True

        session.commit()

        status = "✅ Включен" if getattr(account, 'auto_spam_unlock', False) else "❌ Выключен"

        text = f"🔓 <b>Авто спам анлок</b>\n\n"
        text += f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n"
        text += f"🔄 <b>Статус:</b> {status}\n\n"
        if getattr(account, 'auto_spam_unlock', False):
            text += "При получении флудвейта бот автоматически попытается снять спам через @SpamBot\n\n"
            text += "⚠️ <b>Работает только для премиум аккаунтов Telegram</b>"
        else:
            text += "Автоматическое снятие спама отключено"

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=get_account_extra_functions_keyboard(account_id)
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("toggle_group_v2_"))
async def toggle_group_v2(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    group_id = int(parts[4])
    page = int(parts[5])

    data = await state.get_data()
    groups = data.get('groups', [])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        groups_dict = {g['id']: g for g in groups}

        from utils.group_id_helper import normalize_group_id
        normalized_group_id = normalize_group_id(group_id)

        existing_setting = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == normalized_group_id
        ).first()

        if existing_setting and existing_setting.is_enabled:
            existing_setting.is_enabled = False
            session.commit()

            selected_group_settings = session.query(GroupSettings).filter(
                GroupSettings.account_id == account_id,
                GroupSettings.is_enabled == True
            ).all()
            selected_groups = []
            for setting in selected_group_settings:
                try:
                    group_id_int = int(setting.group_id)
                    selected_groups.append(group_id_int)
                except ValueError:
                    logger.warning(f"Не удалось преобразовать group_id '{setting.group_id}' в число")
                    continue


            await callback.answer("❌ Группа убрана из выбранных")
        else:
            if existing_setting:
                existing_setting.is_enabled = True
            else:
                double_check = session.query(GroupSettings).filter(
                    GroupSettings.account_id == account_id,
                    GroupSettings.group_id == normalized_group_id
                ).first()

                if double_check:
                    double_check.is_enabled = True
                else:
                    group_info = groups_dict.get(group_id, {})
                    new_setting = GroupSettings(
                        account_id=account_id,
                        group_id=normalized_group_id,
                        group_name=group_info.get('title', 'Unknown'),
                        is_enabled=True,
                        custom_message=account.default_message,
                        custom_interval=None,
                        slowmode_seconds=group_info.get('slowmode_seconds', 0),
                        slowmode_minutes=group_info.get('slowmode_minutes', 0)
                    )
                    session.add(new_setting)

            session.commit()

            selected_group_settings = session.query(GroupSettings).filter(
                GroupSettings.account_id == account_id,
                GroupSettings.is_enabled == True
            ).all()
            selected_groups = []
            for setting in selected_group_settings:
                try:
                    group_id_int = int(setting.group_id)
                    selected_groups.append(group_id_int)
                except ValueError:
                    logger.warning(f"Не удалось преобразовать group_id '{setting.group_id}' в число")
                    continue


            await callback.answer("✅ Группа добавлена в выбранные")

        await state.update_data(selected_groups=selected_groups)

        await safe_edit_message(
            callback.message,
            f"👥 <b>Группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
            f"📊 <b>Найдено доступных групп:</b> {len(groups)}\n"
            f"✅ <b>Выбрано:</b> {len(selected_groups)}\n\n"
            "💡 <i>Показаны только группы, где аккаунт может отправлять сообщения</i>\n\n"
            "Выберите группы для рассылки:",
            get_groups_selection_keyboard_v2(groups, account_id, page, selected_groups)
        )

    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("groups_page_v2_"))
async def groups_page_v2(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    page = int(parts[4])

    data = await state.get_data()
    groups = data.get('groups', [])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        selected_group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.is_enabled == True
        ).all()
        selected_groups = []
        for setting in selected_group_settings:
            try:
                group_id_int = int(setting.group_id)
                selected_groups.append(group_id_int)
            except ValueError:
                logger.warning(f"Не удалось преобразовать group_id '{setting.group_id}' в число")
                continue

        await state.update_data(selected_groups=selected_groups)

        await safe_edit_message(
            callback.message,
            f"👥 <b>Группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
            f"📊 <b>Найдено доступных групп:</b> {len(groups)}\n"
            f"✅ <b>Выбрано:</b> {len(selected_groups)}\n\n"
            "💡 <i>Показаны только группы, где аккаунт может отправлять сообщения</i>\n\n"
            "Выберите группы для рассылки:",
            get_groups_selection_keyboard_v2(groups, account_id, page, selected_groups)
        )

    finally:
        db.close_session(session)

    await callback.answer(f"📄 Страница {page + 1}")

@router.callback_query(F.data.startswith("select_all_groups_v2_"))
async def select_all_groups_v2(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[4])
    page = int(parts[5])

    data = await state.get_data()
    groups = data.get('groups', [])

    all_group_ids = [group['id'] for group in groups]

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        groups_dict = {g['id']: g for g in groups}

        existing_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id
        ).all()
        existing_dict = {int(setting.group_id): setting for setting in existing_settings}

        for group_id in all_group_ids:
            if group_id in existing_dict:
                existing_dict[group_id].is_enabled = True
            else:
                from utils.group_id_helper import normalize_group_id
                normalized_group_id = normalize_group_id(group_id)

                double_check = session.query(GroupSettings).filter(
                    GroupSettings.account_id == account_id,
                    GroupSettings.group_id == normalized_group_id
                ).first()

                if double_check:
                    double_check.is_enabled = True
                    existing_dict[group_id] = double_check
                else:
                    group_info = groups_dict.get(group_id, {})
                    new_setting = GroupSettings(
                        account_id=account_id,
                        group_id=normalized_group_id,
                        group_name=group_info.get('title', 'Unknown'),
                        is_enabled=True,
                        custom_message=account.default_message,
                        custom_interval=None,
                        slowmode_seconds=group_info.get('slowmode_seconds', 0),
                        slowmode_minutes=group_info.get('slowmode_minutes', 0)
                    )
                    session.add(new_setting)

        session.commit()

        selected_groups = all_group_ids.copy()
        await state.update_data(selected_groups=selected_groups)

        await safe_edit_message(
            callback.message,
            f"👥 <b>Группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
            f"📊 <b>Найдено доступных групп:</b> {len(groups)}\n"
            f"✅ <b>Выбрано:</b> {len(selected_groups)}\n\n"
            "💡 <i>Показаны только группы, где аккаунт может отправлять сообщения</i>\n\n"
            "Выберите группы для рассылки:",
            get_groups_selection_keyboard_v2(groups, account_id, page, selected_groups)
        )

    finally:
        db.close_session(session)

    await callback.answer("✅ Все группы выбраны!")

@router.callback_query(F.data.startswith("deselect_all_groups_v2_"))
async def deselect_all_groups_v2(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[4])
    page = int(parts[5])

    data = await state.get_data()
    groups = data.get('groups', [])
    selected_groups = []

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        existing_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id
        ).all()

        for setting in existing_settings:
            setting.is_enabled = False

        session.commit()

        await state.update_data(selected_groups=selected_groups)

        await safe_edit_message(
            callback.message,
            f"👥 <b>Группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
            f"📊 <b>Найдено доступных групп:</b> {len(groups)}\n"
            f"✅ <b>Выбрано:</b> {len(selected_groups)}\n\n"
            "💡 <i>Показаны только группы, где аккаунт может отправлять сообщения</i>\n\n"
            "Выберите группы для рассылки:",
            get_groups_selection_keyboard_v2(groups, account_id, page, selected_groups)
        )

    finally:
        db.close_session(session)

    await callback.answer("❌ Выбор всех групп снят!")

async def get_group_real_name(account, group_id):
    logger.info(f"🔍 Получение названия для группы {group_id}")

    try:
        proxy_config = None
        if account.proxy_id:
            proxy = get_proxy_by_id(account.proxy_id)
            if proxy:
                proxy_data = {
                    'host': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'proxy_type': proxy.proxy_type
                }
                proxy_config = get_telethon_proxy_config(proxy_data)

        client = TelegramClient(
            StringSession(account.session_string),
            account.api_id,
            account.api_hash,
            proxy=proxy_config,
            timeout=10,
            system_version="4.16.30-vxCUSTOM",
            device_model="Desktop",
            app_version="4.16.30"
        )

        await client.connect()
        logger.info(f"📱 Новый клиент создан и подключен для {account.phone_number}")

        if await client.is_user_authorized():
            logger.info(f"✅ Клиент авторизован, запрашиваем entity для {group_id}")

            entity = None
            group_id_int = int(group_id)

            try:
                entity = await client.get_entity(group_id_int)
                logger.info(f"📋 Получен entity (ID как есть): {type(entity).__name__}")
            except Exception as e1:
                logger.warning(f"⚠️ Не удалось получить entity с ID {group_id_int}: {e1}")

                if group_id_int > 0:
                    try:
                        negative_id = -group_id_int
                        entity = await client.get_entity(negative_id)
                        logger.info(f"📋 Получен entity (отрицательный ID {negative_id}): {type(entity).__name__}")
                    except Exception as e2:
                        logger.warning(f"⚠️ Не удалось получить entity с отрицательным ID {negative_id}: {e2}")

                        try:
                            supergroup_id = -1000000000000 - group_id_int
                            entity = await client.get_entity(supergroup_id)
                            logger.info(f"📋 Получен entity (супергруппа ID {supergroup_id}): {type(entity).__name__}")
                        except Exception as e3:
                            logger.warning(f"⚠️ Не удалось получить entity с супергруппа ID {supergroup_id}: {e3}")

            if entity and hasattr(entity, 'title') and entity.title:
                logger.info(f"✅ Получено название: '{entity.title}' для группы {group_id}")
                await client.disconnect()
                return entity.title
            else:
                logger.warning(f"⚠️ Не удалось получить название для группы {group_id}")
        else:
            logger.warning(f"❌ Клиент не авторизован для аккаунта {account.phone_number}")

        await client.disconnect()

    except Exception as e:
        logger.error(f"❌ Ошибка при получении названия для группы {group_id}: {e}")
        try:
            await client.disconnect()
        except:
            pass

    logger.info(f"🔄 Fallback: ищем название в базе данных")
    try:
        from database.database import db
        session = db.get_session()
        try:
            from database.models import GroupSettings

            group_id_str = str(group_id)
            group_id_int = int(group_id)
            search_ids = [
                group_id_str,
                str(-group_id_int),
                str(abs(group_id_int)),
                str(-1000000000000 - group_id_int) if group_id_int > 0 else str(group_id_int)
            ]

            for search_id in search_ids:
                other_group = session.query(GroupSettings).filter(
                    GroupSettings.account_id == account.id,
                    GroupSettings.group_id == search_id,
                    GroupSettings.group_name.isnot(None),
                    GroupSettings.group_name != "",
                    GroupSettings.group_name != "Unknown",
                    GroupSettings.group_name != search_id
                ).first()

                if other_group and other_group.group_name:
                    if not other_group.group_name.isdigit():
                        logger.info(f"✅ Найдено название в БД: '{other_group.group_name}' для группы {group_id} (по ID {search_id})")
                        return other_group.group_name
                    else:
                        logger.debug(f"⚠️ Пропускаем запись с названием-ID: '{other_group.group_name}'")

            logger.info(f"⚠️ В БД не найдено подходящее название для группы {group_id}")
        finally:
            db.close_session(session)
    except Exception as e:
        logger.error(f"❌ Ошибка поиска в БД для группы {group_id}: {e}")

    logger.info(f"🔄 Дополнительный fallback: запрашиваем актуальный список групп")
    try:
        current_groups = await get_account_groups(account)
        group_id_int = int(group_id)

        for group in current_groups:
            if group.get('id') == group_id_int or group.get('id') == -group_id_int:
                group_title = group.get('title', '')
                if group_title and group_title != 'Unknown':
                    logger.info(f"✅ Найдено название в актуальном списке: '{group_title}' для группы {group_id}")
                    return group_title

        logger.info(f"⚠️ Группа {group_id} не найдена в актуальном списке")
    except Exception as e:
        logger.error(f"❌ Ошибка получения актуального списка групп: {e}")

    try:
        group_id_display = int(group_id)
        if group_id_display < 0:
            fallback_name = f"Группа {abs(group_id_display)}"
        else:
            fallback_name = f"Чат {group_id_display}"
        logger.info(f"🎨 Fallback название: '{fallback_name}' для группы {group_id}")
        return fallback_name
    except (ValueError, TypeError):
        fallback_name = f"Группа {group_id}"
        logger.info(f"🎨 Финальный fallback: '{fallback_name}' для группы {group_id}")
        return fallback_name

@router.callback_query(F.data.startswith("individual_group_settings_"))
async def individual_group_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    account_id = int(callback.data.split("_")[3])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, GroupSettings

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        enabled_groups = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.is_enabled == True
        ).all()

        logger.info(f"🔄 Обновление названий {len(enabled_groups)} групп для аккаунта {account_id}")
        updated_count = 0

        for group_setting in enabled_groups:
            real_name = await get_group_real_name(account, group_setting.group_id)
            old_name = group_setting.group_name or "None"

            if group_setting.group_name != real_name:
                group_setting.group_name = real_name
                updated_count += 1
                logger.info(f"🔄 Обновлено: {group_setting.group_id} '{old_name}' -> '{real_name}'")
            else:
                logger.debug(f"✅ Актуально: {group_setting.group_id} '{real_name}'")

        if updated_count > 0:
            session.commit()
            logger.info(f"✅ Сохранены названия {updated_count} групп в базу данных")
        else:
            logger.info(f"ℹ️ Все названия групп уже актуальны")

        if enabled_groups:
            text = f"<b>⚙️ Индивидуальные настройки групп</b>\n\n" \
                   f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n" \
                   f"👥 <b>Активные группы:</b> {len(enabled_groups)}\n\n" \
                   "Выберите группу для настройки сообщения, медиа и интервала:"
        else:
            text = f"<b>⚙️ Индивидуальные настройки групп</b>\n\n" \
                   f"📱 <b>Аккаунт:</b> <code>{account.phone_number}</code>\n\n" \
                   "❌ <b>Нет активных групп</b>\n\n" \
                   "Сначала выберите группы в разделе 'Группы' в меню аккаунта."

        keyboard = get_individual_group_settings_keyboard(account_id, enabled_groups)

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=keyboard
        )

    finally:
        db.close_session(session)

    await callback.answer()


@router.callback_query(F.data.startswith("super_groups_") & ~F.data.startswith("super_groups_topics_") & ~F.data.startswith("super_groups_page_"))
async def super_groups_main(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        await safe_edit_message(
            callback.message,
            f"🔄 <b>Загружаем группы с темами</b>\n\n"
            f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
            "⏳ Получаем все диалоги...\n"
            "🔍 Ищем группы с темами...\n"
            "🔒 Проверяем права доступа к темам...\n"
            "Подождите, это может занять некоторое время...",
            None
        )

        groups_with_topics = await get_account_groups_with_topics(account)

        if not groups_with_topics:
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(
                text="🔍 Диагностика доступа к темам",
                callback_data=f"diagnose_topics_{account_id}"
            ))
            builder.add(InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"account_settings_{account_id}"
            ))
            builder.adjust(1)

            await safe_edit_message(
                callback.message,
                f"❌ <b>Нет доступных тем</b>\n\n"
                f"Аккаунт <code>{account.phone_number}</code> не имеет доступа к темам.\n\n"
                "🔍 <b>Возможные причины:</b>\n"
                "• Нет групп с включенным форумом\n"
                "• Темы закрыты или архивированы\n"
                "• Ограничены права на отправку сообщений\n"
                "• Пользователь забанен в темах\n\n"
                "💡 <i>Нажмите \"Диагностика\" для подробного анализа</i>",
                builder.as_markup()
            )
            return

        from database.models import SelectedTopics

        selected_topics_db = session.query(SelectedTopics).filter(
            SelectedTopics.account_id == account_id,
            SelectedTopics.is_enabled == True
        ).all()

        selected_topics = [f"{topic.group_id}_{topic.topic_id}" for topic in selected_topics_db]

        logger.info(f"Загружено выбранных тем из БД: {len(selected_topics_db)}")
        logger.info(f"Выбранные темы: {selected_topics}")

        await state.update_data(
            groups_with_topics=groups_with_topics,
            account_id=account_id,
            selected_super_groups_topics=selected_topics
        )

        total_topics = sum(len(group.get('topics', [])) for group in groups_with_topics)

        logger.info(f"Инициализация супер групп: найдено {len(groups_with_topics)} групп, {total_topics} тем")
        logger.info(f"Состояние инициализировано: selected_super_groups_topics={selected_topics}")

        await safe_edit_message(
            callback.message,
            f"✨ <b>Группы с темами</b>\n\n"
            f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
            f"📊 <b>Найдено тем:</b> {total_topics}\n"
            f"✅ <b>Выбрано тем:</b> {len(selected_topics)}\n\n"
            "Выберите темы для настройки:",
            get_super_groups_topics_keyboard(groups_with_topics, account_id, 0, selected_topics)
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("toggle_super_group_topic_"))
async def toggle_super_group_topic(callback: CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    logger.info(f"Парсинг callback_data: {callback.data}")
    logger.info(f"Data parts: {data_parts}")

    account_id = int(data_parts[4])
    page = int(data_parts[-1])

    topic_data = "_".join(data_parts[5:-1])

    logger.info(f"Account ID: {account_id}")
    logger.info(f"Topic data: {topic_data}")
    logger.info(f"Page: {page}")

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SelectedTopics

        selected_topics_db = session.query(SelectedTopics).filter(
            SelectedTopics.account_id == account_id,
            SelectedTopics.is_enabled == True
        ).all()

        selected_topics = [f"{topic.group_id}_{topic.topic_id}" for topic in selected_topics_db]

        selected_topics = selected_topics.copy()

        logger.info(f"Переключение темы: {topic_data}")
        logger.info(f"Текущие выбранные темы: {selected_topics}")
        logger.info(f"Страница: {page}")

        if topic_data in selected_topics:
            selected_topics.remove(topic_data)
            logger.info(f"Убрана тема: {topic_data}")
            action_text = "убрана"

            group_id, topic_id = topic_data.split('_')
            session.query(SelectedTopics).filter(
                SelectedTopics.account_id == account_id,
                SelectedTopics.group_id == group_id,
                SelectedTopics.topic_id == topic_id
            ).delete()

            from database.models import SuperGroup
            super_group = session.query(SuperGroup).filter(
                SuperGroup.account_id == account_id,
                SuperGroup.base_group_id == str(group_id),
                SuperGroup.topic_id == str(topic_id)
            ).first()
            if super_group:
                super_group.is_enabled = False
                logger.info(f"Отключена SuperGroup для темы: {topic_data}")
        else:
            selected_topics.append(topic_data)
            logger.info(f"Добавлена тема: {topic_data}")
            action_text = "добавлена"

            group_id, topic_id = topic_data.split('_')

            group_info = None
            topic_info = None
            for group in groups_with_topics:
                if str(group['id']) == str(group_id):
                    group_info = group
                    for topic in group.get('topics', []):
                        if topic['id'] == int(topic_id):
                            topic_info = topic
                            break
                    break

            if group_info and topic_info:
                selected_topic = SelectedTopics(
                    account_id=account_id,
                    group_id=str(group_id),
                    group_name=group_info['title'],
                    topic_id=str(topic_id),
                    topic_name=topic_info['title'],
                    is_enabled=True
                )
                session.add(selected_topic)

                from database.models import SuperGroup
                super_group = session.query(SuperGroup).filter(
                    SuperGroup.account_id == account_id,
                    SuperGroup.base_group_id == str(group_id),
                    SuperGroup.topic_id == str(topic_id)
                ).first()
                if super_group:
                    super_group.is_enabled = True
                    logger.info(f"Включена SuperGroup для темы: {topic_data}")

        session.commit()

        logger.info(f"Новые выбранные темы: {selected_topics}")
        logger.info(f"Тип selected_topics: {type(selected_topics)}")

        await state.update_data(selected_super_groups_topics=selected_topics)

    except Exception as e:
        logger.error(f"Ошибка при переключении темы: {e}")
        action_text = "ошибка"
    finally:
        db.close_session(session)

    updated_data = await state.get_data()
    logger.info(f"Состояние после обновления: {updated_data.get('selected_super_groups_topics', [])}")

    total_topics = sum(len(group.get('topics', [])) for group in groups_with_topics)

    await safe_edit_message(
        callback.message,
        f"✨ <b>Группы с темами</b>\n\n"
        f"📱 Аккаунт: <code>{account_id}</code>\n"
        f"📊 <b>Найдено тем:</b> {total_topics}\n"
        f"✅ <b>Выбрано тем:</b> {len(selected_topics)}\n\n"
        "Выберите темы для настройки:",
        get_super_groups_topics_keyboard(groups_with_topics, account_id, page, selected_topics)
    )

    await callback.answer(f"✅ Тема {action_text}")

@router.callback_query(F.data.startswith("super_groups_topics_page_"))
async def super_groups_topics_page(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[4])
    page = int(parts[5])

    logger.info(f"Навигация: callback_data={callback.data}, account_id={account_id}, page={page}")

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SelectedTopics

        selected_topics_db = session.query(SelectedTopics).filter(
            SelectedTopics.account_id == account_id,
            SelectedTopics.is_enabled == True
        ).all()

        selected_topics = [f"{topic.group_id}_{topic.topic_id}" for topic in selected_topics_db]

        logger.info(f"Навигация на страницу {page}, загружено выбранных тем из БД: {len(selected_topics_db)}")
        logger.info(f"Выбранные темы при навигации: {selected_topics}")

        await state.update_data(selected_super_groups_topics=selected_topics)

    except Exception as e:
        logger.error(f"Ошибка загрузки тем из БД при навигации: {e}")
        selected_topics = []
    finally:
        db.close_session(session)

    total_topics = sum(len(group.get('topics', [])) for group in groups_with_topics)

    await safe_edit_message(
        callback.message,
        f"✨ <b>Группы с темами</b>\n\n"
        f"📱 Аккаунт: <code>{account_id}</code>\n"
        f"📊 <b>Найдено тем:</b> {total_topics}\n"
        f"✅ <b>Выбрано тем:</b> {len(selected_topics)}\n\n"
        "Выберите темы для настройки:",
        get_super_groups_topics_keyboard(groups_with_topics, account_id, page, selected_topics)
    )

    await callback.answer(f"📄 Страница {page + 1}")

@router.callback_query(F.data.startswith("select_all_super_groups_topics_"))
async def select_all_super_groups_topics(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[5])
    page = int(parts[6])

    logger.info(f"Выбор всех тем: callback_data={callback.data}, account_id={account_id}, page={page}")

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SelectedTopics

        from database.models import SuperGroup

        session.query(SelectedTopics).filter(SelectedTopics.account_id == account_id).delete()

        session.query(SuperGroup).filter(SuperGroup.account_id == account_id).update({SuperGroup.is_enabled: False})

        selected_topics = []
        for group in groups_with_topics:
            group_id = group['id']
            topics = group.get('topics', [])
            for topic in topics:
                topic_data = f"{group_id}_{topic['id']}"
                selected_topics.append(topic_data)
                logger.info(f"Added topic: {topic_data} for group {group['title']}")

                selected_topic = SelectedTopics(
                    account_id=account_id,
                    group_id=str(group_id),
                    group_name=group['title'],
                    topic_id=str(topic['id']),
                    topic_name=topic['title'],
                    is_enabled=True
                )
                session.add(selected_topic)

                super_group = session.query(SuperGroup).filter(
                    SuperGroup.account_id == account_id,
                    SuperGroup.base_group_id == str(group_id),
                    SuperGroup.topic_id == str(topic['id'])
                ).first()
                if super_group:
                    super_group.is_enabled = True
                    logger.info(f"Включена SuperGroup для темы: {topic_data}")

        session.commit()

        logger.info(f"Выбраны все темы: {selected_topics}")
        await state.update_data(selected_super_groups_topics=selected_topics)

    except Exception as e:
        logger.error(f"Ошибка при выборе всех тем: {e}")
        selected_topics = []
    finally:
        db.close_session(session)

    total_topics = sum(len(group.get('topics', [])) for group in groups_with_topics)

    await safe_edit_message(
        callback.message,
        f"✨ <b>Группы с темами</b>\n\n"
        f"📱 Аккаунт: <code>{account_id}</code>\n"
        f"📊 <b>Найдено тем:</b> {total_topics}\n"
        f"✅ <b>Выбрано тем:</b> {len(selected_topics)}\n\n"
        "Выберите темы для настройки:",
        get_super_groups_topics_keyboard(groups_with_topics, account_id, page, selected_topics)
    )

    await callback.answer(f"✅ Выбраны все темы ({len(selected_topics)} шт.)")

@router.callback_query(F.data.startswith("deselect_all_super_groups_topics_"))
async def deselect_all_super_groups_topics(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[5])
    page = int(parts[6])

    logger.info(f"Отмена выбора всех тем: callback_data={callback.data}, account_id={account_id}, page={page}")

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SelectedTopics, SuperGroup

        session.query(SelectedTopics).filter(SelectedTopics.account_id == account_id).delete()

        session.query(SuperGroup).filter(SuperGroup.account_id == account_id).update({SuperGroup.is_enabled: False})
        logger.info(f"Отключены все SuperGroup для аккаунта {account_id}")

        session.commit()

        await state.update_data(selected_super_groups_topics=[])

    except Exception as e:
        logger.error(f"Ошибка при отмене выбора всех тем: {e}")
    finally:
        db.close_session(session)

    total_topics = sum(len(group.get('topics', [])) for group in groups_with_topics)

    await safe_edit_message(
        callback.message,
        f"✨ <b>Группы с темами</b>\n\n"
        f"📱 Аккаунт: <code>{account_id}</code>\n"
        f"📊 <b>Найдено тем:</b> {total_topics}\n"
        f"✅ <b>Выбрано тем:</b> 0\n\n"
        "Выберите темы для настройки:",
        get_super_groups_topics_keyboard(groups_with_topics, account_id, page, [])
    )

    await callback.answer("✅ Выбор всех тем отменен")

@router.callback_query(F.data.startswith("individual_super_groups_topics_"))
async def individual_super_groups_topics(callback: CallbackQuery, state: FSMContext):
    import logging
    logger = logging.getLogger(__name__)

    account_id = int(callback.data.split("_")[4])

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])
    selected_topics = data.get('selected_super_groups_topics', [])

    logger.info(f"individual_super_groups_topics: account_id={account_id}")
    logger.info(f"individual_super_groups_topics: selected_topics={selected_topics}")
    logger.info(f"individual_super_groups_topics: groups_with_topics count={len(groups_with_topics)}")

    if not selected_topics:
        from database.database import db
        session = db.get_session()
        try:
            from database.models import SelectedTopics

            selected_topics_db = session.query(SelectedTopics).filter(
                SelectedTopics.account_id == account_id,
                SelectedTopics.is_enabled == True
            ).all()

            if selected_topics_db:
                selected_topics = [f"{topic.group_id}_{topic.topic_id}" for topic in selected_topics_db]

                if not groups_with_topics:
                    groups_with_topics = []
                    for topic in selected_topics_db:
                        groups_with_topics.append({
                            'id': topic.group_id,
                            'title': topic.group_name,
                            'topics': [{
                                'id': int(topic.topic_id),
                                'title': topic.topic_name
                            }]
                        })
            else:
                await callback.answer("❌ Не выбрано ни одной темы")
                return

        except Exception as e:
            logger.error(f"Ошибка загрузки тем из БД: {e}")
            await callback.answer("❌ Ошибка загрузки тем")
            return
        finally:
            db.close_session(session)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SuperGroup, SelectedTopics

        created_count = 0
        for topic_data in selected_topics:
            group_id, topic_id = topic_data.split('_')
            group_id = int(group_id)
            topic_id = int(topic_id)

            group_info = None
            topic_info = None
            for group in groups_with_topics:
                logger.info(f"Comparing in individual_super_groups_topics: group['id']='{str(group['id'])}' with group_id='{str(group_id)}'")
                if str(group['id']) == str(group_id):
                    group_info = group
                    for topic in group.get('topics', []):
                        if topic['id'] == topic_id:
                            topic_info = topic
                            break
                    break

            if not group_info or not topic_info:
                continue

            existing = session.query(SuperGroup).filter(
                SuperGroup.account_id == account_id,
                SuperGroup.base_group_id == str(group_id),
                SuperGroup.topic_id == str(topic_id)
            ).first()

            if not existing:
                super_group = SuperGroup(
                    account_id=account_id,
                    base_group_id=str(group_id),
                    base_group_name=group_info['title'],
                    topic_name=topic_info['title'],
                    topic_id=str(topic_id),
                    is_enabled=True
                )
                session.add(super_group)
                created_count += 1

            existing_selected = session.query(SelectedTopics).filter(
                SelectedTopics.account_id == account_id,
                SelectedTopics.group_id == str(group_id),
                SelectedTopics.topic_id == str(topic_id)
            ).first()

            if not existing_selected:
                selected_topic = SelectedTopics(
                    account_id=account_id,
                    group_id=str(group_id),
                    group_name=group_info['title'],
                    topic_id=str(topic_id),
                    topic_name=topic_info['title'],
                    is_enabled=True
                )
                session.add(selected_topic)

        session.commit()

        await show_individual_topics_menu(callback, account_id, selected_topics, groups_with_topics)

    except Exception as e:
        logger.error(f"Ошибка сохранения тем: {e}")
        await callback.answer("❌ Ошибка сохранения тем")
    finally:
        db.close_session(session)

async def show_individual_topics_menu(callback: CallbackQuery, account_id: int, selected_topics: list = None, groups_with_topics: list = None):
    import logging
    logger = logging.getLogger(__name__)

    from keyboards.keyboards import get_account_settings_keyboard

    if selected_topics is None or groups_with_topics is None:
        from database.database import db
        session = db.get_session()
        try:
            from database.models import SelectedTopics, SuperGroup

            selected_topics_db = session.query(SelectedTopics).filter(
                SelectedTopics.account_id == account_id,
                SelectedTopics.is_enabled == True
            ).all()

            if not selected_topics_db:
                super_groups_db = session.query(SuperGroup).filter(
                    SuperGroup.account_id == account_id,
                    SuperGroup.is_enabled == True
                ).all()

                if super_groups_db:
                    selected_topics = [f"{sg.base_group_id}_{sg.topic_id}" for sg in super_groups_db]

                    groups_with_topics = []
                    for sg in super_groups_db:
                        groups_with_topics.append({
                            'id': sg.base_group_id,
                            'title': sg.base_group_name,
                            'topics': [{
                                'id': int(sg.topic_id),
                                'title': sg.topic_name
                            }]
                        })
                else:
                    from database.models import Account
                    account = session.query(Account).filter(Account.id == account_id).first()
                    account_display = account.phone_number if account else f"Аккаунт {account_id}"

                    await safe_edit_message(
                        callback.message,
                        f"❌ <b>Нет сохраненных тем</b>\n\n"
                        f"Аккаунт: <code>{account_display}</code>\n\n"
                        "Сначала выберите темы для настройки.",
                        get_account_settings_keyboard(account_id)
                    )
                    return
            else:
                selected_topics = [f"{topic.group_id}_{topic.topic_id}" for topic in selected_topics_db]

                groups_with_topics = []
                for topic in selected_topics_db:
                    groups_with_topics.append({
                        'id': topic.group_id,
                        'title': topic.group_name,
                        'topics': [{
                            'id': int(topic.topic_id),
                            'title': topic.topic_name
                        }]
                    })

        except Exception as e:
            logger.error(f"Ошибка загрузки тем из БД: {e}")
            await callback.answer("❌ Ошибка загрузки тем")
            return
        finally:
            db.close_session(session)

    logger.info(f"show_individual_topics_menu: selected_topics={selected_topics}")
    logger.info(f"show_individual_topics_menu: groups_with_topics count={len(groups_with_topics)}")

    topics_info = []
    for topic_data in selected_topics:
        logger.info(f"Processing topic_data: {topic_data}")
        group_id, topic_id = topic_data.split('_')
        group_id = int(group_id)
        topic_id = int(topic_id)

        logger.info(f"Parsed: group_id={group_id}, topic_id={topic_id}")

        found = False
        for group in groups_with_topics:
            group_storage_id = str(group['id'])
            logger.info(f"Comparing: group_storage_id='{group_storage_id}' with group_id='{str(group_id)}'")
            if group_storage_id == str(group_id):
                logger.info(f"Found group: {group['title']} (storage_id: {group_storage_id})")
                for topic in group.get('topics', []):
                    if topic['id'] == topic_id:
                        logger.info(f"Found topic: {topic['title']}")
                        topics_info.append({
                            'group_title': group['title'],
                            'topic_title': topic['title'],
                            'topic_data': topic_data
                        })
                        found = True
                        break
                if found:
                    break

        if not found:
            logger.warning(f"Topic not found: group_id={group_id}, topic_id={topic_id}")
            logger.warning(f"Available groups: {[{'id': str(g['id']), 'title': g['title']} for g in groups_with_topics]}")

    logger.info(f"Collected topics_info: {topics_info}")

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()
        account_display = account.phone_number if account else f"Аккаунт {account_id}"
    except Exception as e:
        logger.error(f"Ошибка получения информации об аккаунте: {e}")
        account_display = f"Аккаунт {account_id}"
    finally:
        db.close_session(session)

    text = f"⚙️ <b>Индивидуальные настройки тем</b>\n\n"
    text += f"📱 Аккаунт: <code>{account_display}</code>\n"
    text += f"✅ <b>Выбрано тем:</b> {len(selected_topics)}\n\n"
    text += "<b>Выбранные темы:</b>\n"

    if topics_info:
        for i, topic_info in enumerate(topics_info, 1):
            text += f"{i}. <b>{topic_info['group_title']}</b> | Тема: {topic_info['topic_title']}\n"
    else:
        text += "❌ <i>Темы не найдены</i>\n"

    text += "\nВыберите тему для настройки:"

    from keyboards.keyboards import get_individual_topics_menu_keyboard
    keyboard = get_individual_topics_menu_keyboard(account_id, topics_info)

    await safe_edit_message(callback.message, text, keyboard)

@router.callback_query(F.data.startswith("individual_topic_settings_"))
async def individual_topic_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    parts = callback.data.split("_")
    account_id = int(parts[3])
    topic_data = "_".join(parts[4:])

    group_id, topic_id = topic_data.split('_')
    group_id = int(group_id)
    topic_id = int(topic_id)

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    if not groups_with_topics:
        from database.database import db
        session = db.get_session()
        try:
            from database.models import SelectedTopics

            selected_topics_db = session.query(SelectedTopics).filter(
                SelectedTopics.account_id == account_id,
                SelectedTopics.is_enabled == True
            ).all()

            if selected_topics_db:
                groups_dict = {}
                for topic in selected_topics_db:
                    if topic.group_id not in groups_dict:
                        groups_dict[topic.group_id] = {
                            'id': topic.group_id,
                            'title': topic.group_name,
                            'topics': []
                        }
                    groups_dict[topic.group_id]['topics'].append({
                        'id': int(topic.topic_id),
                        'title': topic.topic_name
                    })

                groups_with_topics = list(groups_dict.values())
                logger.info(f"Восстановлены данные groups_with_topics из БД: {len(groups_with_topics)} групп")

                await state.update_data(groups_with_topics=groups_with_topics)
            else:
                from database.models import SuperGroup
                super_group = session.query(SuperGroup).filter(
                    SuperGroup.account_id == account_id,
                    SuperGroup.base_group_id == str(group_id),
                    SuperGroup.topic_id == str(topic_id)
                ).first()

                if super_group:
                    groups_with_topics = [{
                        'id': int(super_group.base_group_id),
                        'title': super_group.base_group_name,
                        'topics': [{
                            'id': int(super_group.topic_id),
                            'title': super_group.topic_name
                        }]
                    }]
                    logger.info(f"Создана структура groups_with_topics из SuperGroup")

                    await state.update_data(groups_with_topics=groups_with_topics)
        except Exception as e:
            logger.error(f"Ошибка восстановления данных для individual_topic_settings: {e}")
        finally:
            db.close_session(session)

    group_info = None
    topic_info = None
    for group in groups_with_topics:
        logger.info(f"Comparing in individual_topic_settings: group['id']='{str(group['id'])}' with group_id='{str(group_id)}'")
        if str(group['id']) == str(group_id):
            group_info = group
            for topic in group.get('topics', []):
                if topic['id'] == topic_id:
                    topic_info = topic
                    break
            break

    if not group_info or not topic_info:
        await callback.answer("❌ Тема не найдена")
        return

    text = build_topic_settings_text(account_id, topic_data, for_caption=True)

    keyboard = get_topic_settings_keyboard(account_id, topic_data)

    try:
        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.edit_message_media(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            media=InputMediaPhoto(media=mailer_image, caption=text, parse_mode="HTML"),
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Не удалось отредактировать сообщение: {e}")
        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("topic_message_"))
async def topic_message_settings(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    topic_data = "_".join(parts[3:])

    await state.update_data(
        current_topic_data=topic_data,
        current_account_id=account_id
    )

    await state.set_state(AccountStates.waiting_for_topic_message)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup

        account = session.query(Account).filter(Account.id == account_id).first()

        group_id, topic_id = topic_data.split('_')
        group_id = int(group_id)
        topic_id = int(topic_id)

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        account_display = account.phone_number if account else f"Аккаунт {account_id}"
        group_name = super_group.base_group_name if super_group else f"Группа {group_id}"
        topic_name = super_group.topic_name if super_group else f"Тема {topic_id}"

    except Exception as e:
        logger.error(f"Ошибка получения информации для отображения: {e}")
        account_display = f"Аккаунт {account_id}"
        group_name = f"Группа {group_id}"
        topic_name = f"Тема {topic_id}"
    finally:
        db.close_session(session)

    mailer_image = FSInputFile("img_static/mailer.png")
    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(
            media=mailer_image,
            caption=f"💬 <b>Настройка сообщения для темы</b>\n\n"
                    f"📱 Аккаунт: <code>{account_display}</code>\n"
                    f"📝 Тема: <b>{group_name} | {topic_name}</b>\n\n"
                    "Отправьте сообщение для рассылки в эту тему:\n\n"
                    "💡 <i>Для удаления сообщения отправьте 0</i>",
            parse_mode="HTML"
        ),
        reply_markup=get_message_edit_cancel_keyboard()
    )

@router.callback_query(F.data.startswith("topic_media_"))
async def topic_media_settings(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    topic_data = "_".join(parts[3:])

    await state.update_data(
        current_topic_data=topic_data,
        current_account_id=account_id
    )

    await state.set_state(AccountStates.waiting_for_topic_media)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup

        account = session.query(Account).filter(Account.id == account_id).first()

        group_id, topic_id = topic_data.split('_')
        group_id = int(group_id)
        topic_id = int(topic_id)

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        account_display = account.phone_number if account else f"Аккаунт {account_id}"
        group_name = super_group.base_group_name if super_group else f"Группа {group_id}"
        topic_name = super_group.topic_name if super_group else f"Тема {topic_id}"

    except Exception as e:
        logger.error(f"Ошибка получения информации для отображения: {e}")
        account_display = f"Аккаунт {account_id}"
        group_name = f"Группа {group_id}"
        topic_name = f"Тема {topic_id}"
    finally:
        db.close_session(session)

    mailer_image = FSInputFile("img_static/mailer.png")
    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(
            media=mailer_image,
            caption=f"📎 <b>Настройка медиа для темы</b>\n\n"
                    f"📱 Аккаунт: <code>{account_display}</code>\n"
                    f"📝 Тема: <b>{group_name} | {topic_name}</b>\n\n"
                    "Отправьте медиа файл (фото, видео, GIF) для рассылки в эту тему:\n\n"
                    "💡 <i>Для удаления медиа отправьте 0</i>",
            parse_mode="HTML"
        ),
        reply_markup=get_message_edit_cancel_keyboard()
    )

@router.callback_query(F.data.startswith("topic_interval_"))
async def topic_interval_settings(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    topic_data = "_".join(parts[3:])

    await state.update_data(
        current_topic_data=topic_data,
        current_account_id=account_id
    )

    await state.set_state(AccountStates.waiting_for_topic_interval)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup

        account = session.query(Account).filter(Account.id == account_id).first()

        group_id, topic_id = topic_data.split('_')
        group_id = int(group_id)
        topic_id = int(topic_id)

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        account_display = account.phone_number if account else f"Аккаунт {account_id}"
        group_name = super_group.base_group_name if super_group else f"Группа {group_id}"
        topic_name = super_group.topic_name if super_group else f"Тема {topic_id}"

    except Exception as e:
        logger.error(f"Ошибка получения информации для отображения: {e}")
        account_display = f"Аккаунт {account_id}"
        group_name = f"Группа {group_id}"
        topic_name = f"Тема {topic_id}"
    finally:
        db.close_session(session)

    mailer_image = FSInputFile("img_static/mailer.png")
    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(
            media=mailer_image,
            caption=f"⏱ <b>Настройка интервала для темы</b>\n\n"
                    f"📱 Аккаунт: <code>{account_display}</code>\n"
                    f"📝 Тема: <b>{group_name} | {topic_name}</b>\n\n"
                    "Отправьте интервал в минутах между сообщениями:\n\n"
                    "💡 <i>Для сброса к автоматическому (15 мин) отправьте 0</i>",
            parse_mode="HTML"
        ),
        reply_markup=get_message_edit_cancel_keyboard()
    )

@router.callback_query(F.data.startswith("topic_escrow_"))
async def topic_escrow_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    parts = callback.data.split("_")
    account_id = int(parts[2])
    topic_data = "_".join(parts[3:])

    await state.update_data(
        current_topic_data=topic_data,
        current_account_id=account_id
    )

    await state.set_state(AccountStates.waiting_for_topic_escrow)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup

        account = session.query(Account).filter(Account.id == account_id).first()

        group_id, topic_id = topic_data.split('_')
        group_id = int(group_id)
        topic_id = int(topic_id)

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        account_display = account.phone_number if account else f"Аккаунт {account_id}"
        group_name = super_group.base_group_name if super_group else f"Группа {group_id}"
        topic_name = super_group.topic_name if super_group else f"Тема {topic_id}"

    except Exception as e:
        logger.error(f"Ошибка получения информации для отображения: {e}")
        account_display = f"Аккаунт {account_id}"
        group_name = f"Группа {group_id}"
        topic_name = f"Тема {topic_id}"
    finally:
        db.close_session(session)

    try:
        await callback.message.delete()
    except:
        pass

    mailer_image = FSInputFile("img_static/mailer.png")
    await callback.bot.send_photo(
        chat_id=callback.message.chat.id,
        photo=mailer_image,
        caption=f"💯 <b>Настройка гаранта для темы</b>\n\n"
                f"📱 Аккаунт: <code>{account_display}</code>\n"
                f"📝 Тема: <b>{group_name} | {topic_name}</b>\n\n"
                "Отправьте @username гаранта:\n\n"
                "💡 <i>Для удаления гаранта отправьте 0</i>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"individual_topic_settings_{account_id}_{topic_data}"
                )]
            ]
        ),
        parse_mode="HTML"
    )

    await callback.answer()

@router.message(AccountStates.waiting_for_topic_message)
async def process_topic_message(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('current_account_id')
    topic_data = data.get('current_topic_data')

    if not account_id or not topic_data:
        await message.answer("❌ Ошибка: данные не найдены")
        return

    group_id, topic_id = topic_data.split('_')
    group_id = int(group_id)
    topic_id = int(topic_id)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SuperGroup

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        if not super_group:
            super_group = SuperGroup(
                account_id=account_id,
                base_group_id=str(group_id),
                topic_id=str(topic_id),
                topic_name=f"Тема {topic_id}",
                base_group_name=f"Группа {group_id}"
            )
            session.add(super_group)

        if message.text.strip() == "0":
            super_group.custom_message = None
            session.commit()
        else:
            logger.info(f"👤 Пользовательский ввод для темы: '{message.text}'")

            from utils.markdown_converter import safe_convert_markdown_to_html
            markdown_converted = safe_convert_markdown_to_html(message.text.strip())

            if message.entities:
                from utils.emoji_processor import correct_entity_positions
                corrected_entities = correct_entity_positions(message)
                logger.info(f"📋 Сообщение содержит {len(corrected_entities)} сущностей")
                for i, entity in enumerate(corrected_entities):
                    if entity.type == "custom_emoji":
                        logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}")
                    else:
                        logger.info(f"  Сущность {i}: {entity.type} в {entity.offset}-{entity.offset + entity.length}")
                    if entity.type == "custom_emoji":
                        logger.info(f"  🎭 ID пользовательского эмодзи: {entity.custom_emoji_id}")

                from utils.text_formatter_wrapper import format_message_with_nodejs
                processed_message = format_message_with_nodejs(message)
                super_group.custom_message = processed_message
            else:
                super_group.custom_message = markdown_converted

            session.commit()

            logger.info(f"💾 Сохранено сообщение темы: '{super_group.custom_message}'")

        try:
            await message.bot.delete_message(message.chat.id, message.message_id - 1)
        except:
            pass
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

        text = build_topic_settings_text(account_id, topic_data, for_caption=True)
        keyboard = get_topic_settings_keyboard(account_id, topic_data)

        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            photo=mailer_image,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении сообщения темы: {e}")
        await message.answer("❌ Ошибка при сохранении сообщения")
    finally:
        db.close_session(session)

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])
    selected_topics = data.get('selected_super_groups_topics', [])

    await state.clear()

    if groups_with_topics or selected_topics:
        await state.update_data(
            groups_with_topics=groups_with_topics,
            selected_super_groups_topics=selected_topics
        )

@router.message(AccountStates.waiting_for_topic_media)
async def process_topic_media(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('current_account_id')
    topic_data = data.get('current_topic_data')

    if not account_id or not topic_data:
        await message.answer("❌ Ошибка: данные не найдены")
        return

    group_id, topic_id = topic_data.split('_')
    group_id = int(group_id)
    topic_id = int(topic_id)

    if message.text and message.text.strip() == "0":
        from database.database import db
        session = db.get_session()
        try:
            from database.models import SuperGroup

            super_group = session.query(SuperGroup).filter(
                SuperGroup.account_id == account_id,
                SuperGroup.base_group_id == str(group_id),
                SuperGroup.topic_id == str(topic_id)
            ).first()

            if super_group:
                super_group.custom_photo = None
                super_group.custom_gif = None
                super_group.custom_video = None
                session.commit()

            try:
                await message.bot.delete_message(message.chat.id, message.message_id - 1)
            except:
                pass
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

            text = build_topic_settings_text(account_id, topic_data, for_caption=True)
            keyboard = get_topic_settings_keyboard(account_id, topic_data)

            mailer_image = FSInputFile("img_static/mailer.png")
            await message.answer_photo(
                photo=mailer_image,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Ошибка при удалении медиа темы: {e}")
            await message.answer("❌ Ошибка при удалении медиа")
        finally:
            db.close_session(session)

        await state.clear()
        return

    if not message.photo and not message.video and not message.animation:
        await message.answer("❌ Отправьте фото, видео или GIF")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SuperGroup

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        if not super_group:
            super_group = SuperGroup(
                account_id=account_id,
                base_group_id=str(group_id),
                topic_id=str(topic_id),
                topic_name=f"Тема {topic_id}",
                base_group_name=f"Группа {group_id}"
            )
            session.add(super_group)

        super_group.custom_photo = None
        super_group.custom_gif = None
        super_group.custom_video = None

        if message.photo:
            file_info = await message.bot.get_file(message.photo[-1].file_id)
            file_data = await message.bot.download_file(file_info.file_path)
            super_group.custom_photo = file_data.read()
        elif message.video:
            file_info = await message.bot.get_file(message.video.file_id)
            file_data = await message.bot.download_file(file_info.file_path)
            super_group.custom_video = file_data.read()
        elif message.animation:
            file_info = await message.bot.get_file(message.animation.file_id)
            file_data = await message.bot.download_file(file_info.file_path)
            super_group.custom_gif = file_data.read()

        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id - 1)
        except:
            pass
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

        text = build_topic_settings_text(account_id, topic_data, for_caption=True)
        keyboard = get_topic_settings_keyboard(account_id, topic_data)

        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            photo=mailer_image,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении медиа темы: {e}")
        await message.answer("❌ Ошибка при сохранении медиа")
    finally:
        db.close_session(session)
        await state.clear()

@router.message(AccountStates.waiting_for_topic_interval)
async def process_topic_interval(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('current_account_id')
    topic_data = data.get('current_topic_data')

    if not account_id or not topic_data:
        await message.answer("❌ Ошибка: данные не найдены")
        return

    group_id, topic_id = topic_data.split('_')
    group_id = int(group_id)
    topic_id = int(topic_id)

    if message.text.strip() == "0":
        interval = None
    else:
        try:
            interval = int(message.text)
            if interval < 1:
                await message.answer("❌ Интервал должен быть больше 0")
                return
        except ValueError:
            await message.answer("❌ Введите корректное число")
            return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SuperGroup

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        if not super_group:
            super_group = SuperGroup(
                account_id=account_id,
                base_group_id=str(group_id),
                topic_id=str(topic_id),
                topic_name=f"Тема {topic_id}",
                base_group_name=f"Группа {group_id}"
            )
            session.add(super_group)

        super_group.custom_interval = interval
        session.commit()

        try:
            await message.bot.delete_message(message.chat.id, message.message_id - 1)
        except:
            pass
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

        text = build_topic_settings_text(account_id, topic_data, for_caption=True)
        keyboard = get_topic_settings_keyboard(account_id, topic_data)

        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            photo=mailer_image,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении интервала темы: {e}")
        await message.answer("❌ Ошибка при сохранении интервала")
    finally:
        db.close_session(session)

    await state.clear()

@router.message(AccountStates.waiting_for_topic_escrow)
async def process_topic_escrow(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('current_account_id')
    topic_data = data.get('current_topic_data')

    if not account_id or not topic_data:
        await message.answer("❌ Ошибка: данные не найдены")
        await state.clear()
        return

    group_id, topic_id = topic_data.split('_')
    group_id = int(group_id)
    topic_id = int(topic_id)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SuperGroup

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        if not super_group:
            await message.answer("❌ Настройки темы не найдены")
            await state.clear()
            return

        if message.text.strip() == "0":
            super_group.escrow_username = None

            if super_group.custom_message:
                lines = super_group.custom_message.split('\n')
                filtered_lines = []
                for line in lines:
                    if not (line.strip().startswith('<b>escrow/гарант :') or
                            line.strip().startswith('escrow/гарант :')):
                        filtered_lines.append(line)

                while filtered_lines and not filtered_lines[-1].strip():
                    filtered_lines.pop()

                super_group.custom_message = '\n'.join(filtered_lines) if filtered_lines else None

            session.commit()

            try:
                await message.bot.delete_message(message.chat.id, message.message_id - 1)
            except:
                pass
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

            text = build_topic_settings_text(account_id, topic_data, for_caption=True)
            keyboard = get_topic_settings_keyboard(account_id, topic_data)

            mailer_image = FSInputFile("img_static/mailer.png")
            await message.answer_photo(
                photo=mailer_image,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        else:
            escrow_username = message.text.strip()

            if not escrow_username.startswith('@'):
                escrow_username = '@' + escrow_username

            from database.models import Account
            account = session.query(Account).filter(Account.id == account_id).first()

            has_topic_message = super_group.custom_message
            has_common_message = account and account.default_message

            if not has_topic_message and not has_common_message:
                await message.answer("❌ Сначала настройте сообщение для темы или общее сообщение аккаунта")
                await state.clear()
                return

            if super_group.custom_message:
                lines = super_group.custom_message.split('\n')
                filtered_lines = []
                for line in lines:
                    if not (line.strip().startswith('<b>escrow/гарант :') or
                            line.strip().startswith('escrow/гарант :')):
                        filtered_lines.append(line)

                while filtered_lines and not filtered_lines[-1].strip():
                    filtered_lines.pop()

                filtered_lines.append('')
                filtered_lines.append(f'<b>escrow/гарант : {escrow_username}</b>')

                super_group.custom_message = '\n'.join(filtered_lines)

            super_group.escrow_username = escrow_username
            session.commit()

            logger.info(f"💾 Добавлен гарант для темы: '{escrow_username}'")

            try:
                await message.bot.delete_message(message.chat.id, message.message_id - 1)
            except:
                pass
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

            text = build_topic_settings_text(account_id, topic_data, for_caption=True)
            keyboard = get_topic_settings_keyboard(account_id, topic_data)

            mailer_image = FSInputFile("img_static/mailer.png")
            await message.answer_photo(
                photo=mailer_image,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Ошибка при сохранении гаранта темы: {e}")
        await message.answer("❌ Ошибка при сохранении гаранта")
        await state.clear()
    finally:
        db.close_session(session)

    await state.clear()

@router.callback_query(F.data.startswith("back_to_individual_super_groups_topics_"))
async def individual_super_groups_topics_back(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[-1])

    await state.clear()

    await show_individual_topics_menu(callback, account_id)

async def show_super_groups_list(callback: CallbackQuery, account_id: int):
    from database.database import db
    session = db.get_session()
    try:
        from database.models import SuperGroup
        super_groups = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id
        ).all()

        if not super_groups:
            await safe_edit_message(
                callback.message,
                f"❌ <b>Нет созданных супер групп</b>\n\n"
                f"Аккаунт: <code>{account_id}</code>",
                get_account_settings_keyboard(account_id)
            )
            return

        groups_dict = {}
        for sg in super_groups:
            if sg.base_group_id not in groups_dict:
                groups_dict[sg.base_group_id] = {
                    'name': sg.base_group_name,
                    'topics': []
                }
            groups_dict[sg.base_group_id]['topics'].append({
                'id': sg.id,
                'name': sg.topic_name,
                'enabled': sg.is_enabled
            })

        text = f"✨ <b>Супер группы аккаунта</b> <code>{account_id}</code>\n\n"

        for group_id, group_info in groups_dict.items():
            text += f"📁 <b>{group_info['name']}</b>\n"
            for topic in group_info['topics']:
                status = "✅" if topic['enabled'] else "❌"
                text += f"  {status} {topic['name']}\n"
            text += "\n"

        await safe_edit_message(
            callback.message,
            text,
            get_super_groups_list_keyboard(super_groups, account_id, 0)
        )

    finally:
        db.close_session(session)


@router.callback_query(F.data.startswith("list_super_groups_"))
async def list_super_groups(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[3])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        super_groups = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id
        ).order_by(SuperGroup.created_at.desc()).all()

        if not super_groups:
            await safe_edit_message(
                callback.message,
                f"✨ <b>Супер группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
                "📭 <i>У вас пока нет созданных супер групп</i>\n\n"
                "💡 <i>Создайте первую супер группу для организации рассылки по темам</i>",
                get_super_groups_main_keyboard(account_id)
            )
        else:
            await safe_edit_message(
                callback.message,
                f"✨ <b>Супер группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
                f"📊 <b>Создано супер групп:</b> {len(super_groups)}\n\n"
                "Выберите супер группу для настройки:",
                get_super_groups_list_keyboard(super_groups, account_id, 0)
            )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("super_groups_page_"))
async def super_groups_page(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    page = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        super_groups = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id
        ).order_by(SuperGroup.created_at.desc()).all()

        await safe_edit_message(
            callback.message,
            f"✨ <b>Супер группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
            f"📊 <b>Создано супер групп:</b> {len(super_groups)}\n\n"
            "Выберите супер группу для настройки:",
            get_super_groups_list_keyboard(super_groups, account_id, page)
        )

    finally:
        db.close_session(session)

    await callback.answer(f"📄 Страница {page + 1}")

@router.callback_query(F.data.startswith("super_group_settings_"))
async def super_group_settings(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    parts = callback.data.split("_")
    account_id = int(parts[3])
    super_group_id = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        status = "✅ Включена" if super_group.is_enabled else "❌ Отключена"

        await safe_edit_message(
            callback.message,
            f"⚙️ <b>Настройки супер группы</b>\n\n"
            f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
            f"👥 Базовая группа: <b>{super_group.base_group_name}</b>\n"
            f"📝 Тема: <b>{super_group.topic_name}</b>\n"
            f"📊 Статус: {status}\n\n"
            "Выберите настройку для изменения:",
            get_super_group_settings_keyboard(account_id, super_group_id)
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("toggle_super_group_"))
async def toggle_super_group(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    super_group_id = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        super_group.is_enabled = not super_group.is_enabled
        session.commit()

        status = "✅ включена" if super_group.is_enabled else "❌ отключена"
        await callback.answer(f"Супер группа {status}")

        status_text = "✅ Включена" if super_group.is_enabled else "❌ Отключена"

        await safe_edit_message(
            callback.message,
            f"⚙️ <b>Настройки супер группы</b>\n\n"
            f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
            f"👥 Базовая группа: <b>{super_group.base_group_name}</b>\n"
            f"📝 Тема: <b>{super_group.topic_name}</b>\n"
            f"📊 Статус: {status_text}\n\n"
            "Выберите настройку для изменения:",
            get_super_group_settings_keyboard(account_id, super_group_id)
        )

    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("delete_super_group_"))
async def delete_super_group(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    super_group_id = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        session.delete(super_group)
        session.commit()

        await callback.answer("✅ Супер группа удалена")

        super_groups = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id
        ).order_by(SuperGroup.created_at.desc()).all()

        if not super_groups:
            await safe_edit_message(
                callback.message,
                f"✨ <b>Супер группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
                "📭 <i>У вас пока нет созданных супер групп</i>\n\n"
                "💡 <i>Создайте первую супер группу для организации рассылки по темам</i>",
                get_super_groups_main_keyboard(account_id)
            )
        else:
            await safe_edit_message(
                callback.message,
                f"✨ <b>Супер группы аккаунта</b> <code>{account.phone_number}</code>\n\n"
                f"📊 <b>Создано супер групп:</b> {len(super_groups)}\n\n"
                "Выберите супер группу для настройки:",
                get_super_groups_list_keyboard(super_groups, account_id, 0)
            )

    finally:
        db.close_session(session)


@router.callback_query(F.data.startswith("group_topics_"))
async def show_group_topics(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = int(parts[3])
    page = int(parts[4])

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    selected_group = None
    for group in groups_with_topics:
        if group['id'] == group_id:
            selected_group = group
            break

    if not selected_group:
        await callback.answer("❌ Группа не найдена")
        return

    topics = selected_group.get('topics', [])

    await safe_edit_message(
        callback.message,
        f"📝 <b>Темы группы</b>\n\n"
        f"👥 Группа: <b>{selected_group['title']}</b>\n"
        f"📊 <b>Количество тем:</b> {len(topics)}\n\n"
        "Выберите тему для настройки:",
        get_topics_list_keyboard(selected_group, account_id, 0)
    )

    await callback.answer()

@router.callback_query(F.data.startswith("groups_topics_page_"))
async def groups_topics_page(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    page = int(parts[4])

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account
        account = session.query(Account).filter(Account.id == account_id).first()

        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        await safe_edit_message(
            callback.message,
            f"✨ <b>Создание супер группы</b>\n\n"
            f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
            f"📊 <b>Найдено групп с темами:</b> {len(groups_with_topics)}\n\n"
            "Выберите группу для настройки тем:",
            get_groups_with_topics_keyboard(groups_with_topics, account_id, page)
        )

    finally:
        db.close_session(session)

    await callback.answer(f"📄 Страница {page + 1}")

@router.callback_query(F.data.startswith("topics_page_"))
async def topics_page(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = int(parts[3])
    page = int(parts[4])

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    selected_group = None
    for group in groups_with_topics:
        if group['id'] == group_id:
            selected_group = group
            break

    if not selected_group:
        await callback.answer("❌ Группа не найдена")
        return

    await safe_edit_message(
        callback.message,
        f"📝 <b>Темы группы</b>\n\n"
        f"👥 Группа: <b>{selected_group['title']}</b>\n"
        f"📊 <b>Количество тем:</b> {len(selected_group.get('topics', []))}\n\n"
        "Выберите тему для настройки:",
        get_topics_list_keyboard(selected_group, account_id, page)
    )

    await callback.answer(f"📄 Страница {page + 1}")

@router.callback_query(F.data.startswith("select_topic_"))
async def select_topic_for_super_group(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[2])
    group_id = int(parts[3])
    topic_id = int(parts[4])
    page = int(parts[5])

    data = await state.get_data()
    groups_with_topics = data.get('groups_with_topics', [])

    selected_group = None
    selected_topic = None

    for group in groups_with_topics:
        if group['id'] == group_id:
            selected_group = group
            for topic in group.get('topics', []):
                if topic['id'] == topic_id:
                    selected_topic = topic
                    break
            break

    if not selected_group or not selected_topic:
        await callback.answer("❌ Тема не найдена")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup

        account = session.query(Account).filter(Account.id == account_id).first()
        if not account:
            await callback.answer("❌ Аккаунт не найден")
            return

        existing_super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        if existing_super_group:
            await safe_edit_message(
                callback.message,
                f"⚙️ <b>Настройки супер группы</b>\n\n"
                f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
                f"👥 Группа: <b>{selected_group['title']}</b>\n"
                f"📝 Тема: <b>{selected_topic['title']}</b>\n"
                f"📊 Статус: {'✅ Включена' if existing_super_group.is_enabled else '❌ Отключена'}\n\n"
                "Выберите настройку для изменения:",
                get_super_group_settings_keyboard(account_id, existing_super_group.id)
            )
        else:
            await safe_edit_message(
                callback.message,
                f"ℹ️ <b>Супер группа не найдена</b>\n\n"
                f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
                f"👥 Группа: <b>{selected_group['title']}</b>\n"
                f"📝 Тема: <b>{selected_topic['title']}</b>\n\n"
                "Для этой темы еще не настроена супер группа.",
                get_account_settings_keyboard(account_id)
            )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("super_group_message_"))
async def super_group_message_settings(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    super_group_id = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        await state.update_data(
            account_id=account_id,
            super_group_id=super_group_id,
            super_group_name=f"{super_group.base_group_name} | {super_group.topic_name}"
        )

        current_raw = super_group.custom_message or account.default_message or "Сообщение не установлено"

        from utils.emoji_processor import html_with_tg_emoji_to_plain_text
        current_message = html_with_tg_emoji_to_plain_text(current_raw)
        safe_current_message = escape_html_for_pre(current_message)
        truncated_current_message = truncate_message_for_display(safe_current_message)

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=f"📝 <b>Настройка сообщения супер группы</b>\n\n"
                    f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
                    f"👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n\n"
                    f"📄 <b>Текущее сообщение:</b>\n<pre>{truncated_current_message}</pre>\n\n"
                    "Отправьте новое сообщение для этой супер группы:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"super_group_settings_{account_id}_{super_group_id}")]
            ]),
            parse_mode="HTML"
        )

        await state.set_state(AccountStates.waiting_for_super_group_message)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("super_group_media_"))
async def super_group_media_settings(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    super_group_id = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        await state.update_data(
            account_id=account_id,
            super_group_id=super_group_id,
            super_group_name=f"{super_group.base_group_name} | {super_group.topic_name}"
        )

        has_photo = super_group.custom_photo is not None
        has_gif = super_group.custom_gif is not None
        has_video = super_group.custom_video is not None

        media_status = []
        if has_photo:
            media_status.append("🖼️ Фото")
        if has_gif:
            media_status.append("🎬 GIF")
        if has_video:
            media_status.append("📹 Видео")

        media_text = " | ".join(media_status) if media_status else "❌ Медиа не установлено"

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=f"🖼️ <b>Настройка медиа супер группы</b>\n\n"
                    f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
                    f"👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n\n"
                    f"📄 <b>Текущее медиа:</b> {media_text}\n\n"
                    "Выберите тип медиа для добавления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🖼️ Фото", callback_data=f"super_group_add_photo_{account_id}_{super_group_id}")],
                [InlineKeyboardButton(text="🎬 GIF", callback_data=f"super_group_add_gif_{account_id}_{super_group_id}")],
                [InlineKeyboardButton(text="📹 Видео", callback_data=f"super_group_add_video_{account_id}_{super_group_id}")],
                [InlineKeyboardButton(text="🗑️ Удалить медиа", callback_data=f"super_group_delete_media_{account_id}_{super_group_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"super_group_settings_{account_id}_{super_group_id}")]
            ]),
            parse_mode="HTML"
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("super_group_interval_"))
async def super_group_interval_settings(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[3])
    super_group_id = int(parts[4])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        await state.update_data(
            account_id=account_id,
            super_group_id=super_group_id,
            super_group_name=f"{super_group.base_group_name} | {super_group.topic_name}"
        )

        current_interval = super_group.custom_interval or account.message_interval

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=f"⏱️ <b>Настройка интервала супер группы</b>\n\n"
                    f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
                    f"👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n\n"
                    f"⏰ <b>Текущий интервал:</b> {current_interval} секунд\n\n"
                    "Отправьте новый интервал в секундах (от 30 до 3600):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"super_group_settings_{account_id}_{super_group_id}")]
            ]),
            parse_mode="HTML"
        )

        await state.set_state(AccountStates.waiting_for_super_group_interval)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("super_group_add_photo_"))
async def super_group_add_photo_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[4])
    super_group_id = int(parts[5])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        await state.update_data(
            account_id=account_id,
            super_group_id=super_group_id,
            super_group_name=f"{super_group.base_group_name} | {super_group.topic_name}",
            media_type="photo"
        )

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=f"🖼️ <b>Добавление фото для супер группы</b>\n\n"
                    f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
                    f"👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n\n"
                    "Отправьте фото для этой супер группы:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"super_group_media_{account_id}_{super_group_id}")]
            ]),
            parse_mode="HTML"
        )

        await state.set_state(AccountStates.waiting_for_super_group_media)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("super_group_add_gif_"))
async def super_group_add_gif_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[4])
    super_group_id = int(parts[5])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        await state.update_data(
            account_id=account_id,
            super_group_id=super_group_id,
            super_group_name=f"{super_group.base_group_name} | {super_group.topic_name}",
            media_type="gif"
        )

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=f"🎬 <b>Добавление GIF для супер группы</b>\n\n"
                    f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
                    f"👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n\n"
                    "Отправьте GIF для этой супер группы:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"super_group_media_{account_id}_{super_group_id}")]
            ]),
            parse_mode="HTML"
        )

        await state.set_state(AccountStates.waiting_for_super_group_media)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("super_group_add_video_"))
async def super_group_add_video_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    account_id = int(parts[4])
    super_group_id = int(parts[5])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        await state.update_data(
            account_id=account_id,
            super_group_id=super_group_id,
            super_group_name=f"{super_group.base_group_name} | {super_group.topic_name}",
            media_type="video"
        )

        try:
            await callback.message.delete()
        except:
            pass

        mailer_image = FSInputFile("img_static/mailer.png")
        await callback.bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=mailer_image,
            caption=f"📹 <b>Добавление видео для супер группы</b>\n\n"
                    f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
                    f"👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n\n"
                    "Отправьте видео для этой супер группы:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"super_group_media_{account_id}_{super_group_id}")]
            ]),
            parse_mode="HTML"
        )

        await state.set_state(AccountStates.waiting_for_super_group_media)

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("super_group_delete_media_"))
async def super_group_delete_media(callback: CallbackQuery):
    parts = callback.data.split("_")
    account_id = int(parts[4])
    super_group_id = int(parts[5])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await callback.answer("❌ Супер группа не найдена")
            return

        super_group.custom_photo = None
        super_group.custom_gif = None
        super_group.custom_video = None
        session.commit()

        await callback.answer("✅ Медиа удалено")

        await safe_edit_message(
            callback.message,
            f"🖼️ <b>Настройка медиа супер группы</b>\n\n"
            f"📱 Аккаунт: <code>{account.phone_number}</code>\n"
            f"👥 Супер группа: <b>{super_group.base_group_name} | {super_group.topic_name}</b>\n\n"
            f"📄 <b>Текущее медиа:</b> ❌ Медиа не установлено\n\n"
            "Выберите тип медиа для добавления:",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🖼️ Фото", callback_data=f"super_group_add_photo_{account_id}_{super_group_id}")],
                [InlineKeyboardButton(text="🎬 GIF", callback_data=f"super_group_add_gif_{account_id}_{super_group_id}")],
                [InlineKeyboardButton(text="📹 Видео", callback_data=f"super_group_add_video_{account_id}_{super_group_id}")],
                [InlineKeyboardButton(text="🗑️ Удалить медиа", callback_data=f"super_group_delete_media_{account_id}_{super_group_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"super_group_settings_{account_id}_{super_group_id}")]
            ])
        )

    finally:
        db.close_session(session)

@router.message(AccountStates.waiting_for_super_group_message)
async def process_super_group_message(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')
    super_group_id = data.get('super_group_id')

    if not account_id or not super_group_id:
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await message.answer("❌ Аккаунт или супер группа не найдены", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        if message.text.strip() == "0":
            super_group.custom_message = None
            session.commit()
            await message.answer("✅ Сообщение сброшено к общему")
        else:
            super_group.custom_message = message.text
            session.commit()
            await message.answer("✅ Сообщение для супер группы установлено")

        text = build_super_group_settings_text(account_id, super_group_id)
        mailer_image = FSInputFile("img_static/mailer.png")
        await message.answer_photo(
            mailer_image,
            caption=text,
            reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения супер группы: {e}")
        try:
            mailer_image = FSInputFile("img_static/mailer.png")
            await message.answer_photo(
                mailer_image,
                caption="❌ Ошибка при обработке сообщения",
                reply_markup=get_main_menu_keyboard()
            )
        except:
            await message.answer("❌ Ошибка при обработке сообщения", reply_markup=get_main_menu_keyboard())
    finally:
        db.close_session(session)

    await state.clear()

@router.message(AccountStates.waiting_for_super_group_media)
async def process_super_group_media(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')
    super_group_id = data.get('super_group_id')

    if not account_id or not super_group_id:
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            await message.answer("❌ Аккаунт или супер группа не найдены", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        if message.text and message.text.strip() == "0":
            super_group.media_type = None
            super_group.media_data = None
            session.commit()
            await message.answer("✅ Медиа для супер группы сброшено")
        elif message.photo:
            file_id = message.photo[-1].file_id
            file = await message.bot.get_file(file_id)
            media_data = await message.bot.download_file(file.file_path)
            super_group.media_type = "photo"
            super_group.media_data = media_data.read()
            session.commit()
            await message.answer("✅ Фото для супер группы установлено")
        elif message.video:
            file_id = message.video.file_id
            file = await message.bot.get_file(file_id)
            media_data = await message.bot.download_file(file.file_path)
            super_group.media_type = "video"
            super_group.media_data = media_data.read()
            session.commit()
            await message.answer("✅ Видео для супер группы установлено")
        elif message.animation:
            file_id = message.animation.file_id
            file = await message.bot.get_file(file_id)
            media_data = await message.bot.download_file(file.file_path)
            super_group.media_type = "animation"
            super_group.media_data = media_data.read()
            session.commit()
            await message.answer("✅ GIF для супер группы установлено")
        else:
            await message.answer("❌ Отправьте фото, видео, GIF или '0' для сброса", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        mailer_image = FSInputFile("img_static/mailer.png")
        text = build_super_group_settings_text(account_id, super_group_id)
        await message.answer_photo(
            mailer_image,
            caption=text,
            reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке медиа супер группы: {e}")
        await message.answer("❌ Ошибка при обработке медиа", reply_markup=get_main_menu_keyboard())
    finally:
        db.close_session(session)

    await state.clear()

@router.message(AccountStates.waiting_for_super_group_interval)
async def process_super_group_interval(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data.get('account_id')
    super_group_id = data.get('super_group_id')

    if not account_id or not super_group_id:
        await message.answer("❌ Ошибка с данными", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    if message.text.strip() == "0":
        from database.database import db
        session = db.get_session()
        try:
            from database.models import SuperGroup
            super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

            if super_group:
                super_group.custom_interval = None
                session.commit()
                await message.answer("✅ Интервал сброшен к общему")

                mailer_image = FSInputFile("img_static/mailer.png")
                text = build_super_group_settings_text(account_id, super_group_id)
                await message.answer_photo(
                    mailer_image,
                    caption=text,
                    reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
                    parse_mode="HTML"
                )

        except Exception as e:
            logger.error(f"Ошибка при сбросе интервала супер группы: {e}")
            await message.answer("❌ Ошибка при сбросе интервала", reply_markup=get_main_menu_keyboard())
        finally:
            db.close_session(session)

        await state.clear()
        return

    try:
        interval = int(message.text)
        if interval < 1 or interval > 1440:
            await message.answer("❌ Интервал должен быть от 1 до 1440 минут или '0' для сброса", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        from database.database import db
        session = db.get_session()
        try:
            from database.models import SuperGroup
            super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

            if not super_group:
                await message.answer("❌ Супер группа не найдена")
                await state.clear()
                return

            super_group.custom_interval = interval
            session.commit()

            mailer_image = FSInputFile("img_static/mailer.png")
            text = build_super_group_settings_text(account_id, super_group_id)
            await message.answer_photo(
                mailer_image,
                caption=text,
                reply_markup=get_super_group_settings_keyboard(account_id, super_group_id),
                parse_mode="HTML"
            )
            await state.clear()

        finally:
            db.close_session(session)

    except ValueError:
        await message.answer("❌ Введите корректное число или '0' для сброса", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return
    except Exception as e:
        logger.error(f"Ошибка при обработке интервала супер группы: {e}")
        await message.answer("❌ Ошибка при обработке интервала", reply_markup=get_main_menu_keyboard())
        await state.clear()
        return

    await state.clear()

def build_super_group_settings_text(account_id: int, super_group_id: int) -> str:
    from database.database import db
    session = db.get_session()
    try:
        from database.models import Account, SuperGroup
        account = session.query(Account).filter(Account.id == account_id).first()
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()

        if not account or not super_group:
            return "❌ Супер группа не найдена"

        common_message = account.common_message or "Не установлено"
        common_interval = account.common_interval or "Не установлен"
        common_media = "Не установлено"
        if account.media_type and account.media_data:
            media_types = {"photo": "Фото", "video": "Видео", "animation": "GIF"}
            common_media = media_types.get(account.media_type, "Неизвестно")

        super_message = super_group.custom_message or common_message
        super_interval = super_group.custom_interval or common_interval
        super_media = "Не установлено"
        if super_group.media_type and super_group.media_data:
            media_types = {"photo": "Фото", "video": "Видео", "animation": "GIF"}
            super_media = media_types.get(super_group.media_type, "Неизвестно")
        elif account.media_type and account.media_data:
            media_types = {"photo": "Фото", "video": "Видео", "animation": "GIF"}
            super_media = media_types.get(account.media_type, "Неизвестно")

        status_emoji = "🟢" if super_group.is_active else "🔴"
        status_text = "Активна" if super_group.is_active else "Неактивна"

        text = f"⚙️ <b>Настройки супер группы</b>\n\n" \
               f"📝 <b>Название:</b> {super_group.base_group_name} | Тема: {super_group.topic_name}\n" \
               f"🆔 <b>ID группы:</b> <code>{super_group.base_group_id}</code>\n" \
               f"🆔 <b>ID темы:</b> <code>{super_group.topic_id or 'Нет'}</code>\n" \
               f"📊 <b>Статус:</b> {status_emoji} {status_text}\n\n" \
               f"💬 <b>Сообщение:</b>\n" \
               f"<code>{truncate_message_for_display(super_message)}</code>\n\n" \
               f"🖼️ <b>Медиа:</b> {super_media}\n" \
               f"⏱️ <b>Интервал:</b> {super_interval} мин.\n\n" \
               f"📋 <b>Общие настройки аккаунта:</b>\n" \
               f"💬 Сообщение: <code>{truncate_message_for_display(common_message, 200)}</code>\n" \
               f"🖼️ Медиа: {common_media}\n" \
               f"⏱️ Интервал: {common_interval} мин."

        return text

    except Exception as e:
        logger.error(f"Ошибка при построении текста настроек супер группы: {e}")
        return "❌ Ошибка при загрузке настроек"
    finally:
        db.close_session(session)

@router.callback_query(F.data.startswith("diagnose_code_issue:"))
async def diagnose_code_issue(callback: CallbackQuery):
    try:
        await callback.answer()

        await safe_edit_message(
            callback.message,
            "🔍 <b>Диагностика проблем с кодами</b>\n\n"
            "📋 <b>Возможные причины:</b>\n\n"
            "1️⃣ <b>Код отправлен в Telegram</b>\n"
            "   • Проверьте уведомления Telegram на телефоне\n"
            "   • Код может прийти с задержкой\n\n"
            "2️⃣ <b>Превышен лимит запросов</b>\n"
            "   • Telegram ограничивает частые запросы\n"
            "   • Подождите 5-10 минут\n\n"
            "3️⃣ <b>Проблемы с номером</b>\n"
            "   • Номер заблокирован Telegram\n"
            "   • Неверный формат номера\n\n"
            "4️⃣ <b>Сетевые проблемы</b>\n"
            "   • Проблемы с интернетом\n"
            "   • Блокировка оператора\n\n"
            "💡 <b>Рекомендации:</b>\n"
            "• Используйте VPN при необходимости\n"
            "• Проверьте настройки уведомлений\n"
            "• Попробуйте другой номер телефона",
            get_account_retry_keyboard()
        )

    except Exception as e:
        logger.error(f"Ошибка в diagnose_code_issue: {e}")
        await callback.answer("❌ Ошибка при диагностике")

@router.callback_query(F.data.startswith("diagnose_proxy_issue:"))
async def diagnose_proxy_issue(callback: CallbackQuery):
    try:
        await callback.answer()

        from database.database import get_working_proxies
        working_proxies = get_working_proxies()

        if not working_proxies:
            await safe_edit_message(
                callback.message,
                "❌ <b>Проблема с прокси</b>\n\n"
                "🔍 <b>Диагностика:</b>\n"
                "• Нет активных рабочих прокси в базе данных\n"
                "• Все прокси помечены как нерабочие\n\n"
                "💡 <b>Решение:</b>\n"
                "• Добавьте новые прокси в админ панели\n"
                "• Проверьте статус существующих прокси\n"
                "• Убедитесь, что прокси работают",
                get_account_retry_keyboard()
            )
            return

        proxy = working_proxies[0]

        await safe_edit_message(
            callback.message,
            f"🔍 <b>Диагностика прокси</b>\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"• Всего рабочих прокси: {len(working_proxies)}\n"
            f"• Проверяем прокси: {proxy.host}:{proxy.port}\n"
            f"• Тип: {proxy.proxy_type}\n\n"
            f"🔧 <b>Проверка конфигурации...</b>\n\n"
            f"⏳ Тестируем подключение...",
            get_account_retry_keyboard()
        )

        from utils.proxy_validator import get_telethon_proxy_config, validate_proxy_for_telethon

        proxy_data = {
            'host': proxy.host,
            'port': proxy.port,
            'username': proxy.username,
            'password': proxy.password,
            'proxy_type': proxy.proxy_type
        }

        proxy_config = get_telethon_proxy_config(proxy_data)

        if proxy_config is None:
            await safe_edit_message(
                callback.message,
                f"❌ <b>Ошибка конфигурации прокси</b>\n\n"
                f"🔍 <b>Проблема:</b>\n"
                f"• Не удалось создать конфигурацию для Telethon\n"
                f"• Прокси: {proxy.host}:{proxy.port}\n"
                f"• Тип: {proxy.proxy_type}\n\n"
                f"💡 <b>Возможные причины:</b>\n"
                f"• Отсутствует библиотека PySocks\n"
                f"• Неверные данные прокси\n"
                f"• Неподдерживаемый тип прокси",
                get_account_retry_keyboard()
            )
            return

        is_valid, error = await validate_proxy_for_telethon(proxy_data)

        if not is_valid:
            await safe_edit_message(
                callback.message,
                f"❌ <b>Прокси не работает</b>\n\n"
                f"🔍 <b>Проблема:</b>\n"
                f"• Прокси недоступен или не работает\n"
                f"• Прокси: {proxy.host}:{proxy.port}\n"
                f"• Ошибка: {error}\n\n"
                f"💡 <b>Решение:</b>\n"
                f"• Проверьте настройки прокси\n"
                f"• Убедитесь, что прокси сервер работает\n"
                f"• Проверьте логин и пароль",
                get_account_retry_keyboard()
            )
            return

        await safe_edit_message(
            callback.message,
            f"✅ <b>Прокси работает корректно</b>\n\n"
            f"🔍 <b>Результат проверки:</b>\n"
            f"• Прокси: {proxy.host}:{proxy.port}\n"
            f"• Тип: {proxy.proxy_type}\n"
            f"• Статус: ✅ Работает\n"
            f"• Конфигурация: ✅ Создана\n\n"
            f"💡 <b>Если коды не приходят:</b>\n"
            f"• Проблема не в прокси\n"
            f"• Проверьте настройки Telegram\n"
            f"• Убедитесь, что номер не заблокирован",
            get_account_retry_keyboard()
        )

    except Exception as e:
        logger.error(f"Ошибка в diagnose_proxy_issue: {e}")
        await callback.answer("❌ Ошибка при диагностике прокси")
