from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

def get_permanent_reply_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Главное меню"), KeyboardButton(text="💰 Пополнить баланс")],
            [KeyboardButton(text="📖 Манул по использованию")]
        ],
        resize_keyboard=True,
        persistent=True
    )
    return keyboard

def get_main_menu_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
                InlineKeyboardButton(text="👥 Мои аккаунты", callback_data="my_accounts")
            ],
            [
                InlineKeyboardButton(text="💳 Об оплате", callback_data="payment_info"),
                InlineKeyboardButton(text="ⓘ Информация", callback_data="information")
            ],
            [InlineKeyboardButton(text="🚀 Премиальная рассылка", callback_data="premium_mailing")],
            [InlineKeyboardButton(text="💎 Купить аккаунт с отлегой", callback_data="buy_aged_account")],
            [InlineKeyboardButton(text="📊 Подбор групп для рассылки", callback_data="group_selection")]
        ]
    )
    return keyboard

def get_profile_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="top_up_balance")],
            [InlineKeyboardButton(text="🎁 Реферальная программа", callback_data="referral_program")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_payment_methods_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="top_up_balance")],
            [InlineKeyboardButton(text="🎟️ Активировать промокод", callback_data="activate_promo")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_top_up_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💸 Crypto Bot", callback_data="pay_crypto")],
            [InlineKeyboardButton(text="🎟️ Активировать промокод", callback_data="activate_promo")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="payment_methods")]
        ]
    )
    return keyboard

def get_payment_periods_keyboard():
    import configparser
    config = configparser.ConfigParser()
    config.read('config.ini')

    price_1 = config.get('PRICING', 'day_1', fallback='1.5')
    price_7 = config.get('PRICING', 'day_7', fallback='10')
    price_14 = config.get('PRICING', 'day_14', fallback='19')
    price_30 = config.get('PRICING', 'day_30', fallback='35')

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"1 день — {price_1}$", callback_data=f"period_1_{price_1}")],
            [InlineKeyboardButton(text=f"7 дней — {price_7}$", callback_data=f"period_7_{price_7}")],
            [InlineKeyboardButton(text=f"14 дней — {price_14}$", callback_data=f"period_14_{price_14}")],
            [InlineKeyboardButton(text=f"30 дней — {price_30}$", callback_data=f"period_30_{price_30}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="top_up_balance")]
        ]
    )
    return keyboard

def get_crypto_currencies_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="USDT", callback_data="crypto_USDT")],
            [InlineKeyboardButton(text="USDC", callback_data="crypto_USDC")],
            [InlineKeyboardButton(text="TRX", callback_data="crypto_TRX")],
            [InlineKeyboardButton(text="BTC", callback_data="crypto_BTC")],
            [InlineKeyboardButton(text="ETH", callback_data="crypto_ETH")],
            [InlineKeyboardButton(text="DOGE", callback_data="crypto_DOGE")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="pay_crypto")]
        ]
    )
    return keyboard

def get_account_management_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account")],
            [InlineKeyboardButton(text="📋 Мои аккаунты", callback_data="list_accounts")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_no_accounts_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_account_actions_keyboard(account_id: int, is_active: bool = False, subscription_minutes: int = 0):
    subscription_text = "💎 Продлить подписку" if subscription_minutes > 0 else "💎 Купить подписку"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="⏸️ Остановить рассылку" if is_active else "▶️ Запустить рассылку",
                callback_data=(f"stop_spam_{account_id}" if is_active else f"start_spam_{account_id}")
            )],
            [InlineKeyboardButton(text="📝 Настройки рассылки", callback_data=f"common_settings_{account_id}")],
            [InlineKeyboardButton(text="🔧 Доп. функции", callback_data=f"account_extra_functions_{account_id}")],
            [InlineKeyboardButton(text="⚙️ Настройки аккаунта", callback_data=f"account_settings_{account_id}")],
            [InlineKeyboardButton(text="👥 Настройки групп", callback_data=f"account_groups_{account_id}")],
            [InlineKeyboardButton(text=subscription_text, callback_data=f"buy_subscription_{account_id}")],
            [InlineKeyboardButton(text="🗑️ Удалить аккаунт", callback_data=f"delete_account_{account_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="list_accounts")]
        ]
    )
    return keyboard

def get_account_settings_keyboard(account_id: int, selected_groups: list = None, page: int = 0):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Настройки профиля", callback_data=f"edit_profile_{account_id}")],
            [InlineKeyboardButton(text="📝 Настройки сообщений", callback_data=f"edit_messages_{account_id}")],
            [InlineKeyboardButton(text="⏱️ Настройки времени", callback_data=f"edit_intervals_{account_id}")],
            [InlineKeyboardButton(text="🖼️ Настройки медиа", callback_data=f"edit_media_{account_id}")],
            [InlineKeyboardButton(text="�🔙 Назад", callback_data=f"account_actions_{account_id}")]
        ]
    )
    return keyboard

