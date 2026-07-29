from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, User, Account, Proxy, GroupSettings, Payment, Referral, PromoCode, PromoCodeUsage, SystemSettings, MessageLog, ReferralLink
import configparser
import os
from datetime import datetime

class Database:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        db_config = self.config['DATABASE']
        self.database_url = f"postgresql://{db_config['username']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}?client_encoding=utf8"

        self.engine = create_engine(
            self.database_url,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=3600,
            pool_pre_ping=True,
            echo=False,
            connect_args={
                "options": "-c timezone=utc",
                "client_encoding": "utf8"
            }
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self):
        Base.metadata.create_all(bind=self.engine)

    def get_session(self):
        return self.SessionLocal()

    def close_session(self, session):
        session.close()

db = Database()

def get_user_by_telegram_id(telegram_id: str):
    session = db.get_session()
    try:
        return session.query(User).filter(User.telegram_id == telegram_id).first()
    finally:
        db.close_session(session)

def create_user(telegram_id: str, username: str = None, referrer_id: str = None, referral_link_code: str = None):
    session = db.get_session()
    try:
        user_exist = session.query(User).filter(User.telegram_id == telegram_id).first()
        if user_exist:
            return user_exist

        referral_link_id = None
        if referral_link_code:
            referral_link = session.query(ReferralLink).filter(ReferralLink.link_code == referral_link_code).first()
            if referral_link:
                referral_link_id = referral_link.id
                referral_link.users_joined += 1
                session.commit()

        user = User(
            telegram_id=telegram_id,
            username=username,
            referrer_id=referrer_id,
            referral_link_id=referral_link_id,
            bonus_minutes=15
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        if referrer_id:
            referrer = session.query(User).filter(User.telegram_id == referrer_id).first()
            if referrer:
                referrer.referral_count += 1
                referral = Referral(
                    user_id=referrer_id,
                    referred_user_id=telegram_id
                )
                session.add(referral)
                session.commit()
        return user
    finally:
        db.close_session(session)

def get_user_accounts(telegram_id: str):
    session = db.get_session()
    try:
        return session.query(Account).filter(Account.user_id == telegram_id).all()
    finally:
        db.close_session(session)

def create_account(user_id: str, phone_number: str, session_string: str = None, api_id: int = None, api_hash: str = None):
    session = db.get_session()
    try:
        exist_acc = session.query(Account).filter(
            Account.user_id == user_id,
            Account.phone_number == phone_number
        ).first()
        if exist_acc:
            return exist_acc, False
        user = session.query(User).filter(User.telegram_id == user_id).first()
        acc_count = session.query(Account).filter(Account.user_id == user_id).count()
        account = Account(
            user_id=user_id,
            phone_number=phone_number,
            session_string=session_string,
            api_id=api_id,
            api_hash=api_hash
        )
        bonus_applied = False
        if acc_count == 0 and user and user.bonus_minutes > 0:
            account.subscription_minutes = user.bonus_minutes
            user.bonus_minutes = 0
            bonus_applied = True
        session.add(account)
        session.commit()
        session.refresh(account)
        return account, bonus_applied
    finally:
        db.close_session(session)

def get_active_accounts():
    session = db.get_session()
    try:
        return session.query(Account).filter(
            Account.is_active == True,
            Account.subscription_minutes > 0
        ).all()
    finally:
        db.close_session(session)

def update_account_subscription(account_id: int, minutes: int):
    session = db.get_session()
    try:
        account = session.query(Account).filter(Account.id == account_id).first()
        if account:
            account.subscription_minutes += minutes
            session.commit()
            return account
        return None
    finally:
        db.close_session(session)

def get_proxy_by_id(proxy_id: int):
    session = db.get_session()
    try:
        return session.query(Proxy).filter(Proxy.id == proxy_id).first()
    finally:
        db.close_session(session)

def create_proxy(host: str, port: int, username: str = None, password: str = None, proxy_type: str = 'SOCKS5', added_by: str = 'admin'):
    session = db.get_session()
    try:
        proxy = Proxy(
            host=host,
            port=port,
            username=username,
            password=password,
            proxy_type=proxy_type,
            added_by=added_by
        )
        session.add(proxy)
        session.commit()
        session.refresh(proxy)
        return proxy
    finally:
        db.close_session(session)

def get_admin_proxies():
    session = db.get_session()
    try:
        return session.query(Proxy).filter(Proxy.added_by == 'admin').all()
    finally:
        db.close_session(session)

def get_all_proxies():
    session = db.get_session()
    try:
        return session.query(Proxy).all()
    finally:
        db.close_session(session)

def get_working_proxies():
    session = db.get_session()
    try:
        return session.query(Proxy).filter(
            Proxy.is_active == True,
            Proxy.is_working == True
        ).all()
    finally:
        db.close_session(session)

def update_proxy_status(proxy_id: int, is_working: bool, error_message: str = None):
    session = db.get_session()
    try:
        proxy = session.query(Proxy).filter(Proxy.id == proxy_id).first()
        if proxy:
            proxy.is_working = is_working
            proxy.last_checked = datetime.now()
            proxy.check_count += 1
            if not is_working:
                proxy.fail_count += 1
            session.commit()
            return proxy
        return None
    finally:
        db.close_session(session)

def delete_proxy(proxy_id: int):
    session = db.get_session()
    try:
        proxy = session.query(Proxy).filter(Proxy.id == proxy_id).first()
        if proxy:
            session.delete(proxy)
            session.commit()
            return True
        return False
    finally:
        db.close_session(session)

def get_random_working_proxy():
    session = db.get_session()
    try:
        import random
        working_proxies = session.query(Proxy).filter(
            Proxy.is_active == True,
            Proxy.is_working == True
        ).all()
        if working_proxies:
            return random.choice(working_proxies)
        return None
    finally:
        db.close_session(session)

def get_group_settings(account_id: int, group_id: str):
    session = db.get_session()
    try:
        return session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()
    finally:
        db.close_session(session)

def create_group_settings(account_id: int, group_id: str, group_name: str = None):
    session = db.get_session()
    try:
        exist = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()
        if exist:
            return exist
        settings = GroupSettings(
            account_id=account_id,
            group_id=group_id,
            group_name=group_name
        )
        session.add(settings)
        session.commit()
        session.refresh(settings)
        return settings
    finally:
        db.close_session(session)

def create_payment(user_id: str, amount: float, currency: str, payment_method: str, transaction_id: str = None):
    session = db.get_session()
    try:
        payment = Payment(
            user_id=user_id,
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            transaction_id=transaction_id
        )
        session.add(payment)
        session.commit()
        session.refresh(payment)
        return payment
    finally:
        db.close_session(session)

def log_message(account_id: int, group_id: str, message_text: str, has_media: bool, status: str, error_message: str = None):
    session = db.get_session()
    max_retries = 3

    for attempt in range(max_retries):
        try:
            log = MessageLog(
                account_id=account_id,
                group_id=group_id,
                message_text=message_text,
                has_media=has_media,
                status=status,
                error_message=error_message
            )
            session.add(log)
            session.commit()
            break

        except Exception as e:
            session.rollback()

            if attempt < max_retries - 1:
                db.close_session(session)
                session = db.get_session()
                print(f"⚠️ Попытка {attempt + 1} записи в БД неудачна, повторяем: {e}")
            else:
                print(f"❌ Не удалось записать лог в БД после {max_retries} попыток: {e}")

    try:
        db.close_session(session)
    except:
        pass

def decrease_subscription_minutes():
    session = db.get_session()
    try:
        active_accounts = session.query(Account).filter(
            Account.is_active == True,
            Account.subscription_minutes > 0
        ).all()
        expired_account_ids = []
        hour_warning_account_ids = []
        fifteen_min_warning_account_ids = []

        for account in active_accounts:
            if account.subscription_minutes == 61:
                hour_warning_account_ids.append(account.id)
            elif account.subscription_minutes == 16:
                fifteen_min_warning_account_ids.append(account.id)

            account.subscription_minutes -= 1
            if account.subscription_minutes <= 0:
                account.is_active = False
                expired_account_ids.append(account.id)
        session.commit()
        return len(active_accounts), expired_account_ids, hour_warning_account_ids, fifteen_min_warning_account_ids
    finally:
        db.close_session(session)

def get_super_groups_by_account(account_id: int):
    session = db.get_session()
    try:
        from database.models import SuperGroup
        return session.query(SuperGroup).filter(SuperGroup.account_id == account_id).all()
    finally:
        db.close_session(session)

def get_super_group_by_id(super_group_id: int):
    session = db.get_session()
    try:
        from database.models import SuperGroup
        return session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()
    finally:
        db.close_session(session)


def update_super_group_message(super_group_id: int, message: str):
    session = db.get_session()
    try:
        from database.models import SuperGroup
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()
        if super_group:
            super_group.custom_message = message
            session.commit()
            return True
        return False
    finally:
        db.close_session(session)

def update_super_group_media(super_group_id: int, media_type: str, media_data: bytes):
    session = db.get_session()
    try:
        from database.models import SuperGroup
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()
        if super_group:
            if media_type == 'photo':
                super_group.custom_photo = media_data
            elif media_type == 'gif':
                super_group.custom_gif = media_data
            elif media_type == 'video':
                super_group.custom_video = media_data

            session.commit()
            return True
        return False
    finally:
        db.close_session(session)

def update_super_group_interval(super_group_id: int, interval: int):
    session = db.get_session()
    try:
        from database.models import SuperGroup
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()
        if super_group:
            super_group.custom_interval = interval
            session.commit()
            return True
        return False
    finally:
        db.close_session(session)

def toggle_super_group_status(super_group_id: int):
    session = db.get_session()
    try:
        from database.models import SuperGroup
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()
        if super_group:
            super_group.is_enabled = not super_group.is_enabled
            session.commit()
            return super_group.is_enabled
        return None
    finally:
        db.close_session(session)

def delete_super_group(super_group_id: int):
    session = db.get_session()
    try:
        from database.models import SuperGroup
        super_group = session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()
        if super_group:
            session.delete(super_group)
            session.commit()
            return True
        return False
    finally:
        db.close_session(session)

def get_super_group_settings(super_group_id: int):
    session = db.get_session()
    try:
        from database.models import SuperGroup
        return session.query(SuperGroup).filter(SuperGroup.id == super_group_id).first()
    finally:
        db.close_session(session)

def create_referral_link(name: str, link_code: str = None):
    session = db.get_session()
    try:
        import uuid

        if not link_code:
            link_code = str(uuid.uuid4())[:8]

        existing_link = session.query(ReferralLink).filter(ReferralLink.link_code == link_code).first()
        if existing_link:
            link_code = str(uuid.uuid4())[:8]

        referral_link = ReferralLink(
            name=name,
            link_code=link_code
        )
        session.add(referral_link)
        session.commit()
        session.refresh(referral_link)
        return referral_link
    finally:
        db.close_session(session)

def get_all_referral_links():
    session = db.get_session()
    try:
        return session.query(ReferralLink).filter(ReferralLink.is_active == True).order_by(ReferralLink.created_at.desc()).all()
    finally:
        db.close_session(session)

def get_referral_link_by_id(link_id: int):
    session = db.get_session()
    try:
        return session.query(ReferralLink).filter(ReferralLink.id == link_id).first()
    finally:
        db.close_session(session)

def get_referral_link_by_code(link_code: str):
    session = db.get_session()
    try:
        return session.query(ReferralLink).filter(ReferralLink.link_code == link_code).first()
    finally:
        db.close_session(session)

def delete_referral_link(link_id: int):
    session = db.get_session()
    try:
        referral_link = session.query(ReferralLink).filter(ReferralLink.id == link_id).first()
        if referral_link:
            session.delete(referral_link)
            session.commit()
            return True
        return False
    finally:
        db.close_session(session)

def update_referral_link_stats(link_code: str, user_joined: bool = False, payment_amount: float = 0.0):
    session = db.get_session()
    try:
        referral_link = session.query(ReferralLink).filter(ReferralLink.link_code == link_code).first()
        if referral_link:
            if user_joined:
                referral_link.users_joined += 1
            if payment_amount > 0:
                referral_link.users_paid += 1
                referral_link.total_payments += payment_amount
            session.commit()
            return True
        return False
    finally:
        db.close_session(session)

def get_active_topup_bonus_promocodes():
    session = db.get_session()
    try:
        return session.query(PromoCode).filter(
            PromoCode.type == "topup_bonus",
            PromoCode.is_active == True
        ).all()
    finally:
        db.close_session(session)

def get_topup_bonus_promocode_by_code(code: str):
    session = db.get_session()
    try:
        return session.query(PromoCode).filter(
            PromoCode.code == code.upper(),
            PromoCode.type == "topup_bonus",
            PromoCode.is_active == True
        ).first()
    finally:
        db.close_session(session)

def apply_topup_bonus_promocode(promocode_id: int):
    session = db.get_session()
    try:
        promo = session.query(PromoCode).filter(PromoCode.id == promocode_id).first()
        if promo and promo.type == "topup_bonus":
            if promo.max_uses is None or promo.used_count < promo.max_uses:
                promo.used_count += 1
                session.commit()
                return True
        return False
    finally:
        db.close_session(session)

def has_user_used_promocode(user_id: str, promocode_id: int):
    session = db.get_session()
    try:
        usage = session.query(PromoCodeUsage).filter(
            PromoCodeUsage.user_id == user_id,
            PromoCodeUsage.promo_code_id == promocode_id
        ).first()
        return usage is not None
    finally:
        db.close_session(session)

def record_promocode_usage(user_id: str, promocode_id: int, bonus_amount: float):
    session = db.get_session()
    try:
        usage = PromoCodeUsage(
            user_id=user_id,
            promo_code_id=promocode_id,
            bonus_amount=bonus_amount
        )
        session.add(usage)
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        db.close_session(session)

def get_available_topup_promocodes_for_user(user_id: str):
    session = db.get_session()
    try:
        active_promos = session.query(PromoCode).filter(
            PromoCode.type == "topup_bonus",
            PromoCode.is_active == True
        ).all()

        available_promos = []
        for promo in active_promos:
            if promo.max_uses is not None and promo.used_count >= promo.max_uses:
                continue

            used = session.query(PromoCodeUsage).filter(
                PromoCodeUsage.user_id == user_id,
                PromoCodeUsage.promo_code_id == promo.id
            ).first()

            if not used:
                available_promos.append(promo)

        return available_promos
    finally:
        db.close_session(session)

def is_promocode_available_for_user(user_id: str, promo_code: str):
    session = db.get_session()
    try:
        promo = session.query(PromoCode).filter(
            PromoCode.code == promo_code.upper(),
            PromoCode.is_active == True
        ).first()

        if not promo:
            return False, "Промокод не найден или неактивен"

        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            return False, "Промокод превысил лимит использований"

        used = session.query(PromoCodeUsage).filter(
            PromoCodeUsage.user_id == user_id,
            PromoCodeUsage.promo_code_id == promo.id
        ).first()

        if used:
            return False, "Вы уже использовали этот промокод"

        return True, "Промокод доступен"

    finally:
        db.close_session(session)
