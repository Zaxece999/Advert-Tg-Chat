import asyncio
import logging
import hashlib
import hmac
import time
from typing import Dict, Optional, Tuple
import aiohttp
import configparser

from database.database import create_payment, update_account_subscription, get_user_by_telegram_id, db
from database.models import Payment, Account, User

logger = logging.getLogger(__name__)

class CryptoPaymentService:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.api_token = self.config.get('CRYPTOBOT', 'token')
        self.base_url = "https://pay.crypt.bot/api"
        self.bot_username = self.config.get('SETTINGS', 'bot_username', fallback='').lstrip('@')

    async def create_invoice(self, user_id: str, amount: float, currency: str,
                           description: str = None) -> Tuple[bool, Optional[Dict]]:
        try:
            payload = {
                "asset": currency,
                "amount": str(amount),
                "description": description or "Оплата подписки",
                "payload": user_id
            }

            if self.bot_username:
                payload["paid_btn_name"] = "callback"
                payload["paid_btn_url"] = f"https://t.me/{self.bot_username}?start=payment_completed"

            headers = {
                "Crypto-Pay-API-Token": self.api_token,
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/createInvoice",
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("ok"):
                            return True, data.get("result")
                        else:
                            logger.error(f"Ошибка CryptoBot API: {data.get('error')}")
                            return False, None
                    else:
                        logger.error(f"HTTP ошибка CryptoBot API: {response.status}")
                        return False, None

        except Exception as e:
            logger.error(f"Ошибка при создании счета: {e}")
            return False, None

    async def get_all_invoices(self) -> Tuple[bool, list]:
        try:
            headers = {
                "Crypto-Pay-API-Token": self.api_token
            }

            url = f"{self.base_url}/getInvoices"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers
                ) as response:
                    response_text = await response.text()

                    if response.status == 200:
                        try:
                            data = await response.json()

                            if data.get("ok"):
                                invoices = data.get("result", {}).get("items", [])
                                return True, invoices
                            else:
                                logger.error(f"Ошибка CryptoBot API: {data.get('error')}")
                                return False, []
                        except Exception as parse_error:
                            logger.error(f"Не удалось разобрать JSON-ответ: {parse_error}")
                            return False, []
                    else:
                        logger.error(f"HTTP ошибка CryptoBot API: {response.status}")
                        logger.error(f"Тело ответа: {response_text}")
                        return False, []

        except Exception as e:
            logger.error(f"Ошибка при получении счетов: {e}")
            return False, []

    async def check_invoice_status(self, invoice_id: str) -> Tuple[bool, Optional[Dict]]:
        try:
            headers = {
                "Crypto-Pay-API-Token": self.api_token
            }

            params = {
                "invoice_ids": invoice_id
            }

            url = f"{self.base_url}/getInvoices"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    params=params
                ) as response:
                    response_text = await response.text()

                    if response.status == 200:
                        try:
                            data = await response.json()

                            if data.get("ok"):
                                invoices = data.get("result", {}).get("items", [])
                                if invoices:
                                    return True, invoices[0]
                                else:
                                    logger.warning(f"Счета с ID {invoice_id} не найдены")
                                    return False, None
                            else:
                                logger.error(f"Ошибка CryptoBot API: {data.get('error')}")
                                return False, None
                        except Exception as parse_error:
                            logger.error(f"Не удалось разобрать JSON-ответ: {parse_error}")
                            return False, None
                    else:
                        logger.error(f"HTTP ошибка CryptoBot API: {response.status}")
                        logger.error(f"Тело ответа: {response_text}")
                        return False, None

        except Exception as e:
            logger.error(f"Ошибка при проверке статуса счета: {e}")
            return False, None

    async def process_payment(self, user_id: str, days: int, amount: float,
                            currency: str, account_id: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        try:
            description = f"Подписка на {days} дней"
            success, invoice_data = await self.create_invoice(user_id, amount, currency, description)

            if not success or not invoice_data:
                return False, "Не удалось создать счет на оплату"

            invoice_id = invoice_data.get("invoice_id")
            bot_url = invoice_data.get("bot_invoice_url")
            url_hash = bot_url.split('?start=')[-1] if '?start=' in bot_url else str(invoice_id)

            payment = create_payment(
                user_id=user_id,
                amount=amount,
                currency=currency,
                payment_method="crypto",
                transaction_id=str(invoice_id)
            )

            if payment:
                return True, bot_url
            else:
                return False, "Не удалось создать запись оплаты"

        except Exception as e:
            logger.error(f"Ошибка при обработке оплаты: {e}")
            return False, str(e)

    async def confirm_payment(self, url_hash: str) -> Tuple[bool, Optional[str], Optional[str]]:
        try:
            success, all_invoices_data = await self.get_all_invoices()

            if not success:
                logger.error("Не удалось получить счета от API")
                return False, "Не удалось получить счета", "not_found"

            target_invoice = None

            for invoice in all_invoices_data:
                bot_url = invoice.get("bot_invoice_url", "")
                if url_hash in bot_url:
                    target_invoice = invoice
                    break

            session = db.get_session()
            try:
                if not target_invoice:
                    recent_payments = session.query(Payment).filter(
                        Payment.status == "pending"
                    ).order_by(Payment.created_at.desc()).limit(10).all()

                    for invoice in all_invoices_data:
                        invoice_id = str(invoice.get("invoice_id", ""))
                        for payment in recent_payments:
                            if payment.transaction_id == invoice_id:
                                target_invoice = invoice
                                break
                        if target_invoice:
                            break

                if not target_invoice:
                    logger.error("Не найден подходящий счет")
                    return False, "Платеж не найден", "not_found"

                invoice_status = target_invoice.get("status")
                real_invoice_id = str(target_invoice.get("invoice_id"))

                if invoice_status == "active":
                    return False, "Платеж еще не завершен", "pending"
                elif invoice_status != "paid":
                    return False, "Платеж не прошел или отменен", "failed"

                payment = session.query(Payment).filter(
                    Payment.transaction_id == real_invoice_id
                ).first()

                if not payment:
                    logger.error(f"Запись оплаты не найдена в базе для invoice_id: {real_invoice_id}")
                    return False, "Запись оплаты не найдена", "not_found"

                if payment.status == "completed":
                    return False, "Платеж уже обработан", "already_processed"

                payment.status = "completed"

                user = get_user_by_telegram_id(payment.user_id)

                if user:
                    original_amount = payment.amount
                    final_amount = payment.amount

                    from database.database import get_available_topup_promocodes_for_user, apply_topup_bonus_promocode, record_promocode_usage
                    available_promos = get_available_topup_promocodes_for_user(payment.user_id)

                    promo_bonus = 0
                    applied_promos = []

                    for promo in available_promos:
                        bonus_amount = (original_amount * promo.value) / 100
                        promo_bonus += bonus_amount

                        if apply_topup_bonus_promocode(promo.id):
                            record_promocode_usage(payment.user_id, promo.id, bonus_amount)
                            applied_promos.append((promo.code, promo.value, bonus_amount))

                    final_amount += promo_bonus
                    user.balance += final_amount

                    user_in_session = session.query(User).filter(User.telegram_id == user.telegram_id).first()
                    if user_in_session:
                        user_in_session.balance = user.balance
                        session.commit()
                    else:
                        session.commit()

                    if user_in_session and user_in_session.referral_link_id:
                        from database.models import ReferralLink
                        referral_link = session.query(ReferralLink).filter(
                            ReferralLink.id == user_in_session.referral_link_id
                        ).first()
                        if referral_link:
                            referral_link.users_paid += 1
                            referral_link.total_payments += payment.amount
                            session.commit()

                    if user.referrer_id:
                        referrer = get_user_by_telegram_id(user.referrer_id)
                        if referrer:
                            bonus = payment.amount * 0.25
                            referrer.balance += bonus
                            session.commit()

                    message = f"✅ Платеж подтвержден!\n\n💰 Основная сумма: <b>${original_amount}</b>"

                    if applied_promos:
                        message += "\n\n🎉 Применены промокоды:"
                        for promo_code, promo_percent, bonus_amount in applied_promos:
                            message += f"\n📈 <code>{promo_code}</code> (+{promo_percent}%): <b>+${bonus_amount:.2f}</b>"
                        message += f"\n\n💎 Итого зачислено: <b>${final_amount:.2f}</b>"
                    else:
                        message += f"\n\n💎 Зачислено: <b>${final_amount:.2f}</b>"

                    message += f"\n\n💳 Текущий баланс: <b>${user.balance:.2f}</b>"

                    return True, message, "success"
                else:
                    logger.error(f"Пользователь не найден: {payment.user_id}")
                    return False, "Пользователь не найден", "error"

            finally:
                db.close_session(session)

        except Exception as e:
            logger.error(f"Ошибка при подтверждении платежа: {e}")
            return False, str(e), "error"

    def get_supported_currencies(self) -> list:
        return ["USDT", "USDC", "BTC", "ETH", "TRX", "DOGE"]

    def calculate_price_in_currency(self, usd_amount: float, currency: str) -> float:
        exchange_rates = {
            "USDT": 1.0,
            "USDC": 1.0,
            "BTC": 0.000025,
            "ETH": 0.0005,
            "TRX": 12.5,
            "DOGE": 14.3
        }

        rate = exchange_rates.get(currency, 1.0)
        return usd_amount * rate

payment_service = CryptoPaymentService()

async def create_payment_invoice(user_id: str, days: int, amount: float, currency: str) -> Tuple[bool, Optional[str]]:
    return await payment_service.process_payment(user_id, days, amount, currency)

async def check_payment_status(payment_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
    return await payment_service.confirm_payment(payment_id)