def get_media_types_keyboard(account_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🖼️ Фото", callback_data=f"add_photo_{account_id}")],
            [InlineKeyboardButton(text="🎬 GIF", callback_data=f"add_gif_{account_id}")],
            [InlineKeyboardButton(text="📹 Видео", callback_data=f"add_video_{account_id}")],
            [InlineKeyboardButton(text="🗑️ Удалить медиа", callback_data=f"delete_media_{account_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_settings_{account_id}")]
        ]
    )
    return keyboard

def get_information_keyboard():
    import configparser
    config = configparser.ConfigParser()
    config.read('config.ini')

    rules_link = config.get('SETTINGS', 'rules_link', fallback='https://t.me/')
    admin_link = config.get('SETTINGS', 'admin_contact_link', fallback='https://t.me/')
    manual_link = config.get('SETTINGS', 'manual_link', fallback='https://t.me/')

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💵 Прайс", callback_data="show_pricing")],
            [InlineKeyboardButton(text="📖 Мануал", url=manual_link)],
            [
                InlineKeyboardButton(text="📋 Правила", url=rules_link),
                InlineKeyboardButton(text="👨‍💼 Администрация", url=admin_link)
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_confirmation_keyboard(action: str, item_id: str = None):
    callback_data = f"confirm_{action}_{item_id}" if item_id else f"confirm_{action}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data=callback_data)],
            [InlineKeyboardButton(text="❌ Нет", callback_data="cancel")]
        ]
    )
    return keyboard

def get_back_to_main_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_account_retry_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_account_login_method_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Вход по номеру телефона", callback_data="login_by_phone")],
            [InlineKeyboardButton(text="📁 Загрузить .session файл", callback_data="login_by_session")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_code_entry_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Вход по QR", callback_data="qr_login")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )
    return keyboard

def get_qr_login_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="add_account")]
        ]
    )
    return keyboard

def get_admin_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="💬 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🔧 Настройки", callback_data="admin_settings")],
            [InlineKeyboardButton(text="🎟️ Промокоды", callback_data="admin_promo")],
            [InlineKeyboardButton(text="🔗 Реферальные ссылки", callback_data="admin_referral_links")],
            [InlineKeyboardButton(text="🌐 Прокси", callback_data="admin_proxy")]
        ]
    )
    return keyboard

def get_prices_settings_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 1 день", callback_data="edit_price_1"),
                InlineKeyboardButton(text="📅 7 дней", callback_data="edit_price_7")
            ],
            [
                InlineKeyboardButton(text="📅 14 дней", callback_data="edit_price_14"),
                InlineKeyboardButton(text="📅 30 дней", callback_data="edit_price_30")
            ],
            [InlineKeyboardButton(text="🔙 Назад к админ панели", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_back_to_admin_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад к админ панели", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_admin_users_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users_list")],
            [InlineKeyboardButton(text="💰 Управление балансом", callback_data="admin_balance_management")],
            [InlineKeyboardButton(text="📈 Просмотр активности", callback_data="admin_user_activity")],
            [InlineKeyboardButton(text="🔙 Назад к админ панели", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_admin_broadcast_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Всем пользователям", callback_data="broadcast_all")],
            [InlineKeyboardButton(text="🔥 Только активным", callback_data="broadcast_active")],
            [InlineKeyboardButton(text="💰 Только с балансом", callback_data="broadcast_balance")],
            [InlineKeyboardButton(text="🔙 Назад к админ панели", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_admin_settings_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Изменить цены", callback_data="settings_prices")],
            [InlineKeyboardButton(text="🎁 Изменить бонусы", callback_data="settings_bonuses")],
            [InlineKeyboardButton(text="📝 Изменить сообщения", callback_data="settings_messages")],
            [InlineKeyboardButton(text="🔙 Назад к админ панели", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_admin_promo_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Создать промокод", callback_data="create_promo")],
            [InlineKeyboardButton(text="📋 Список промокодов", callback_data="list_promos")],
            [InlineKeyboardButton(text="🗑️ Удалить промокоды", callback_data="delete_promos")],
            [InlineKeyboardButton(text="📊 Статистика промокодов", callback_data="promo_stats")],
            [InlineKeyboardButton(text="🔙 Назад к админ панели", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_broadcast_confirm_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_send")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")]
        ]
    )
    return keyboard

def get_promo_type_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Бонус к балансу", callback_data="promo_type_balance")],
            [InlineKeyboardButton(text="🎁 Бонус в минутах", callback_data="promo_type_minutes")],
            [InlineKeyboardButton(text="📈 % к пополнению", callback_data="promo_type_topup_bonus")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promo")]
        ]
    )
    return keyboard

def get_promo_confirm_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать", callback_data="promo_create_confirm")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="promo_create_cancel")]
        ]
    )
    return keyboard

def get_promo_delete_keyboard(promos: list):
    builder = InlineKeyboardBuilder()

    for promo in promos:
        status = "🟢" if promo.is_active else "🔴"
        if promo.type == "balance":
            unit = "$"
        elif promo.type == "minutes":
            unit = "мин"
        elif promo.type == "topup_bonus":
            unit = "%"
        else:
            unit = ""

        builder.add(InlineKeyboardButton(
            text=f"{status} {promo.code} ({promo.value}{unit})",
            callback_data=f"delete_promo_{promo.id}"
        ))

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="admin_promo"
    ))

    builder.adjust(1)
    return builder.as_markup()

