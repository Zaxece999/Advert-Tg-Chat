from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    bonus_minutes = Column(Integer, default=0)
    referral_count = Column(Integer, default=0)
    referrer_id = Column(String, nullable=True)
    referral_link_id = Column(Integer, ForeignKey('referral_links.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(Boolean, default=False)

    accounts = relationship("Account", back_populates="user")
    payments = relationship("Payment", back_populates="user")
    referrals = relationship("Referral", back_populates="user")
    referral_link = relationship("ReferralLink", back_populates="referred_users", foreign_keys="User.referral_link_id")

class Account(Base):
    __tablename__ = 'accounts'

    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.telegram_id'), nullable=False)
    phone_number = Column(String, nullable=False)
    session_string = Column(Text, nullable=True)
    is_active = Column(Boolean, default=False)
    subscription_minutes = Column(Integer, default=0)
    proxy_id = Column(Integer, ForeignKey('proxies.id'), nullable=True)

    api_id = Column(Integer, nullable=True)
    api_hash = Column(String, nullable=True)

    default_message = Column(Text, nullable=True)
    message_interval = Column(Integer, default=60)
    send_delay = Column(Integer, default=5)

    default_photo = Column(LargeBinary, nullable=True)
    default_gif = Column(LargeBinary, nullable=True)
    default_video = Column(LargeBinary, nullable=True)

    profile_name = Column(String, nullable=True)
    profile_username = Column(String, nullable=True)
    profile_bio = Column(Text, nullable=True)
    profile_photo = Column(LargeBinary, nullable=True)

    cyrillic_substitution = Column(Boolean, default=False)

    auto_spam_unlock = Column(Boolean, default=False)

    autoresponder_enabled = Column(Boolean, default=False)
    autoresponder_first_message = Column(Text, nullable=True)
    autoresponder_away_message = Column(Text, nullable=True)
    autoresponder_away_minutes = Column(Integer, default=30)
    last_seen_time = Column(DateTime, default=datetime.utcnow)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="accounts")
    proxy = relationship("Proxy", back_populates="accounts")
    group_settings = relationship("GroupSettings", back_populates="account")

class Proxy(Base):
    __tablename__ = 'proxies'

    id = Column(Integer, primary_key=True)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    password = Column(String, nullable=True)
    proxy_type = Column(String, default='SOCKS5')
    is_active = Column(Boolean, default=True)
    is_working = Column(Boolean, default=True)
    last_checked = Column(DateTime, default=datetime.utcnow)
    check_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    added_by = Column(String, nullable=True)

    accounts = relationship("Account", back_populates="proxy")

class GroupSettings(Base):
    __tablename__ = 'group_settings'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    group_id = Column(String, nullable=False)
    group_name = Column(String, nullable=True)

    custom_message = Column(Text, nullable=True)
    custom_photo = Column(LargeBinary, nullable=True)
    custom_gif = Column(LargeBinary, nullable=True)
    custom_video = Column(LargeBinary, nullable=True)
    custom_interval = Column(Integer, nullable=True)
    escrow_username = Column(String(255), nullable=True)

    media_blocked = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)

    last_message_time = Column(DateTime, nullable=True)

    slowmode_seconds = Column(Integer, default=0)
    slowmode_minutes = Column(Integer, default=0)

    account = relationship("Account", back_populates="group_settings")

class Payment(Base):
    __tablename__ = 'payments'

    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.telegram_id'), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    payment_method = Column(String, nullable=False)
    status = Column(String, default='pending')
    transaction_id = Column(String, nullable=True)
    minutes_added = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="payments")

class Referral(Base):
    __tablename__ = 'referrals'

    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.telegram_id'), nullable=False)
    referred_user_id = Column(String, nullable=False)
    bonus_earned = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="referrals")

class PromoCode(Base):
    __tablename__ = 'promo_codes'

    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    type = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    max_uses = Column(Integer, nullable=True)
    used_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

