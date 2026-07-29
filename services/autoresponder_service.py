import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User, Chat, Channel
from telethon.errors import FloodWaitError, UserIsBlockedError, PeerIdInvalidError

from database.database import db
from database.models import Account, AutoresponderDialog
from utils.proxy_validator import get_telethon_proxy_config
from utils.cyrillic_substitution import apply_cyrillic_substitution
from utils.xtelethon import CustomParseMode, convert_html_to_custom_format

logger = logging.getLogger(__name__)

class AutoresponderService:
    def __init__(self):
        self.active_clients: Dict[int, TelegramClient] = {}
        self.running = False

    async def start_autoresponder_for_account(self, account: Account):
        try:
            logger.info(f"Пытаюсь запустить автоответчик для аккаунта {account.phone_number}, включен: {account.autoresponder_enabled}")
            if not account.autoresponder_enabled:
                logger.info(f"Автоответчик отключен для аккаунта {account.phone_number}")
                return

            proxy_config = None
            if account.proxy_id:
                from database.database import get_proxy_by_id
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

            import configparser
            config = configparser.ConfigParser()
            config.read('config.ini')
            api_id = int(config.get('TELEGRAM', 'api_id'))
            api_hash = config.get('TELEGRAM', 'api_hash')

            client = TelegramClient(
                StringSession(account.session_string),
                api_id,
                api_hash,
                proxy=proxy_config,
                system_version="4.16.30-vxCUSTOM",
                device_model="Desktop",
                app_version="4.16.30"
            )

            @client.on(events.NewMessage(incoming=True))
            async def handle_new_message(event):
                await self.process_incoming_message(event, account)

            @client.on(events.NewMessage(outgoing=True))
            async def handle_outgoing_message(event):
                await self.process_outgoing_message(event, account)

            await client.connect()
            if not await client.is_user_authorized():
                logger.error(f"Аккаунт {account.phone_number} не авторизован")
                return

            self.active_clients[account.id] = client

            logger.info(f"Автоответчик запущен для аккаунта {account.phone_number}. Активных клиентов: {len(self.active_clients)}")

        except Exception as e:
            logger.error(f"Ошибка при запуске автоответчика для аккаунта {account.phone_number}: {e}")

    async def process_outgoing_message(self, event, account: Account):
        try:
            await self.update_account_last_seen(account.id)
            logger.debug(f"Обновлено время последнего действия для аккаунта {account.phone_number} после исходящего сообщения")

        except Exception as e:
            logger.error(f"Ошибка при обработке исходящего сообщения для аккаунта {account.phone_number}: {e}")

    async def process_incoming_message(self, event, account: Account):
        try:
            if event.is_group or event.is_channel:
                return

            sender = await event.get_sender()
            if not isinstance(sender, User):
                return

            client = self.active_clients.get(account.id)
            if client:
                me = await client.get_me()
                if me and sender.id == me.id:
                    return

            if sender.bot:
                return

            sender_id = str(sender.id)
            sender_username = sender.username

            logger.info(f"Обработка сообщения от {sender_id} ({sender_username}) к аккаунту {account.phone_number}")

            session = db.get_session()
            try:
                dialog = session.query(AutoresponderDialog).filter(
                    AutoresponderDialog.account_id == account.id,
                    AutoresponderDialog.dialog_id == sender_id
                ).first()

                if not dialog:
                    dialog = AutoresponderDialog(
                        account_id=account.id,
                        dialog_id=sender_id,
                        dialog_username=sender_username,
                        first_message_sent=False,
                        away_message_sent=False,
                        last_user_message=datetime.now()
                    )
                    session.add(dialog)
                    session.commit()

                    if account.autoresponder_first_message:
                        await self.send_autoresponse(
                            event,
                            account,
                            account.autoresponder_first_message,
                            "first"
                        )

                        dialog.first_message_sent = True
                        dialog.last_autoresponder_sent = datetime.now()
                        session.commit()

                        logger.info(f"Отправлено первое сообщение автоответчика от {sender_id} к аккаунту {account.phone_number}")
                else:
                    dialog.last_user_message = datetime.now()
                    dialog.dialog_username = sender_username

                    if account.autoresponder_away_message:
                        if account.last_seen_time is None:
                            await self.update_account_last_seen(account.id)
                            logger.info(f"Инициализировано время последнего действия для аккаунта {account.phone_number}")
                            return

                        time_away = datetime.now() - account.last_seen_time
                        away_threshold = timedelta(minutes=account.autoresponder_away_minutes or 30)

                        logger.debug(f"Аккаунт {account.phone_number}: time_away={time_away}, threshold={away_threshold}")

                        if time_away > away_threshold:
                            should_send_away = True
                            if dialog.away_message_sent and dialog.last_autoresponder_sent:
                                time_since_last = datetime.now() - dialog.last_autoresponder_sent
                                if time_since_last < timedelta(hours=1):
                                    should_send_away = False
                                    logger.debug(f"Пропуск сообщения при отсутствии для {sender_id} - отправлено {time_since_last.total_seconds()/60:.1f} минут назад")

                            if should_send_away:
                                await self.send_autoresponse(
                                    event,
                                    account,
                                    account.autoresponder_away_message,
                                    "away"
                                )

                                dialog.away_message_sent = True
                                dialog.last_autoresponder_sent = datetime.now()

                                logger.info(f"Отправлено сообщение автоответчика при отсутствии от {sender_id} к аккаунту {account.phone_number}")

                    session.commit()

            finally:
                db.close_session(session)

        except Exception as e:
            logger.error(f"Ошибка при обработке входящего сообщения для аккаунта {account.phone_number}: {e}")

    async def send_autoresponse(self, event, account: Account, message: str, response_type: str):
        try:
            if hasattr(account, 'cyrillic_substitution') and account.cyrillic_substitution:
                message = apply_cyrillic_substitution(message, enabled=True, rate=0.3)

            custom_message = convert_html_to_custom_format(message)
            parsed_text, entities = CustomParseMode('html').parse(custom_message)

            await event.respond(parsed_text, formatting_entities=entities)

            logger.info(f"Отправлено {response_type} сообщение автоответчика от {account.phone_number}")

        except FloodWaitError as e:
            logger.warning(f"Ошибка ожидания для автоответчика от {account.phone_number}: {e.seconds} секунд")
            from services.message_sender import message_sender
            client = self.active_clients.get(account.id)
            if client:
                await message_sender.handle_flood_wait_error(account, client, "autoresponder", message, None, e.seconds)
        except UserIsBlockedError:
            logger.warning(f"Пользователь заблокировал автоответчик от {account.phone_number}")
        except PeerIdInvalidError:
            logger.warning(f"Неверный идентификатор для автоответчика от {account.phone_number}")
        except Exception as e:
            logger.error(f"Ошибка при отправке автоответчика от {account.phone_number}: {e}")

    async def update_account_last_seen(self, account_id: int):
        session = db.get_session()
        try:
            account = session.query(Account).filter(Account.id == account_id).first()
            if account:
                account.last_seen_time = datetime.now()
                session.commit()
                logger.debug(f"Обновлено время последнего действия для аккаунта {account.phone_number}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени последнего действия для аккаунта {account_id}: {e}")
        finally:
            db.close_session(session)

    async def start_all_autoresponders(self):
        session = db.get_session()
        try:
            accounts = session.query(Account).filter(
                Account.autoresponder_enabled == True
            ).all()

            logger.info(f"Запуск автоответчиков для {len(accounts)} аккаунтов")

            current_time = datetime.now()
            for account in accounts:
                if account.last_seen_time is None:
                    account.last_seen_time = current_time
                    logger.info(f"Инициализировано время последнего действия для аккаунта {account.phone_number}")

            session.commit()

            for account in accounts:
                await self.start_autoresponder_for_account(account)

        except Exception as e:
            logger.error(f"Ошибка при запуске автоответчиков: {e}")
        finally:
            db.close_session(session)

    async def stop_autoresponder_for_account(self, account_id: int):
        if account_id in self.active_clients:
            try:
                await self.active_clients[account_id].disconnect()
                del self.active_clients[account_id]
                logger.info(f"Автоответчик остановлен для аккаунта {account_id}")
            except Exception as e:
                logger.error(f"Ошибка при остановке автоответчика для аккаунта {account_id}: {e}")

    async def stop_all_autoresponders(self):
        self.running = False

        for account_id in list(self.active_clients.keys()):
            await self.stop_autoresponder_for_account(account_id)

        logger.info("Все автоответчики остановлены")

    async def restart_autoresponder_for_account(self, account_id: int):
        await self.stop_autoresponder_for_account(account_id)

        session = db.get_session()
        try:
            account = session.query(Account).filter(Account.id == account_id).first()
            if account:
                await self.start_autoresponder_for_account(account)
        finally:
            db.close_session(session)

    async def run_autoresponder_service(self):
        self.running = True

        logger.info("Запуск сервиса автоответчиков...")

        await self.start_all_autoresponders()

        while self.running:
            try:
                await asyncio.sleep(60)

                for account_id, client in list(self.active_clients.items()):
                    if not client.is_connected():
                        logger.warning(f"Клиент {account_id} отключен, перезапуск...")
                        await self.restart_autoresponder_for_account(account_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в сервисе автоответчиков: {e}")
                await asyncio.sleep(60)

        logger.info("Сервис автоответчиков остановлен")

autoresponder_service = AutoresponderService()

async def start_autoresponder_service():
    await autoresponder_service.run_autoresponder_service()

async def stop_autoresponder_service():
    await autoresponder_service.stop_all_autoresponders()

async def restart_account_autoresponder(account_id: int):
    logger.info(f"Перезапуск автоответчика для аккаунта {account_id}")
    await autoresponder_service.restart_autoresponder_for_account(account_id)

async def update_account_last_seen(account_id: int):
    await autoresponder_service.update_account_last_seen(account_id)