def get_promo_delete_confirm_keyboard(promo_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Удалить", callback_data=f"confirm_delete_promo_{promo_id}")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="delete_promos")]
        ]
    )
    return keyboard

def get_message_editing_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👋 Приветствие новых пользователей", callback_data="edit_msg_welcome_new")],
            [InlineKeyboardButton(text="🔄 Приветствие существующих", callback_data="edit_msg_welcome_existing")],
            [InlineKeyboardButton(text="💳 Информация о платежах", callback_data="edit_msg_payment_info")],
            [InlineKeyboardButton(text="💵 Информация о ценах", callback_data="edit_msg_pricing_info")],
            [InlineKeyboardButton(text="ℹ️ Информация о боте", callback_data="edit_msg_bot_info")],
            [InlineKeyboardButton(text="🔙 Назад к админ панели", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_message_edit_cancel_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_message_edit")]
        ]
    )
    return keyboard

def get_proxy_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список прокси", callback_data="proxy_list")],
            [InlineKeyboardButton(text="➕ Добавить прокси", callback_data="proxy_add")],
            [InlineKeyboardButton(text="🔍 Проверить все", callback_data="proxy_check_all")],
            [InlineKeyboardButton(text="🗑️ Удалить нерабочие", callback_data="proxy_delete_broken")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="proxy_stats")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_proxy_list_keyboard(proxies: list, page: int = 0):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    items_per_page = 5
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_proxies = proxies[start_idx:end_idx]

    for proxy in page_proxies:
        status_emoji = "🟢" if proxy.is_working else "🔴"
        status_text = "Работает" if proxy.is_working else "Не работает"

        button_text = f"{status_emoji} {proxy.host}:{proxy.port} ({status_text})"
        if len(button_text) > 50:
            button_text = button_text[:47] + "..."

        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"proxy_info_{proxy.id}"
            )
        ])

    pagination_row = []
    if page > 0:
        pagination_row.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"proxy_page_{page-1}"
        ))

    if end_idx < len(proxies):
        pagination_row.append(InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"proxy_page_{page+1}"
        ))

    if pagination_row:
        keyboard.inline_keyboard.append(pagination_row)

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_proxy")
    ])

    return keyboard

def get_proxy_info_keyboard(proxy_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Проверить", callback_data=f"proxy_check_{proxy_id}")],
            [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"proxy_delete_{proxy_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="proxy_list")]
        ]
    )
    return keyboard

def get_proxy_delete_confirm_keyboard(proxy_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"proxy_delete_confirm_{proxy_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"proxy_info_{proxy_id}")]
        ]
    )
    return keyboard

def get_proxy_add_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_proxy")]
        ]
    )
    return keyboard

def get_groups_keyboard(groups: list, account_id: int):
    builder = InlineKeyboardBuilder()

    for group in groups:
        group_name = group.get('title', 'Неизвестная группа')[:30]
        group_id = group.get('id', 0)
        builder.add(InlineKeyboardButton(
            text=f"👥 {group_name}",
            callback_data=f"group_settings_{account_id}_{group_id}"
        ))

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"account_actions_{account_id}"
    ))

    builder.adjust(1)
    return builder.as_markup()

def get_account_list_keyboard(accounts: list):
    builder = InlineKeyboardBuilder()

    def format_minutes_short(minutes):
        if minutes <= 0:
            return "0м"

        days = minutes // (24 * 60)
        hours = (minutes % (24 * 60)) // 60
        remaining_minutes = minutes % 60

        if days > 0:
            if hours > 0:
                return f"{days}д {hours}ч"
            return f"{days}д"
        elif hours > 0:
            if remaining_minutes > 0:
                return f"{hours}ч {remaining_minutes}м"
            return f"{hours}ч"
        else:
            return f"{remaining_minutes}м"

    for account in accounts:
        status = "🟢" if account.is_active else "🔴"
        phone = account.phone_number
        minutes_formatted = format_minutes_short(account.subscription_minutes)

        builder.add(InlineKeyboardButton(
            text=f"{status} {phone} ({minutes_formatted})",
            callback_data=f"account_actions_{account.id}"
        ))

    builder.add(InlineKeyboardButton(
        text="➕ Добавить аккаунт",
        callback_data="add_account"
    ))

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="main_menu"
    ))

    builder.adjust(1)
    return builder.as_markup()

