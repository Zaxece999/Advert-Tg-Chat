import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database.database import decrease_subscription_minutes, get_active_accounts, db
from database.models import Account, User
from services.message_sender import message_sender
from services.autoresponder_service import autoresponder_service

logger = logging.getLogger(__name__)

class BackgroundTasks:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.message_sender_task = None
        self.autoresponder_task = None

    async def start(self):
        logger.info("Запуск фоновых задач...")

        self.scheduler.add_job(
            func=self.decrease_subscription_time,
            trigger=IntervalTrigger(minutes=1),
            id='decrease_subscription_time',
            name='Уменьшение времени подписки',
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=30
        )

        self.scheduler.add_job(
            func=self.check_proxy_health,
            trigger=IntervalTrigger(minutes=30),
            id='check_proxy_health',
            name='Проверка прокси',
            replace_existing=True
        )

        self.scheduler.add_job(
            func=self.cleanup_inactive_accounts,
            trigger=IntervalTrigger(hours=1),
            id='cleanup_inactive_accounts',
            name='Очистка неактивных аккаунтов',
            replace_existing=True
        )

        self.scheduler.add_job(
            func=self.cleanup_old_logs,
            trigger=IntervalTrigger(hours=24),
            id='cleanup_old_logs',
            name='Очистка старых логов',
            replace_existing=True
        )

        self.scheduler.start()
        logger.info("📅 Планировщик успешно запущен")

        jobs = self.scheduler.get_jobs()
        logger.info(f"📝 Запланировано задач: {len(jobs)}")
        for job in jobs:
            logger.info(f"  - {job.name} (ID: {job.id}), Следующий запуск: {job.next_run_time}")

        self.message_sender_task = asyncio.create_task(self.run_message_sender())
        self.autoresponder_task = asyncio.create_task(self.run_autoresponder_service())
        logger.info("✅ Фоновые задачи успешно запущены")

    async def stop(self):
        logger.info("Остановка фоновых задач...")

        if self.scheduler.running:
            self.scheduler.shutdown()

        if self.message_sender_task and not self.message_sender_task.done():
            self.message_sender_task.cancel()
            try:
                await self.message_sender_task
            except asyncio.CancelledError:
                pass

        if hasattr(self, 'autoresponder_task') and self.autoresponder_task and not self.autoresponder_task.done():
            self.autoresponder_task.cancel()
            try:
                await self.autoresponder_task
            except asyncio.CancelledError:
                pass

        await message_sender.cleanup_clients()
        await autoresponder_service.stop_all_autoresponders()
        logger.info("Фоновые задачи остановлены")

    async def decrease_subscription_time(self):
        try:
            logger.info("🔄 Запуск планового уменьшения времени подписки...")
            from database.database import db
            from database.models import Account
            session = db.get_session()
            try:
                active_accounts = session.query(Account).filter(
                    Account.is_active == True,
                    Account.subscription_minutes > 0
                ).all()
                logger.info(f"📊 Найдено {len(active_accounts)} активных аккаунтов с подпиской")
                for account in active_accounts:
                    logger.info(f"  - {account.phone_number}: {account.subscription_minutes} минут")
            finally:
                db.close_session(session)

            affected_accounts, expired_account_ids, hour_warning_account_ids, fifteen_min_warning_account_ids = decrease_subscription_minutes()
            logger.info(f"✅ Время подписки уменьшено для {affected_accounts} аккаунтов")

            session = db.get_session()
            try:
                active_accounts_after = session.query(Account).filter(
                    Account.is_active == True,
                    Account.subscription_minutes > 0
                ).all()
                logger.info(f"📊 После уменьшения: {len(active_accounts_after)} активных аккаунтов осталось")
                for account in active_accounts_after:
                    logger.info(f"  - {account.phone_number}: {account.subscription_minutes} минут")
            finally:
                db.close_session(session)

            if expired_account_ids:
                await self.notify_expired_subscriptions(expired_account_ids)
                logger.info(f"📧 Оповещено {len(expired_account_ids)} пользователей об окончании подписки")

            if hour_warning_account_ids:
                await self.notify_subscription_warning(hour_warning_account_ids, "hour")
                logger.info(f"⏰ Оповещено {len(hour_warning_account_ids)} пользователей о подписке (остался час)")

            if fifteen_min_warning_account_ids:
                await self.notify_subscription_warning(fifteen_min_warning_account_ids, "fifteen_minutes")
                logger.info(f"⏰ Оповещено {len(fifteen_min_warning_account_ids)} пользователей о подписке (осталось 15 минут)")

        except Exception as e:
            logger.error(f"❌ Ошибка при уменьшении времени подписки: {e}")
            import traceback
            logger.error(f"❌ Трассировка: {traceback.format_exc()}")

    async def check_proxy_health(self):
        try:
            from database.models import Proxy
            from utils.proxy_validator import proxy_validator
            from database.database import update_proxy_status

            session = db.get_session()
            try:
                proxies = session.query(Proxy).filter(Proxy.is_active == True).all()

                inactive_count = 0
                for proxy in proxies:
                    proxy_data = {
                        'host': proxy.host,
                        'port': proxy.port,
                        'username': proxy.username,
                        'password': proxy.password,
                        'proxy_type': proxy.proxy_type
                    }

                    health = await proxy_validator.check_proxy_health(proxy_data)
                    update_proxy_status(proxy.id, health['is_valid'], health.get('error'))

                    if not health['is_valid']:
                        inactive_count += 1
                        logger.warning(f"Прокси {proxy.host}:{proxy.port} помечен как нерабочий: {health['error']}")
                    else:
                        logger.info(f"Прокси {proxy.host}:{proxy.port} работает (время отклика: {health['response_time']:.2f}с)")

                logger.info(f"Проверка прокси завершена. {inactive_count} прокси помечены как нерабочие")

            finally:
                db.close_session(session)

        except Exception as e:
            logger.error(f"Ошибка при проверке прокси: {e}")

    async def cleanup_inactive_accounts(self):
        try:
            session = db.get_session()
            try:
                expired_accounts = session.query(Account).filter(
                    Account.subscription_minutes <= 0,
                    Account.is_active == False
                ).all()

                logger.info(f"Найдено {len(expired_accounts)} неактивных аккаунтов с истекшей подпиской")
                for account in expired_accounts:
                    logger.debug(f"Неактивный аккаунт: {account.phone_number} (Пользователь: {account.user_id})")

            finally:
                db.close_session(session)

        except Exception as e:
            logger.error(f"Ошибка при проверке неактивных аккаунтов: {e}")

    async def cleanup_old_logs(self):
        try:
            from database.models import MessageLog

            session = db.get_session()
            try:
                cutoff_date = datetime.now() - timedelta(days=7)

                deleted_count = session.query(MessageLog).filter(
                    MessageLog.sent_at < cutoff_date
                ).delete()

                session.commit()
                logger.info(f"Очищено {deleted_count} старых логов сообщений")

            finally:
                db.close_session(session)

        except Exception as e:
            logger.error(f"Ошибка при очистке старых логов: {e}")

    async def notify_expired_subscriptions(self, expired_account_ids):
        try:
            from aiogram import Bot
            import configparser
            from database.database import db
            from database.models import Account

            config = configparser.ConfigParser()
            config.read('config.ini')
            bot_token = config.get('TELEGRAM', 'bot_token')

            bot = Bot(token=bot_token)

            session = db.get_session()
            try:
                for account_id in expired_account_ids:
                    account = session.query(Account).filter(Account.id == account_id).first()
                    if not account:
                        continue

                    try:
                        price_1 = config.get('PRICING', 'day_1', fallback='1.5')
                        price_7 = config.get('PRICING', 'day_7', fallback='10')
                        price_14 = config.get('PRICING', 'day_14', fallback='19')
                        price_30 = config.get('PRICING', 'day_30', fallback='35')

                        message = f"""
⏰ <b>Подписка истекла!</b>

📱 Аккаунт: {account.phone_number}
🕒 Время истечения: {datetime.now().strftime('%d.%m.%Y %H:%M')}

💰 <b>Цены на продление:</b>
• 1 день — {price_1}$
• 7 дней — {price_7}$
• 14 дней — {price_14}$
• 30 дней — {price_30}$

🔄 Продлите подписку для продолжения работы бота!
"""

                        await bot.send_message(
                            chat_id=int(account.user_id),
                            text=message,
                            parse_mode="HTML"
                        )

                        logger.info(f"Уведомление об истечении подписки отправлено пользователю {account.user_id} для аккаунта {account.phone_number}")

                    except Exception as e:
                        logger.error(f"Не удалось отправить уведомление пользователю {account.user_id}: {e}")

            finally:
                db.close_session(session)

            await bot.session.close()

        except Exception as e:
            logger.error(f"Ошибка при отправке уведомлений об истечении подписки: {e}")

    async def notify_subscription_warning(self, account_ids, warning_type):
        try:
            from aiogram import Bot
            import configparser
            from database.database import db
            from database.models import Account

            config = configparser.ConfigParser()
            config.read('config.ini')
            bot_token = config.get('TELEGRAM', 'bot_token')

            bot = Bot(token=bot_token)

            session = db.get_session()
            try:
                for account_id in account_ids:
                    account = session.query(Account).filter(Account.id == account_id).first()
                    if not account:
                        continue

                    try:
                        price_1 = config.get('PRICING', 'day_1', fallback='1.5')
                        price_7 = config.get('PRICING', 'day_7', fallback='10')
                        price_14 = config.get('PRICING', 'day_14', fallback='19')
                        price_30 = config.get('PRICING', 'day_30', fallback='35')

                        if warning_type == "hour":
                            time_left = "1 час"
                            emoji = "⏰"
                            urgency = "скоро"
                        else:
                            time_left = "15 минут"
                            emoji = "🚨"
                            urgency = "очень скоро"

                        message = f"""
{emoji} <b>Подписка {urgency} истечет!</b>

📱 Аккаунт: {account.phone_number}
⏱️ Осталось времени: {time_left}

💰 <b>Цены на продление:</b>
• 1 день — {price_1}$
• 7 дней — {price_7}$
• 14 дней — {price_14}$
• 30 дней — {price_30}$

🔄 Продлите подписку, чтобы не прерывать работу бота!
"""

                        await bot.send_message(
                            chat_id=int(account.user_id),
                            text=message,
                            parse_mode="HTML"
                        )

                        logger.info(f"✅ Отправлено предупреждение о подписке пользователю {account.user_id} (осталось: {time_left})")

                    except Exception as e:
                        logger.error(f"Не удалось отправить предупреждение о подписке пользователю {account.user_id}: {e}")

            finally:
                db.close_session(session)

            await bot.session.close()

        except Exception as e:
            logger.error(f"Ошибка при отправке предупреждений о подписке: {e}")

    async def run_message_sender(self):
        logger.info("Запуск фоновой задачи рассылки сообщений...")

        while True:
            try:
                await message_sender.run_broadcast_cycle()
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info("Задача рассылки сообщений отменена")
                break
            except Exception as e:
                logger.error(f"Ошибка в фоновой задаче рассылки сообщений: {e}")
                await asyncio.sleep(60)

    async def send_user_notification(self, user_id: str, message: str):
        try:
            logger.info(f"Уведомление для пользователя {user_id}: {message}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")

    async def run_autoresponder_service(self):
        logger.info("Запуск фоновой задачи автoответчика...")

        try:
            await autoresponder_service.run_autoresponder_service()
        except asyncio.CancelledError:
            logger.info("Задача автoответчика отменена")
            await autoresponder_service.stop_all_autoresponders()
        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче автoответчика: {e}")
            await asyncio.sleep(60)

background_tasks = BackgroundTasks()

async def start_background_tasks():
    logger.info("🚀 Запуск фоновых задач из обработчика старта...")
    await background_tasks.start()

async def stop_background_tasks():
    logger.info("🛑 Остановка фоновых задач из обработчика завершения...")
    await background_tasks.stop()