class PromoCodeUsage(Base):
    __tablename__ = 'promo_code_usage'

    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.telegram_id'), nullable=False)
    promo_code_id = Column(Integer, ForeignKey('promo_codes.id'), nullable=False)
    used_at = Column(DateTime, default=datetime.utcnow)
    bonus_amount = Column(Float, nullable=True)

    user = relationship("User")
    promo_code = relationship("PromoCode")

class SystemSettings(Base):
    __tablename__ = 'system_settings'

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=False)
    description = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

class MessageLog(Base):
    __tablename__ = 'message_logs'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    group_id = Column(String, nullable=False)
    message_text = Column(Text, nullable=True)
    has_media = Column(Boolean, default=False)
    status = Column(String, nullable=False)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)

class AutoresponderDialog(Base):
    __tablename__ = 'autoresponder_dialogs'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    dialog_id = Column(String, nullable=False)
    dialog_username = Column(String, nullable=True)
    first_message_sent = Column(Boolean, default=False)
    away_message_sent = Column(Boolean, default=False)
    last_user_message = Column(DateTime, default=datetime.utcnow)
    last_autoresponder_sent = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account")

class AccountTemplate(Base):
    __tablename__ = 'account_templates'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    user_id = Column(String, ForeignKey('users.telegram_id'), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    profile_name = Column(String, nullable=True)
    profile_username = Column(String, nullable=True)
    profile_bio = Column(Text, nullable=True)
    profile_photo = Column(LargeBinary, nullable=True)

    default_message = Column(Text, nullable=True)
    message_interval = Column(Integer, default=60)
    default_photo = Column(LargeBinary, nullable=True)
    default_gif = Column(LargeBinary, nullable=True)
    default_video = Column(LargeBinary, nullable=True)

    cyrillic_substitution = Column(Boolean, default=False)

    autoresponder_enabled = Column(Boolean, default=False)
    autoresponder_first_message = Column(Text, nullable=True)
    autoresponder_away_message = Column(Text, nullable=True)
    autoresponder_away_minutes = Column(Integer, default=30)

    user = relationship("User")
    group_templates = relationship("GroupTemplate", back_populates="template")

class GroupTemplate(Base):
    __tablename__ = 'group_templates'

    id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey('account_templates.id'), nullable=False)
    group_id = Column(String, nullable=False)
    group_name = Column(String, nullable=True)

    custom_message = Column(Text, nullable=True)
    custom_photo = Column(LargeBinary, nullable=True)
    custom_gif = Column(LargeBinary, nullable=True)
    custom_video = Column(LargeBinary, nullable=True)
    custom_interval = Column(Integer, nullable=True)
    is_enabled = Column(Boolean, default=True)

    template = relationship("AccountTemplate", back_populates="group_templates")

class SuperGroup(Base):
    __tablename__ = 'super_groups'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    base_group_id = Column(String, nullable=False)
    base_group_name = Column(String, nullable=True)
    topic_name = Column(String, nullable=False)
    topic_id = Column(String, nullable=True)

    custom_message = Column(Text, nullable=True)
    custom_photo = Column(LargeBinary, nullable=True)
    custom_gif = Column(LargeBinary, nullable=True)
    custom_video = Column(LargeBinary, nullable=True)
    custom_interval = Column(Integer, nullable=True)
    escrow_username = Column(String(255), nullable=True)

    media_blocked = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)

    slowmode_seconds = Column(Integer, default=0)
    slowmode_minutes = Column(Integer, default=0)

    last_message_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account")

class SelectedTopics(Base):
    __tablename__ = 'selected_topics'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    group_id = Column(String, nullable=False)
    group_name = Column(String, nullable=True)
    topic_id = Column(String, nullable=False)
    topic_name = Column(String, nullable=True)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account")

class ReferralLink(Base):
    __tablename__ = 'referral_links'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    link_code = Column(String, unique=True, nullable=False)
    users_joined = Column(Integer, default=0)
    users_paid = Column(Integer, default=0)
    total_payments = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    referred_users = relationship("User", back_populates="referral_link", foreign_keys="User.referral_link_id")