def get_payment_check_keyboard(payment_id: str):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=f"https://t.me/CryptoBot?start={payment_id}")],
            [InlineKeyboardButton(text="🔍 Проверить", callback_data=f"check_payment_{payment_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="top_up_balance")]
        ]
    )
    return keyboard

def get_subscription_periods_keyboard(account_id: int):
    import configparser
    config = configparser.ConfigParser()
    config.read('config.ini')

    price_1 = config.get('PRICING', 'day_1', fallback='1.5')
    price_7 = config.get('PRICING', 'day_7', fallback='10')
    price_14 = config.get('PRICING', 'day_14', fallback='19')
    price_30 = config.get('PRICING', 'day_30', fallback='35')

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📅 1 день - {price_1}$", callback_data=f"account_sub_1_{account_id}")],
            [InlineKeyboardButton(text=f"📅 7 дней - {price_7}$", callback_data=f"account_sub_7_{account_id}")],
            [InlineKeyboardButton(text=f"📅 14 дней - {price_14}$", callback_data=f"account_sub_14_{account_id}")],
            [InlineKeyboardButton(text=f"📅 30 дней - {price_30}$", callback_data=f"account_sub_30_{account_id}")],
            [InlineKeyboardButton(text="🎁 Ввести промокод", callback_data=f"account_promo_{account_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_actions_{account_id}")]
        ]
    )
    return keyboard

def get_insufficient_balance_keyboard(account_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="top_up_balance")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_actions_{account_id}")]
        ]
    )
    return keyboard

def get_delete_account_keyboard(account_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Да, удалить", callback_data=f"confirm_delete_{account_id}")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"account_actions_{account_id}")]
        ]
    )
    return keyboard

def get_account_problem_keyboard(account_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Авторизоваться заново", callback_data=f"reauth_account_{account_id}")],
            [InlineKeyboardButton(text="❌ Удалить аккаунт", callback_data=f"delete_account_{account_id}")],
            [InlineKeyboardButton(text="🔙 Назад к аккаунтам", callback_data="list_accounts")]
        ]
    )
    return keyboard


def get_groups_selection_keyboard_v2(groups: list, account_id: int, page: int = 0, selected_groups: list = None):
    if selected_groups is None:
        selected_groups = []

    builder = InlineKeyboardBuilder()

    items_per_page = 8
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_groups = groups[start_idx:end_idx]

    for group in page_groups:
        group_id = group.get('id', 0)
        group_title = group.get('title', 'Unknown Group')

        from utils.group_id_helper import normalize_group_id
        normalized_group_id = normalize_group_id(group_id)

        try:
            normalized_group_id_int = int(normalized_group_id)
            is_selected = (group_id in selected_groups) or (normalized_group_id_int in selected_groups)
        except ValueError:
            is_selected = group_id in selected_groups

        checkmark = "✅ " if is_selected else ""
        button_text = f"{checkmark}{group_title}"

        if len(button_text) > 30:
            button_text = button_text[:27] + "..."

        builder.add(InlineKeyboardButton(
            text=button_text,
            callback_data=f"toggle_group_v2_{account_id}_{group_id}_{page}"
        ))

    nav_buttons = []
    total_pages = (len(groups) - 1) // items_per_page + 1

    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"groups_page_v2_{account_id}_{page-1}"
        ))

    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="➡️ Далее",
            callback_data=f"groups_page_v2_{account_id}_{page+1}"
        ))

    if nav_buttons:
        builder.add(*nav_buttons)

    all_groups_selected = len(selected_groups) == len(groups) and len(groups) > 0

    if all_groups_selected:
        button_text = "❌ Убрать выбор групп"
        callback_data = f"deselect_all_groups_v2_{account_id}_{page}"
    else:
        button_text = "✅ Выбрать все группы"
        callback_data = f"select_all_groups_v2_{account_id}_{page}"

    builder.add(InlineKeyboardButton(
        text=button_text,
        callback_data=callback_data
    ))

    builder.add(InlineKeyboardButton(
        text="✨ Супер группы",
        callback_data=f"super_groups_{account_id}"
    ))

    if selected_groups:
        builder.add(InlineKeyboardButton(
            text="⚙️ Индивидуальные настройки групп",
            callback_data=f"individual_group_settings_{account_id}"
        ))

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"account_actions_{account_id}"
    ))

    group_count = len(page_groups)
    nav_count = len(nav_buttons)

    layout = [1] * group_count
    if nav_count > 0:
        layout.append(nav_count)
    layout.append(1)
    layout.append(1)
    if selected_groups:
        layout.append(1)
    layout.append(1)

    builder.adjust(*layout)
    return builder.as_markup()

def get_group_settings_keyboard(account_id: int, group_id: int, back_to_account: bool = False):
    back_callback = (
        f"individual_group_settings_{account_id}" if back_to_account
        else f"group_settings_{account_id}_{group_id}"
    )

    buttons = [
        [InlineKeyboardButton(text="📝 Сообщение", callback_data=f"group_message_{account_id}_{group_id}")],
        [InlineKeyboardButton(text="🖼️ Медиа", callback_data=f"group_media_{account_id}_{group_id}")],
        [InlineKeyboardButton(text="⏱️ Интервал", callback_data=f"group_interval_{account_id}_{group_id}")]
    ]

    from database.database import db
    session = db.get_session()
    try:
        from database.models import GroupSettings, Account
        group_settings = session.query(GroupSettings).filter(
            GroupSettings.account_id == account_id,
            GroupSettings.group_id == group_id
        ).first()

        account = session.query(Account).filter(Account.id == account_id).first()

        has_group_message = group_settings and group_settings.custom_message
        has_common_message = account and account.default_message

        if has_group_message or has_common_message:
            buttons.append([InlineKeyboardButton(text="Гарант 💯", callback_data=f"group_escrow_{account_id}_{group_id}")])
    except Exception:
        pass
    finally:
        db.close_session(session)

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard

def get_group_back_keyboard(account_id: int, group_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"group_settings_{account_id}_{group_id}")]
        ]
    )

def get_group_interval_keyboard(account_id: int, group_id: int, has_custom_interval: bool = False):
    buttons = []


    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"group_settings_{account_id}_{group_id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_individual_group_settings_keyboard(account_id: int, enabled_groups: list):
    buttons = []

    for group in enabled_groups:
        group_name = group.group_name

        if not group_name or group_name.strip() == "" or group_name == "Unknown":
            try:
                group_id_display = int(group.group_id)
                if group_id_display < 0:
                    group_name = f"Группа {abs(group_id_display)}"
                else:
                    group_name = f"Чат {group_id_display}"
            except (ValueError, TypeError):
                group_name = f"Группа {group.group_id}"


        buttons.append([InlineKeyboardButton(
            text=f"👥 {group_name}",
            callback_data=f"group_settings_{account_id}_{group.group_id}"
        )])

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_groups_{account_id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_account_profile_keyboard(account_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✏️ Имя", callback_data=f"profile_name_{account_id}"))
    builder.add(InlineKeyboardButton(text="🆔 Username", callback_data=f"profile_username_{account_id}"))
    builder.add(InlineKeyboardButton(text="📝 Биография", callback_data=f"profile_bio_{account_id}"))
    builder.add(InlineKeyboardButton(text="🖼️ Фото профиля", callback_data=f"profile_photo_{account_id}"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_actions_{account_id}"))
    builder.adjust(1)
    return builder.as_markup()

def get_slowmode_warning_keyboard(account_id, group_id, interval):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, продолжить", callback_data=f"confirm_interval_{account_id}_{group_id}_{interval}")],
            [InlineKeyboardButton(text="❌ Нет, изменить", callback_data=f"group_interval_{account_id}_{group_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"group_settings_{account_id}_{group_id}")]
        ]
    )
    return keyboard

def get_common_settings_keyboard(account_id):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Сообщение", callback_data=f"common_message_{account_id}")],
            [InlineKeyboardButton(text="🖼️ Медиа", callback_data=f"common_media_{account_id}")],
            [InlineKeyboardButton(text="⏱️ Интервал", callback_data=f"common_interval_{account_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_actions_{account_id}")]
        ]
    )
    return keyboard

def get_account_templates_keyboard(account_id: int, templates: list):
    builder = InlineKeyboardBuilder()

    for template in templates:
        builder.add(InlineKeyboardButton(
            text=f"📋 {template.name}",
            callback_data=f"apply_template_{account_id}_{template.id}"
        ))

    builder.add(InlineKeyboardButton(
        text="➕ Создать шаблон",
        callback_data=f"create_template_{account_id}"
    ))

    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_actions_{account_id}"))
    builder.adjust(1)
    return builder.as_markup()

def get_template_actions_keyboard(account_id: int, template_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Применить", callback_data=f"confirm_apply_template_{account_id}_{template_id}"))
    builder.add(InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_template_{account_id}_{template_id}"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_templates_{account_id}"))
    builder.adjust(1)
    return builder.as_markup()

def get_template_confirm_keyboard(account_id: int, template_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Да, применить", callback_data=f"final_apply_template_{account_id}_{template_id}"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data=f"apply_template_{account_id}_{template_id}"))
    builder.adjust(1)
    return builder.as_markup()

def get_account_extra_functions_keyboard(account_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Подмена кириллицы", callback_data=f"cyrillic_substitution_{account_id}")],
            [InlineKeyboardButton(text="🤖 Автоответчик", callback_data=f"autoresponder_{account_id}")],
            [InlineKeyboardButton(text="📋 Шаблоны аккаунтов", callback_data=f"account_templates_{account_id}")],
            [InlineKeyboardButton(text="🔓 Авто спам анлок", callback_data=f"auto_spam_unlock_{account_id}")],
            [InlineKeyboardButton(text="🔍 Проверить сессию", callback_data=f"check_session_{account_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"account_actions_{account_id}")]
        ]
    )
    return keyboard

def get_super_groups_main_keyboard(account_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список супер групп", callback_data=f"list_super_groups_{account_id}")],
            [InlineKeyboardButton(text="🔙 Назад к группам", callback_data=f"account_groups_{account_id}")]
        ]
    )
    return keyboard

def get_super_groups_list_keyboard(super_groups: list, account_id: int, page: int = 0):
    builder = InlineKeyboardBuilder()

    items_per_page = 8
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_super_groups = super_groups[start_idx:end_idx]

    for super_group in page_super_groups:
        status = "✅" if super_group.is_enabled else "❌"
        button_text = f"{status} {super_group.base_group_name} | {super_group.topic_name}"

        if len(button_text) > 40:
            button_text = button_text[:37] + "..."

        builder.add(InlineKeyboardButton(
            text=button_text,
            callback_data=f"super_group_settings_{account_id}_{super_group.id}"
        ))

    nav_buttons = []
    total_pages = (len(super_groups) - 1) // items_per_page + 1

    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"super_groups_page_{account_id}_{page-1}"
        ))

    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="➡️ Далее",
            callback_data=f"super_groups_page_{account_id}_{page+1}"
        ))

    if nav_buttons:
        builder.add(*nav_buttons)

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"super_groups_{account_id}"
    ))

    group_count = len(page_super_groups)
    nav_count = len(nav_buttons)

    layout = [1] * group_count
    if nav_count > 0:
        layout.append(nav_count)
    layout.append(1)
    layout.append(1)

    builder.adjust(*layout)
    return builder.as_markup()

def get_super_group_settings_keyboard(account_id: int, super_group_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Сообщение", callback_data=f"super_group_message_{account_id}_{super_group_id}")],
            [InlineKeyboardButton(text="🖼️ Медиа", callback_data=f"super_group_media_{account_id}_{super_group_id}")],
            [InlineKeyboardButton(text="⏱️ Интервал", callback_data=f"super_group_interval_{account_id}_{super_group_id}")],
            [InlineKeyboardButton(text="🔄 Вкл/Выкл", callback_data=f"toggle_super_group_{account_id}_{super_group_id}")],
            [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_super_group_{account_id}_{super_group_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"list_super_groups_{account_id}")]
        ]
    )
    return keyboard


def get_groups_with_topics_keyboard(groups_with_topics: list, account_id: int, page: int = 0):
    builder = InlineKeyboardBuilder()

    items_per_page = 5
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_groups = groups_with_topics[start_idx:end_idx]

    for group in page_groups:
        group_title = group.get('title', 'Unknown Group')
        topics = group.get('topics', [])
        has_forum = group.get('has_forum', False)

        if topics:
            button_text = f"👥 {group_title} | 📝 {len(topics)} тем"
        elif has_forum:
            button_text = f"👥 {group_title} | 📝 Форум"
        else:
            button_text = f"👥 {group_title} | ❌ Нет тем"

        if len(button_text) > 40:
            button_text = button_text[:37] + "..."

        builder.add(InlineKeyboardButton(
            text=button_text,
            callback_data=f"group_topics_{account_id}_{group['id']}_{page}"
        ))

    nav_buttons = []
    total_pages = (len(groups_with_topics) - 1) // items_per_page + 1

    if total_pages > 1:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"groups_topics_page_{account_id}_{page-1}"
            ))

        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(
                text="Далее ➡️",
                callback_data=f"groups_topics_page_{account_id}_{page+1}"
            ))

    if nav_buttons:
        builder.add(*nav_buttons)

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"super_groups_{account_id}"
    ))

    group_count = len(page_groups)
    nav_count = len(nav_buttons)

    layout = [1] * group_count
    if nav_count > 0:
        layout.append(nav_count)
    layout.append(1)

    builder.adjust(*layout)
    return builder.as_markup()

def get_topics_list_keyboard(group: dict, account_id: int, page: int = 0):
    builder = InlineKeyboardBuilder()

    topics = group.get('topics', [])
    group_title = group.get('title', 'Unknown Group')

    if not topics:
        builder.add(InlineKeyboardButton(
            text="❌ В этой группе нет тем",
            callback_data="no_action"
        ))
    else:
        items_per_page = 10
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_topics = topics[start_idx:end_idx]

        for topic in page_topics:
            topic_title = topic.get('title', 'Unknown Topic')
            topic_id = topic.get('id', 0)

            icon_emoji = ""
            if topic.get('icon_emoji_id'):
                icon_emoji = "🎨 "

            button_text = f"{icon_emoji}{topic_title}"

            if len(button_text) > 30:
                button_text = button_text[:27] + "..."

            builder.add(InlineKeyboardButton(
                text=button_text,
                callback_data=f"select_topic_{account_id}_{group['id']}_{topic_id}_{page}"
            ))

        nav_buttons = []
        total_pages = (len(topics) - 1) // items_per_page + 1

        if total_pages > 1:
            if page > 0:
                nav_buttons.append(InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=f"topics_page_{account_id}_{group['id']}_{page-1}"
                ))

            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="Далее ➡️",
                    callback_data=f"topics_page_{account_id}_{group['id']}_{page+1}"
                ))

        if nav_buttons:
            builder.add(*nav_buttons)

    builder.add(InlineKeyboardButton(
        text="🔙 Назад к группам",
        callback_data=f"account_groups_{account_id}"
    ))

    topic_count = len(topics) if topics else 1
    nav_count = len(nav_buttons) if 'nav_buttons' in locals() else 0

    layout = [1] * topic_count
    if nav_count > 0:
        layout.append(nav_count)
    layout.append(1)

    builder.adjust(*layout)
    return builder.as_markup()

def get_super_group_back_keyboard(account_id: int, super_group_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"super_group_settings_{account_id}_{super_group_id}")]
        ]
    )

def get_super_groups_topics_keyboard(groups_with_topics: list, account_id: int, page: int = 0, selected_topics: list = None):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    import logging

    logger = logging.getLogger(__name__)

    if selected_topics is None:
        selected_topics = []

    logger.info(f"Создание клавиатуры: выбрано тем: {len(selected_topics)}, страница: {page}")
    logger.info(f"Выбранные темы: {selected_topics}")
    logger.info(f"Всего групп: {len(groups_with_topics)}")
    logger.info(f"Тип selected_topics: {type(selected_topics)}")

    total_topics = sum(len(group.get('topics', [])) for group in groups_with_topics)
    logger.info(f"Общее количество тем: {total_topics}")

    builder = InlineKeyboardBuilder()

    all_topics = []
    for group in groups_with_topics:
        group_title = group['title']
        group_id = group['id']
        topics = group.get('topics', [])

        for topic in topics:
            topic_data = f"{group_id}_{topic['id']}"
            logger.info(f"Создание темы: group_id={group_id}, topic_id={topic['id']}, topic_data={topic_data}")
            logger.info(f"Тип topic['id']: {type(topic['id'])}, значение: {topic['id']}")
            all_topics.append({
                'group_title': group_title,
                'group_id': group_id,
                'topic_id': topic['id'],
                'topic_title': topic['title'],
                'topic_data': topic_data
            })

    items_per_page = 10
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_topics = all_topics[start_idx:end_idx]

    for topic in page_topics:
        is_selected = topic['topic_data'] in selected_topics
        checkbox = "✅" if is_selected else " "

        button_text = f"{checkbox} {topic['group_title']} | Тема: {topic['topic_title']}"

        if len(button_text) > 50:
            button_text = button_text[:47] + "..."

        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Тема {topic['topic_data']}: {'выбрана' if is_selected else 'не выбрана'}")
        logger.info(f"Тип topic['topic_data']: {type(topic['topic_data'])}, значение: {topic['topic_data']}")
        logger.info(f"Тип selected_topics: {type(selected_topics)}, содержимое: {selected_topics}")
        logger.info(f"Результат проверки: {topic['topic_data'] in selected_topics}")
        logger.info(f"Callback data: toggle_super_group_topic_{account_id}_{topic['topic_data']}_{page}")

        builder.add(InlineKeyboardButton(
            text=button_text,
            callback_data=f"toggle_super_group_topic_{account_id}_{topic['topic_data']}_{page}"
        ))

    nav_buttons = []
    total_pages = (len(all_topics) - 1) // items_per_page + 1

    if total_pages > 1:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"super_groups_topics_page_{account_id}_{page-1}"
            ))

        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(
                text="Далее ➡️",
                callback_data=f"super_groups_topics_page_{account_id}_{page+1}"
            ))

    if len(selected_topics) == total_topics and total_topics > 0:
        builder.add(InlineKeyboardButton(
            text="❌ Убрать выбор всех",
            callback_data=f"deselect_all_super_groups_topics_{account_id}_{page}"
        ))
    else:
        builder.add(InlineKeyboardButton(
            text="✅ Выбрать все",
            callback_data=f"select_all_super_groups_topics_{account_id}_{page}"
        ))

    if selected_topics:
        builder.add(InlineKeyboardButton(
            text="⚙️ Индивидуальные настройки тем",
            callback_data=f"individual_super_groups_topics_{account_id}"
        ))

    if nav_buttons:
        builder.add(*nav_buttons)

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"account_groups_{account_id}"
    ))

    topic_count = len(page_topics)
    nav_count = len(nav_buttons)

    layout = [1] * topic_count
    layout.append(1)

    if selected_topics:
        layout.append(1)

    if nav_count > 0:
        layout.append(nav_count)
    layout.append(1)

    builder.adjust(*layout)
    return builder.as_markup()

def get_individual_topics_menu_keyboard(account_id: int, topics_info: list):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()

    for topic_info in topics_info:
        button_text = f"⚙️ {topic_info['group_title']} | {topic_info['topic_title']}"
        if len(button_text) > 50:
            button_text = button_text[:47] + "..."

        builder.add(InlineKeyboardButton(
            text=button_text,
            callback_data=f"individual_topic_settings_{account_id}_{topic_info['topic_data']}"
        ))

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"super_groups_{account_id}"
    ))

    layout = [1] * len(topics_info)
    layout.append(1)

    builder.adjust(*layout)
    return builder.as_markup()

def get_topic_settings_keyboard(account_id: int, topic_data: str):
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()

    builder.add(InlineKeyboardButton(
        text="💬 Сообщение",
        callback_data=f"topic_message_{account_id}_{topic_data}"
    ))

    builder.add(InlineKeyboardButton(
        text="📎 Медиа",
        callback_data=f"topic_media_{account_id}_{topic_data}"
    ))

    builder.add(InlineKeyboardButton(
        text="⏱ Интервал",
        callback_data=f"topic_interval_{account_id}_{topic_data}"
    ))

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SuperGroup, Account
        group_id, topic_id = topic_data.split('_')
        group_id = int(group_id)
        topic_id = int(topic_id)

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        account = session.query(Account).filter(Account.id == account_id).first()

        has_topic_message = super_group and super_group.custom_message
        has_common_message = account and account.default_message

        if has_topic_message or has_common_message:
            builder.add(InlineKeyboardButton(
                text="Гарант",
                callback_data=f"topic_escrow_{account_id}_{topic_data}"
            ))
    except Exception:
        pass
    finally:
        db.close_session(session)

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"back_to_individual_super_groups_topics_{account_id}"
    ))

    layout = [1, 1, 1]

    from database.database import db
    session = db.get_session()
    try:
        from database.models import SuperGroup, Account
        group_id, topic_id = topic_data.split('_')
        group_id = int(group_id)
        topic_id = int(topic_id)

        super_group = session.query(SuperGroup).filter(
            SuperGroup.account_id == account_id,
            SuperGroup.base_group_id == str(group_id),
            SuperGroup.topic_id == str(topic_id)
        ).first()

        account = session.query(Account).filter(Account.id == account_id).first()

        has_topic_message = super_group and super_group.custom_message
        has_common_message = account and account.default_message

        if has_topic_message or has_common_message:
            layout.append(1)
    except Exception:
        pass
    finally:
        db.close_session(session)

    layout.append(1)
    builder.adjust(*layout)
    return builder.as_markup()

def get_referral_links_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список ссылок", callback_data="referral_links_list")],
            [InlineKeyboardButton(text="➕ Создать ссылку", callback_data="referral_link_create")],
            [InlineKeyboardButton(text="🔙 Назад к админ панели", callback_data="admin_panel")]
        ]
    )
    return keyboard

def get_referral_links_list_keyboard(links: list, page: int = 0):
    builder = InlineKeyboardBuilder()

    items_per_page = 5
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_links = links[start_idx:end_idx]

    for link in page_links:
        button_text = f"🔗 {link.name}"
        if len(button_text) > 30:
            button_text = button_text[:27] + "..."

        builder.add(InlineKeyboardButton(
            text=button_text,
            callback_data=f"referral_link_view_{link.id}"
        ))

    nav_buttons = []
    total_pages = (len(links) - 1) // items_per_page + 1

    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"referral_links_page_{page-1}"
        ))

    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"referral_links_page_{page+1}"
        ))

    if nav_buttons:
        builder.add(*nav_buttons)

    builder.add(InlineKeyboardButton(
        text="➕ Создать ссылку",
        callback_data="referral_link_create"
    ))

    builder.add(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="admin_referral_links"
    ))

    link_count = len(page_links)
    nav_count = len(nav_buttons)

    layout = [1] * link_count
    if nav_count > 0:
        layout.append(nav_count)
    layout.append(1)
    layout.append(1)

    builder.adjust(*layout)
    return builder.as_markup()

def get_referral_link_view_keyboard(link_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Удалить ссылку", callback_data=f"referral_link_delete_{link_id}")],
            [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="referral_links_list")]
        ]
    )
    return keyboard

def get_referral_link_delete_confirm_keyboard(link_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"referral_link_delete_confirm_{link_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"referral_link_view_{link_id}")]
        ]
    )
    return keyboard

def get_referral_links_empty_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать ссылку", callback_data="referral_link_create")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_referral_links")]
        ]
    )
    return keyboard

def get_subscription_check_keyboard():
    import configparser
    config = configparser.ConfigParser()
    config.read('config.ini')

    channel_link = config.get('SETTINGS', 'channel_link', fallback='https://t.me/')

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=channel_link)],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")]
        ]
    )
    return keyboard

def get_invalid_session_keyboard(account_id: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Авторизоваться заново", callback_data=f"reauth_account_{account_id}")],
            [InlineKeyboardButton(text="🔙 Назад к доп. функциям", callback_data=f"account_extra_functions_{account_id}")]
        ]
    )
    return keyboard
