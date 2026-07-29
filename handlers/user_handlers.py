from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InputMediaPhoto
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums.chat_member_status import ChatMemberStatus
import configparser
from datetime import datetime

from database.database import get_user_by_telegram_id, create_user, get_user_accounts, get_all_referral_links, get_referral_link_by_id, create_referral_link, delete_referral_link
from keyboards.keyboards import (
    get_permanent_reply_keyboard, get_main_menu_keyboard, get_profile_keyboard, get_payment_methods_keyboard,
    get_payment_periods_keyboard, get_crypto_currencies_keyboard,
    get_account_management_keyboard, get_account_list_keyboard, get_no_accounts_keyboard,
    get_information_keyboard, get_back_to_main_keyboard, get_admin_keyboard, get_back_to_admin_keyboard,
    get_admin_users_keyboard, get_admin_broadcast_keyboard, get_admin_settings_keyboard,
    get_admin_promo_keyboard, get_broadcast_confirm_keyboard, get_promo_type_keyboard, get_promo_confirm_keyboard, get_promo_delete_keyboard, get_promo_delete_confirm_keyboard, get_message_editing_keyboard, get_message_edit_cancel_keyboard,
    get_proxy_keyboard, get_proxy_list_keyboard, get_proxy_info_keyboard, get_proxy_add_keyboard, get_proxy_delete_confirm_keyboard, get_prices_settings_keyboard, get_top_up_keyboard,
    get_referral_links_keyboard, get_referral_links_list_keyboard, get_referral_link_view_keyboard, get_referral_link_delete_confirm_keyboard, get_referral_links_empty_keyboard,
    get_subscription_check_keyboard
)

router = Router()

config = configparser.ConfigParser()
config.read('config.ini')

CACHED_IMAGES = {}

def get_cached_image(image_name):
    if image_name not in CACHED_IMAGES:
        CACHED_IMAGES[image_name] = FSInputFile(f"img_static/{image_name}")
    return CACHED_IMAGES[image_name]

def is_admin(telegram_id: str) -> bool:
    admin_ids = [admin_id.strip() for admin_id in config.get('SETTINGS', 'admin_ids', fallback='').split(',')]
    return telegram_id in admin_ids

def get_support_link() -> str:
    return config.get('SETTINGS', 'admin_contact_link', fallback='https://t.me/')

def get_support_username() -> str:
    link = get_support_link().rstrip('/')
    name = link.rsplit('/', 1)[-1]
    return f"@{name}" if name and '.' not in name else ""

def get_manual_link() -> str:
    return config.get('SETTINGS', 'manual_link', fallback='https://t.me/')

def get_bot_username() -> str:
    return config.get('SETTINGS', 'bot_username', fallback='').lstrip('@')

async def safe_edit_message(message, text, keyboard=None):
    try:
        if message.photo:
            return await message.edit_caption(caption=text, reply_markup=keyboard)
        else:
            return await message.edit_text(text=text, reply_markup=keyboard)
    except Exception as e:
        error_text = str(e).lower()
        if any(phrase in error_text for phrase in [
            "message is not modified",
            "exactly the same",
            "bad request: message is not modified",
            "specified new message content and reply markup are exactly the same"
        ]):
            return None
        try:
            return await message.answer(text=text, reply_markup=keyboard)
        except:
            return None

class UserStates(StatesGroup):
    waiting_for_promo = State()
    waiting_for_message = State()
    waiting_for_media = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast_text = State()
    waiting_for_broadcast_confirm = State()

    waiting_for_price_edit = State()
    waiting_for_new_price = State()
    waiting_for_bonus_edit = State()

    waiting_for_promo_code = State()
    waiting_for_promo_value = State()
    waiting_for_promo_limit = State()

    waiting_for_message_edit = State()

    waiting_for_proxy_string = State()

    waiting_for_referral_link_name = State()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    telegram_id = str(message.from_user.id)
    username = message.from_user.username

    channel_id = -1002325380229

    try:
        chat_member = await message.bot.get_chat_member(chat_id=channel_id, user_id=message.from_user.id)

        if chat_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await message.answer(
                "🔒 <b>Доступ ограничен</b>\n\n"
                "Для использования бота необходимо подписаться на наш канал.\n"
                "После подписки нажмите кнопку «Я подписался»",
                reply_markup=get_subscription_check_keyboard()
            )
            return
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")

    referrer_id = None
    referral_link_code = None

    if message.text and len(message.text.split()) > 1:
        start_param = message.text.split()[1]
        from database.database import get_referral_link_by_code
        ref_link = get_referral_link_by_code(start_param)
        if ref_link:
            referral_link_code = start_param
        else:
            referrer_id = start_param

    user = get_user_by_telegram_id(telegram_id)

    if not user:
        user = create_user(telegram_id, username, referrer_id, referral_link_code)
        welcome_message = config.get('MESSAGES', 'welcome_new_user')

        hello_image = get_cached_image("hello.png")
        await message.answer_photo(
            photo=hello_image,
            caption=welcome_message,
            reply_markup=get_permanent_reply_keyboard()
        )

    else:
        accounts = get_user_accounts(telegram_id)

        account_info = f"<b>Подключенные аккаунты:</b> {len(accounts)}"
        active_accounts = sum(1 for acc in accounts if acc.is_active)
        account_info += f"\n<b>Аккаунты в работе:</b> {active_accounts}"
        account_info += f"\n<b>Ваш баланс:</b> {user.balance} $"

        main_image = get_cached_image("main.png")
        await message.answer_photo(
            photo=main_image,
            caption=f"📊 <b>Главное меню</b>\n\n{account_info}",
            reply_markup=get_main_menu_keyboard()
        )

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()

    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для доступа к админ панели</b>")
        return

    await message.answer(
        "🔧 <b>Админ панель</b>\n\n"
        "Добро пожаловать в панель администратора!\n"
        "Выберите нужный раздел:",
        reply_markup=get_admin_keyboard()
    )

@router.message(F.text == "🏠 Главное меню")
async def main_menu_handler(message: Message, state: FSMContext):
    await state.clear()

    telegram_id = str(message.from_user.id)
    user = get_user_by_telegram_id(telegram_id)

    if not user:
        await message.answer("❌ <b>Пользователь не найден.</b> Отправьте /start для регистрации.")
        return

    accounts = get_user_accounts(telegram_id)
    account_info = f"<b>Подключенные аккаунты:</b> {len(accounts)}"
    active_accounts = sum(1 for acc in accounts if acc.is_active)
    account_info += f"\n<b>Аккаунты в работе:</b> {active_accounts}"
    account_info += f"\n<b>Ваш баланс:</b> {user.balance} $"

    main_image = get_cached_image("main.png")
    await message.answer_photo(
        photo=main_image,
        caption=f"📊 <b>Главное меню</b>\n\n{account_info}",
        reply_markup=get_main_menu_keyboard()
    )

@router.message(F.text == "💰 Пополнить баланс")
async def top_up_balance_handler(message: Message, state: FSMContext):
    await state.clear()

    telegram_id = str(message.from_user.id)
    user = get_user_by_telegram_id(telegram_id)

    if not user:
        await message.answer("❌ <b>Пользователь не найден.</b> Отправьте /start для регистрации.")
        return

    await message.answer(
        "💳 <b>Выберите способ пополнения баланса:</b>",
        reply_markup=get_payment_methods_keyboard()
    )

@router.message(F.text == "📖 Манул по использованию")
async def manual_handler(message: Message, state: FSMContext):
    await state.clear()

    manual_text = f"""
📖 <b>Манул по использованию нашего бота: </b>\n
{get_manual_link()}
"""

    await message.answer(
        manual_text,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await callback.answer("❌ Пользователь не найден.")
        return
    accounts = get_user_accounts(telegram_id)
    account_info = f"<b>Подключенные аккаунты:</b> {len(accounts)}"
    active_accounts = sum(1 for acc in accounts if acc.is_active)
    account_info += f"\n<b>Аккаунты в работе:</b> {active_accounts}"
    account_info += f"\n<b>Ваш баланс:</b> {user.balance} $"
    main_image = FSInputFile("img_static/main.png")
    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(media=main_image, caption=f"📊 <b>Главное меню</b>\n\n{account_info}", parse_mode="HTML"),
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    await safe_edit_message(
        callback.message,
        "🔧 <b>Админ панель</b>\n\n"
        "Добро пожаловать в панель администратора!\n"
        "Выберите нужный раздел:",
        get_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import User
        from datetime import datetime

        total_users = session.query(User).count()
        active_users = session.query(User).filter(User.balance > 0).count()

        today = datetime.utcnow().date()
        new_users_today = session.query(User).filter(User.created_at >= today).count()

        text = f"""
👥 <b>Управление пользователями</b>

📊 <b>Статистика:</b>
• Всего пользователей: {total_users}
• Активных пользователей: {active_users}
• Новых за сегодня: {new_users_today}

⚙️ <b>Доступные действия:</b>
• Просмотр списка пользователей
• Управление балансом
• Просмотр активности
"""

        await safe_edit_message(
            callback.message,
            text,
            get_admin_users_keyboard()
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import User, Account, Payment

        total_users = session.query(User).count()
        total_accounts = session.query(Account).count()
        active_accounts = session.query(Account).filter(Account.is_active == True).count()
        total_payments = session.query(Payment).count()

        total_revenue = session.query(Payment.amount).filter(Payment.status == 'completed').all()
        revenue_sum = sum([payment[0] for payment in total_revenue]) if total_revenue else 0

        text = f"""
📊 <b>Статистика системы</b>

👥 <b>Пользователи:</b>
• Всего: {total_users}
• Активных: {session.query(User).filter(User.balance > 0).count()}

📱 <b>Аккаунты:</b>
• Всего: {total_accounts}
• Активных: {active_accounts}

💰 <b>Платежи:</b>
• Всего транзакций: {total_payments}
• Общая выручка: {revenue_sum:.2f} $

🔄 <b>Система:</b>
• Статус: 🟢 Работает
• Версия: 1.0
"""

        await safe_edit_message(
            callback.message,
            text,
            get_back_to_admin_keyboard()
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    text = """
💬 <b>Массовая рассылка</b>

📢 <b>Функции рассылки:</b>
• Отправка сообщений всем пользователям
• Отправка сообщений активным пользователям
• Отправка сообщений пользователям с балансом

✨ <b>Поддержка HTML разметки:</b>
• <b>Жирный</b> - &lt;b&gt;текст&lt;/b&gt;
• <i>Курсив</i> - &lt;i&gt;текст&lt;/i&gt;
• <u>Подчеркнутый</u> - &lt;u&gt;текст&lt;/u&gt;
• <code>Моноширинный</code> - &lt;code&gt;текст&lt;/code&gt;

📝 <b>Выберите целевую аудиторию:</b>
"""

    await safe_edit_message(
        callback.message,
        text,
        get_admin_broadcast_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_settings")
async def admin_settings_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    text = f"""
🔧 <b>Настройки системы</b>

💰 <b>Текущие цены:</b>
• 1 день: {config.get('PRICING', 'day_1')} $
• 7 дней: {config.get('PRICING', 'day_7')} $
• 14 дней: {config.get('PRICING', 'day_14')} $
• 30 дней: {config.get('PRICING', 'day_30')} $

🎁 <b>Бонусы:</b>
• Новый пользователь: {config.get('SETTINGS', 'new_user_bonus_minutes')} минут
• Реферальный бонус: {config.get('SETTINGS', 'referral_bonus_percent')}%

⚙️ <b>Выберите что изменить:</b>
"""

    await safe_edit_message(
        callback.message,
        text,
        get_admin_settings_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_promo")
async def admin_promo_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode

        total_promos = session.query(PromoCode).count()
        active_promos = session.query(PromoCode).filter(PromoCode.is_active == True).count()
        used_promos = session.query(PromoCode).filter(PromoCode.used_count > 0).count()

        text = f"""
🎟️ <b>Управление промокодами</b>

📊 <b>Статистика:</b>
• Всего промокодов: {total_promos}
• Активных: {active_promos}
• Использованных: {used_promos}

📋 <b>Доступные функции:</b>
• Создание новых промокодов
• Просмотр активных промокодов
• Статистика использования

🆕 <b>Выберите действие:</b>
"""

        await safe_edit_message(
            callback.message,
            text,
            get_admin_promo_keyboard()
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data == "admin_proxy")
async def admin_proxy_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import get_admin_proxies, get_working_proxies

    all_proxies = get_admin_proxies()
    working_proxies = [p for p in all_proxies if p.is_working]

    text = f"""
⚙️ <b>Управление прокси</b>

📊 <b>Статистика:</b>
• Всего прокси: {len(all_proxies)}
• Рабочих: {len(working_proxies)}
• Нерабочих: {len(all_proxies) - len(working_proxies)}

⚙️ <b>Доступные действия:</b>
• Просмотр списка прокси
• Проверка работоспособности
• Добавление новых прокси
• Удаление неработающих
"""

    await safe_edit_message(
        callback.message,
        text,
        get_proxy_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "proxy_list")
async def proxy_list_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import get_admin_proxies

    proxies = get_admin_proxies()

    if not proxies:
        await safe_edit_message(
            callback.message,
            "📋 <b>Список прокси</b>\n\n❌ Прокси не найдены",
            get_proxy_keyboard()
        )
        await callback.answer()
        return

    text = f"📋 <b>Список прокси</b>\n\nВсего: {len(proxies)}"

    await safe_edit_message(
        callback.message,
        text,
        get_proxy_list_keyboard(proxies, 0)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("proxy_page_"))
async def proxy_page_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    page = int(callback.data.split("_")[-1])
    from database.database import get_admin_proxies

    proxies = get_admin_proxies()

    text = f"📋 <b>Список прокси</b>\n\nВсего: {len(proxies)}"

    await safe_edit_message(
        callback.message,
        text,
        get_proxy_list_keyboard(proxies, page)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("proxy_info_"))
async def proxy_info_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    proxy_id = int(callback.data.split("_")[-1])
    from database.database import get_proxy_by_id

    proxy = get_proxy_by_id(proxy_id)

    if not proxy:
        await callback.answer("❌ Прокси не найден")
        return

    status_emoji = "🟢" if proxy.is_working else "🔴"
    status_text = "Работает" if proxy.is_working else "Не работает"

    text = f"""
📋 <b>Информация о прокси</b>

🔗 <b>Адрес:</b> {proxy.host}:{proxy.port}
🔧 <b>Тип:</b> {proxy.proxy_type}
👤 <b>Логин:</b> {proxy.username or 'Не указан'}
🔑 <b>Пароль:</b> {'*' * len(proxy.password) if proxy.password else 'Не указан'}

📊 <b>Статус:</b> {status_emoji} {status_text}
📅 <b>Последняя проверка:</b> {proxy.last_checked.strftime('%d.%m.%Y %H:%M') if proxy.last_checked else 'Не проверялся'}
🔢 <b>Проверок:</b> {proxy.check_count}
❌ <b>Неудач:</b> {proxy.fail_count}
"""

    await safe_edit_message(
        callback.message,
        text,
        get_proxy_info_keyboard(proxy_id)
    )
    await callback.answer()

@router.callback_query(F.data == "proxy_add")
async def proxy_add_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    await state.set_state(AdminStates.waiting_for_proxy_string)

    await safe_edit_message(
        callback.message,
        "➕ <b>Добавление прокси</b>\n\n"
        "Отправьте прокси в формате:\n"
        "<code>host:port:username:password</code>\n\n"
        "📋 <b>Можно добавлять несколько прокси:</b>\n"
        "• Каждый прокси с новой строки\n"
        "• Все прокси будут проверены и добавлены\n\n"
        "Примеры:\n"
        "• <code>192.168.1.1:1080:user:pass</code>\n"
        "• <code>proxy.example.com:8080</code>\n"
        "• <code>user:pass@188.130.143.71:5501</code>\n\n"
        "Поддерживаемые форматы:\n"
        "• <code>host:port:user:pass</code>\n"
        "• <code>user:pass@host:port</code>\n"
        "• <code>host:port</code> (без авторизации)\n\n"
        "Прокси будут автоматически проверены перед добавлением.",
        get_proxy_add_keyboard()
    )
    await callback.answer()

@router.message(StateFilter(AdminStates.waiting_for_proxy_string))
async def process_proxy_string(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ Нет прав доступа")
        await state.clear()
        return

    proxy_text = message.text.strip()
    proxy_lines = [line.strip() for line in proxy_text.split('\n') if line.strip()]

    from utils.proxy_validator import proxy_validator
    from database.database import create_proxy

    if not proxy_lines:
        await message.answer("❌ <b>Ошибка:</b> Не найдено ни одного прокси для добавления")
        return

    success_count = 0
    error_count = 0
    added_proxies = []
    errors = []

    for i, proxy_string in enumerate(proxy_lines, 1):
        try:
            is_valid, error, proxy_data = await proxy_validator.validate_proxy_string(proxy_string)

            if not is_valid:
                error_count += 1
                errors.append(f"Строка {i}: {error}")
                continue

            proxy = create_proxy(
                host=proxy_data['host'],
                port=proxy_data['port'],
                username=proxy_data.get('username'),
                password=proxy_data.get('password'),
                proxy_type=proxy_data.get('proxy_type', 'SOCKS5'),
                added_by='admin'
            )

            success_count += 1
            added_proxies.append(f"• {proxy.host}:{proxy.port}")

        except Exception as e:
            error_count += 1
            errors.append(f"Строка {i}: {str(e)}")

    total_count = len(proxy_lines)

    if success_count > 0:
        result_text = f"📊 <b>Результат добавления прокси:</b>\n\n"
        result_text += f"✅ <b>Добавлено:</b> {success_count} из {total_count}\n"

        if error_count > 0:
            result_text += f"❌ <b>Ошибок:</b> {error_count}\n"

        result_text += "\n🔗 <b>Добавленные прокси:</b>\n"

        display_proxies = added_proxies[:10]
        result_text += "\n".join(display_proxies)

        if len(added_proxies) > 10:
            result_text += f"\n... и еще {len(added_proxies) - 10} прокси"

        if errors:
            result_text += "\n\n❌ <b>Ошибки:</b>\n"
            display_errors = errors[:5]
            result_text += "\n".join(display_errors)

            if len(errors) > 5:
                result_text += f"\n... и еще {len(errors) - 5} ошибок"

        result_text += "\n\nВсе добавленные прокси будут автоматически проверяться каждые 30 минут."

        await message.answer(result_text, reply_markup=get_proxy_keyboard())
    else:
        result_text = f"❌ <b>Не удалось добавить ни одного прокси</b>\n\n"
        result_text += f"Проверено строк: {total_count}\n\n"
        result_text += "❌ <b>Ошибки:</b>\n"

        display_errors = errors[:10]
        result_text += "\n".join(display_errors)

        if len(errors) > 10:
            result_text += f"\n... и еще {len(errors) - 10} ошибок"

        await message.answer(result_text)
        return

    await state.clear()

@router.callback_query(F.data.regexp(r'^proxy_check_\\d+$'))
async def proxy_check_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    try:
        proxy_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("❌ Неверный ID прокси")
        return

    from database.database import get_proxy_by_id, update_proxy_status
    from utils.proxy_validator import proxy_validator

    proxy = get_proxy_by_id(proxy_id)

    if not proxy:
        await callback.answer("❌ Прокси не найден")
        return

    await safe_edit_message(
        callback.message,
        f"🔍 <b>Проверка прокси...</b>\n\n"
        f"🔗 {proxy.host}:{proxy.port}\n"
        f"⏳ Выполняется проверка..."
    )

    try:
        proxy_data = {
            'host': proxy.host,
            'port': proxy.port,
            'username': proxy.username,
            'password': proxy.password,
            'proxy_type': proxy.proxy_type
        }

        is_valid, error = await proxy_validator.validate_proxy(proxy_data)

        update_proxy_status(proxy_id, is_valid, error)

        status_emoji = "🟢" if is_valid else "🔴"
        status_text = "Работает" if is_valid else "Не работает"

        result_text = f"""
🔍 <b>Результат проверки прокси</b>

🔗 <b>Адрес:</b> {proxy.host}:{proxy.port}
📊 <b>Статус:</b> {status_emoji} {status_text}
"""

        if not is_valid:
            result_text += f"❌ <b>Ошибка:</b> {error}\n"

        result_text += f"\n📅 <b>Проверено:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"

        await safe_edit_message(
            callback.message,
            result_text,
            get_proxy_info_keyboard(proxy_id)
        )

    except Exception as e:
        await safe_edit_message(
            callback.message,
            f"❌ <b>Ошибка при проверке прокси:</b>\n{str(e)}",
            get_proxy_info_keyboard(proxy_id)
        )

@router.callback_query(F.data == "proxy_check_all")
async def proxy_check_all_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import get_admin_proxies, update_proxy_status
    from utils.proxy_validator import proxy_validator

    proxies = get_admin_proxies()

    if not proxies:
        await callback.answer("❌ Прокси не найдены")
        return

    await safe_edit_message(
        callback.message,
        f"🔍 <b>Проверка всех прокси...</b>\n\n"
        f"📊 Всего прокси: {len(proxies)}\n"
        f"⏳ Выполняется проверка..."
    )

    try:
        working_count = 0
        broken_count = 0
        broken_details = []

        for proxy in proxies:
            proxy_data = {
                'host': proxy.host,
                'port': proxy.port,
                'username': proxy.username,
                'password': proxy.password,
                'proxy_type': proxy.proxy_type
            }

            is_valid, error = await proxy_validator.validate_proxy(proxy_data)
            update_proxy_status(proxy.id, is_valid, error)

            if is_valid:
                working_count += 1
            else:
                broken_count += 1
                if error:
                    broken_details.append(f"🔗 <b>{proxy.host}:{proxy.port}</b> — {error}")
                else:
                    broken_details.append(f"🔗 <b>{proxy.host}:{proxy.port}</b> — Неизвестная ошибка")

        max_errors = 10
        broken_details_text = ""
        if broken_details:
            broken_details_text = "\n\n<b>Ошибки:</b>\n" + "\n".join(broken_details[:max_errors])
            if len(broken_details) > max_errors:
                broken_details_text += f"\n...и ещё {len(broken_details) - max_errors} прокси с ошибками."

        result_text = f"""
🔍 <b>Результат проверки всех прокси</b>

📊 <b>Статистика:</b>
• Всего проверено: {len(proxies)}
• Рабочих: {working_count} 🟢
• Нерабочих: {broken_count} 🔴
{broken_details_text}
📅 <b>Проверено:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""

        await safe_edit_message(
            callback.message,
            result_text,
            get_proxy_keyboard()
        )

    except Exception as e:
        await safe_edit_message(
            callback.message,
            f"❌ <b>Ошибка при проверке прокси:</b>\n{str(e)}",
            get_proxy_keyboard()
        )

@router.callback_query(F.data == "proxy_delete_broken")
async def proxy_delete_broken_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import get_admin_proxies, delete_proxy

    proxies = get_admin_proxies()
    broken_proxies = [p for p in proxies if not p.is_working]

    if not broken_proxies:
        await callback.answer("❌ Нерабочих прокси не найдено")
        return

    deleted_count = 0
    for proxy in broken_proxies:
        if delete_proxy(proxy.id):
            deleted_count += 1

    await safe_edit_message(
        callback.message,
        f"🗑️ <b>Удаление нерабочих прокси</b>\n\n"
        f"✅ Удалено: {deleted_count} прокси\n"
        f"📊 Всего нерабочих было: {len(broken_proxies)}",
        get_proxy_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("proxy_delete_"))
async def proxy_delete_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    try:
        proxy_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("❌ Неверный ID прокси")
        return

    from database.database import get_proxy_by_id, delete_proxy
    proxy = get_proxy_by_id(proxy_id)

    if not proxy:
        await callback.answer("❌ Прокси не найден")
        return

    if delete_proxy(proxy_id):
        await safe_edit_message(
            callback.message,
            f"✅ <b>Прокси удален</b>\n\n"
            f"🔗 <b>Адрес:</b> {proxy.host}:{proxy.port}\n"
            f"🗑️ Прокси успешно удален из базы данных.",
            get_proxy_keyboard()
        )
    else:
        await safe_edit_message(
            callback.message,
            f"❌ <b>Ошибка удаления</b>\n\n"
            f"Не удалось удалить прокси.",
            get_proxy_keyboard()
        )

    await callback.answer()

@router.callback_query(F.data == "proxy_stats")
async def proxy_stats_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import get_admin_proxies, get_working_proxies

    all_proxies = get_admin_proxies()
    working_proxies = get_working_proxies()

    total_proxies = len(all_proxies)
    working_count = len(working_proxies)
    broken_count = total_proxies - working_count

    total_checks = sum(p.check_count for p in all_proxies)
    total_fails = sum(p.fail_count for p in all_proxies)
    success_rate = ((total_checks - total_fails) / total_checks * 100) if total_checks > 0 else 0

    most_reliable = None
    if all_proxies:
        most_reliable = max(all_proxies, key=lambda p: p.check_count - p.fail_count if p.check_count > 0 else 0)

    text = f"""
📊 <b>Статистика прокси</b>

📈 <b>Общая статистика:</b>
• Всего прокси: {total_proxies}
• Рабочих: {working_count} 🟢
• Нерабочих: {broken_count} 🔴
• Процент успешности: {success_rate:.1f}%

🔍 <b>Проверки:</b>
• Всего проверок: {total_checks}
• Успешных: {total_checks - total_fails}
• Неудачных: {total_fails}
"""

    if most_reliable:
        reliable_success_rate = ((most_reliable.check_count - most_reliable.fail_count) / most_reliable.check_count * 100) if most_reliable.check_count > 0 else 0
        text += f"""
🏆 <b>Самый надежный прокси:</b>
• {most_reliable.host}:{most_reliable.port}
• Проверок: {most_reliable.check_count}
• Успешность: {reliable_success_rate:.1f}%
"""

    await safe_edit_message(
        callback.message,
        text,
        get_proxy_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_users_list")
async def admin_users_list_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import User
        users = session.query(User).order_by(User.created_at.desc()).limit(20).all()

        text = "👥 <b>Список пользователей</b> (последние 20)\n\n"

        for i, user in enumerate(users, 1):
            status = "🟢" if user.balance > 0 else "🔴"
            username = f"@{user.username}" if user.username else "Без username"
            created = user.created_at.strftime("%d.%m.%Y %H:%M")

            text += f"{i}. {status} <code>{user.telegram_id}</code>\n"
            text += f"   👤 {username}\n"
            text += f"   💰 Баланс: {user.balance:.2f} $\n"
            text += f"   📅 Регистрация: {created}\n\n"

        if not users:
            text += "📭 Пользователи не найдены"

        await safe_edit_message(
            callback.message,
            text,
            get_back_to_admin_keyboard()
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data == "admin_balance_management")
async def admin_balance_management_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    text = """
💰 <b>Управление балансом</b>

📝 <b>Для управления балансом:</b>
1. Выберите пользователя по ID
2. Укажите сумму (+ или -)

🔧 <b>Команды для разработчика:</b>
• /add_balance [user_id] [amount] - добавить
• /sub_balance [user_id] [amount] - списать
"""

    await safe_edit_message(
        callback.message,
        text,
        get_back_to_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_user_activity")
async def admin_user_activity_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import User, Account, Payment
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        today = now.date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        users_today = session.query(User).filter(User.created_at >= today).count()
        users_week = session.query(User).filter(User.created_at >= week_ago).count()
        users_month = session.query(User).filter(User.created_at >= month_ago).count()

        active_users = session.query(User).filter(User.balance > 0).count()

        accounts_today = session.query(Account).filter(Account.created_at >= today).count()
        active_accounts = session.query(Account).filter(Account.is_active == True).count()

        payments_today = session.query(Payment).filter(Payment.created_at >= today).count()
        payments_week = session.query(Payment).filter(Payment.created_at >= week_ago).count()

        text = f"""
📈 <b>Активность пользователей</b>

👥 <b>Новые пользователи:</b>
• Сегодня: {users_today}
• За неделю: {users_week}
• За месяц: {users_month}

🔥 <b>Активность:</b>
• Активных пользователей: {active_users}
• Активных аккаунтов: {active_accounts}

📱 <b>Аккаунты:</b>
• Добавлено сегодня: {accounts_today}
• Всего активных: {active_accounts}

💰 <b>Платежи:</b>
• Сегодня: {payments_today}
• За неделю: {payments_week}
"""

        await safe_edit_message(
            callback.message,
            text,
            get_back_to_admin_keyboard()
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.message(Command("add_balance"))
async def cmd_add_balance(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("❌ <b>Использование:</b> /add_balance [user_id] [amount]")
            return

        user_id = parts[1]
        amount = float(parts[2])

        from database.database import db
        session = db.get_session()
        try:
            from database.models import User
            user = session.query(User).filter(User.telegram_id == user_id).first()

            if not user:
                await message.answer(f"❌ <b>Пользователь с ID {user_id} не найден</b>")
                return

            old_balance = user.balance
            user.balance += amount
            session.commit()

            await message.answer(
                f"✅ <b>Баланс обновлен</b>\n\n"
                f"👤 Пользователь: <code>{user_id}</code>\n"
                f"💰 Было: {old_balance:.2f} $\n"
                f"💰 Стало: {user.balance:.2f} $\n"
                f"📈 Изменение: +{amount:.2f} $"
            )

        finally:
            db.close_session(session)

    except ValueError:
        await message.answer("❌ <b>Некорректная сумма</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.message(Command("sub_balance"))
async def cmd_sub_balance(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("❌ <b>Использование:</b> /sub_balance [user_id] [amount]")
            return

        user_id = parts[1]
        amount = float(parts[2])

        from database.database import db
        session = db.get_session()
        try:
            from database.models import User
            user = session.query(User).filter(User.telegram_id == user_id).first()

            if not user:
                await message.answer(f"❌ <b>Пользователь с ID {user_id} не найден</b>")
                return

            old_balance = user.balance
            user.balance -= amount
            if user.balance < 0:
                user.balance = 0
            session.commit()

            await message.answer(
                f"✅ <b>Баланс обновлен</b>\n\n"
                f"👤 Пользователь: <code>{user_id}</code>\n"
                f"💰 Было: {old_balance:.2f} $\n"
                f"💰 Стало: {user.balance:.2f} $\n"
                f"📉 Изменение: -{amount:.2f} $"
            )

        finally:
            db.close_session(session)

    except ValueError:
        await message.answer("❌ <b>Некорректная сумма</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.callback_query(F.data.in_(["broadcast_all", "broadcast_active", "broadcast_balance"]))
async def broadcast_audience_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    audience_type = callback.data.split("_")[1]

    await state.update_data(audience_type=audience_type)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import User

        if audience_type == "all":
            count = session.query(User).count()
            audience_name = "всем пользователям"
        elif audience_type == "active":
            count = session.query(User).filter(User.balance > 0).count()
            audience_name = "активным пользователям"
        elif audience_type == "balance":
            count = session.query(User).filter(User.balance > 0).count()
            audience_name = "пользователям с балансом"
        else:
            count = session.query(User).count()
            audience_name = "всем пользователям"

        text = f"""
📝 <b>Создание рассылки</b>

👥 <b>Целевая аудитория:</b> {audience_name}
📊 <b>Количество получателей:</b> {count}

✨ <b>Поддержка HTML разметки:</b>
• <b>Жирный</b> - &lt;b&gt;текст&lt;/b&gt;
• <i>Курсив</i> - &lt;i&gt;текст&lt;/i&gt;
• <u>Подчеркнутый</u> - &lt;u&gt;текст&lt;/u&gt;
• <code>Моноширинный</code> - &lt;code&gt;текст&lt;/code&gt;

📝 <b>Напишите текст для рассылки:</b>
"""

        await safe_edit_message(
            callback.message,
            text,
            get_back_to_admin_keyboard()
        )

        await state.set_state(AdminStates.waiting_for_broadcast_text)

    finally:
        db.close_session(session)

    await callback.answer()

@router.message(StateFilter(AdminStates.waiting_for_broadcast_text))
async def process_broadcast_text(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    data = await state.get_data()
    audience_type = data.get("audience_type")

    await state.update_data(message_text=message.text)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import User

        if audience_type == "all":
            count = session.query(User).count()
            audience_name = "всем пользователям"
        elif audience_type == "active":
            count = session.query(User).filter(User.balance > 0).count()
            audience_name = "активным пользователям"
        elif audience_type == "balance":
            count = session.query(User).filter(User.balance > 0).count()
            audience_name = "пользователям с балансом"
        else:
            count = session.query(User).count()
            audience_name = "всем пользователям"

        preview_text = f"""
📋 <b>Предпросмотр рассылки</b>

👥 <b>Аудитория:</b> {audience_name}
📊 <b>Получателей:</b> {count}

📝 <b>Текст сообщения:</b>
{message.text}

⚠️ <b>Подтвердите отправку:</b>
"""

        await message.answer(
            preview_text,
            reply_markup=get_broadcast_confirm_keyboard()
        )

        await state.set_state(AdminStates.waiting_for_broadcast_confirm)

    finally:
        db.close_session(session)

@router.callback_query(F.data == "broadcast_send", StateFilter(AdminStates.waiting_for_broadcast_confirm))
async def confirm_broadcast_send(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    data = await state.get_data()
    audience_type = data.get("audience_type")
    message_text = data.get("message_text")

    from database.database import db
    session = db.get_session()
    try:
        from database.models import User

        if audience_type == "all":
            users = session.query(User).all()
        elif audience_type == "active":
            users = session.query(User).filter(User.balance > 0).all()
        elif audience_type == "balance":
            users = session.query(User).filter(User.balance > 0).all()
        else:
            users = session.query(User).all()

        await callback.message.edit_text(
            f"🚀 <b>Рассылка запущена!</b>\n\n"
            f"📊 Отправляем сообщение {len(users)} пользователям...\n"
            f"⏱️ Это может занять некоторое время."
        )

        import asyncio
        from aiogram import Bot

        bot = callback.bot
        sent_count = 0
        failed_count = 0

        for user in users:
            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=message_text,
                    parse_mode="HTML"
                )
                sent_count += 1

                await asyncio.sleep(0.1)

            except Exception as e:
                failed_count += 1
                import logging
                logging.error(f"Failed to send message to {user.telegram_id}: {e}")

        await callback.message.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📤 Отправлено: {sent_count}\n"
            f"❌ Не удалось отправить: {failed_count}\n"
            f"📊 Общий успех: {(sent_count / len(users) * 100):.1f}%"
        )

    finally:
        db.close_session(session)

    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "broadcast_cancel", StateFilter(AdminStates.waiting_for_broadcast_confirm))
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ <b>Рассылка отменена</b>")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "settings_prices")
async def settings_prices_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    text = f"""
💰 <b>Настройка цен на подписку</b>

📊 <b>Текущие цены:</b>
• 1 день: {config.get('PRICING', 'day_1')} $
• 7 дней: {config.get('PRICING', 'day_7')} $
• 14 дней: {config.get('PRICING', 'day_14')} $
• 30 дней: {config.get('PRICING', 'day_30')} $

📝 <b>Выберите период для изменения цены:</b>
"""

    await safe_edit_message(
        callback.message,
        text,
        get_prices_settings_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "settings_bonuses")
async def settings_bonuses_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    text = f"""
🎁 <b>Редактирование бонусов</b>

📊 <b>Текущие бонусы:</b>
• Новый пользователь: {config.get('SETTINGS', 'new_user_bonus_minutes')} минут
• Реферальный бонус: {config.get('SETTINGS', 'referral_bonus_percent')}%
• Новый пользователь (баланс): {config.get('SETTINGS', 'new_user_balance')} $

📝 <b>Для изменения бонуса используйте команды:</b>
• <code>/set_bonus_minutes [минуты]</code> - бонус новому пользователю
• <code>/set_referral_bonus [процент]</code> - реферальный бонус
• <code>/set_new_user_balance [сумма]</code> - начальный баланс

💡 <b>Пример:</b> <code>/set_bonus_minutes 180</code>
"""

    await safe_edit_message(
        callback.message,
        text,
        get_back_to_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "settings_messages")
async def settings_messages_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    text = """
📝 <b>Редактирование сообщений</b>

📋 <b>Доступные сообщения:</b>
• Приветствие для новых пользователей
• Приветствие для существующих пользователей
• Информация о платежах
• Информация о ценах
• Информация о боте

✨ <b>Выберите сообщение для редактирования:</b>

⚠️ <b>Внимание:</b> HTML-разметка поддерживается
"""

    await safe_edit_message(
        callback.message,
        text,
        get_message_editing_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("edit_price_"))
async def edit_price_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    period = callback.data.split("_")[-1]

    period_names = {
        "1": "1 день",
        "7": "7 дней",
        "14": "14 дней",
        "30": "30 дней"
    }

    current_price = config.get('PRICING', f'day_{period}')

    text = f"""
💰 <b>Изменение цены: {period_names[period]}</b>

📊 <b>Текущая цена:</b> {current_price} $

📝 <b>Введите новую цену:</b>
Пример: <code>12.99</code>
"""

    await safe_edit_message(
        callback.message,
        text,
        get_back_to_admin_keyboard()
    )

    await state.set_state(AdminStates.waiting_for_new_price)
    await state.update_data(price_period=period)
    await callback.answer()

@router.message(AdminStates.waiting_for_new_price)
async def process_new_price(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ Нет прав доступа")
        return

    try:
        new_price = float(message.text.strip())

        if new_price <= 0:
            await message.answer("❌ Цена должна быть положительным числом")
            return

        data = await state.get_data()
        period = data.get('price_period')

        if not period:
            await message.answer("❌ Ошибка: не найден период для изменения")
            await state.clear()
            return

        config.set('PRICING', f'day_{period}', str(new_price))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        period_names = {
            "1": "1 день",
            "7": "7 дней",
            "14": "14 дней",
            "30": "30 дней"
        }

        await message.answer(f"✅ <b>Цена обновлена!</b>\n\n💰 {period_names[period]}: {new_price} $")
        await state.clear()

    except ValueError:
        await message.answer("❌ Некорректная цена. Введите число (например: 12.99)")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при обновлении цены: {e}")
        await message.answer("❌ Произошла ошибка при обновлении цены")
        await state.clear()

@router.message(Command("set_price_1"))
async def cmd_set_price_1(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ <b>Использование:</b> /set_price_1 [цена]")
            return

        price = float(parts[1])

        config.set('PRICING', 'day_1', str(price))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        await message.answer(f"✅ <b>Цена обновлена!</b>\n\n💰 1 день: {price} $")

    except ValueError:
        await message.answer("❌ <b>Некорректная цена</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.message(Command("set_price_7"))
async def cmd_set_price_7(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ <b>Использование:</b> /set_price_7 [цена]")
            return

        price = float(parts[1])

        config.set('PRICING', 'day_7', str(price))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        await message.answer(f"✅ <b>Цена обновлена!</b>\n\n💰 7 дней: {price} $")

    except ValueError:
        await message.answer("❌ <b>Некорректная цена</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.message(Command("set_price_14"))
async def cmd_set_price_14(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ <b>Использование:</b> /set_price_14 [цена]")
            return

        price = float(parts[1])

        config.set('PRICING', 'day_14', str(price))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        await message.answer(f"✅ <b>Цена обновлена!</b>\n\n💰 14 дней: {price} $")

    except ValueError:
        await message.answer("❌ <b>Некорректная цена</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.message(Command("set_price_30"))
async def cmd_set_price_30(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ <b>Использование:</b> /set_price_30 [цена]")
            return

        price = float(parts[1])

        config.set('PRICING', 'day_30', str(price))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        await message.answer(f"✅ <b>Цена обновлена!</b>\n\n💰 30 дней: {price} $")

    except ValueError:
        await message.answer("❌ <b>Некорректная цена</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.message(Command("set_bonus_minutes"))
async def cmd_set_bonus_minutes(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ <b>Использование:</b> /set_bonus_minutes [минуты]")
            return

        minutes = int(parts[1])

        config.set('SETTINGS', 'new_user_bonus_minutes', str(minutes))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        await message.answer(f"✅ <b>Бонус обновлен!</b>\n\n🎁 Новый пользователь: {minutes} минут")

    except ValueError:
        await message.answer("❌ <b>Некорректное количество минут</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.message(Command("set_referral_bonus"))
async def cmd_set_referral_bonus(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ <b>Использование:</b> /set_referral_bonus [процент]")
            return

        percent = float(parts[1])

        config.set('SETTINGS', 'referral_bonus_percent', str(percent))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        await message.answer(f"✅ <b>Бонус обновлен!</b>\n\n🎁 Реферальный бонус: {percent}%")

    except ValueError:
        await message.answer("❌ <b>Некорректный процент</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.message(Command("set_new_user_balance"))
async def cmd_set_new_user_balance(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ <b>У вас нет прав для выполнения этой команды</b>")
        return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ <b>Использование:</b> /set_new_user_balance [сумма]")
            return

        balance = float(parts[1])

        config.set('SETTINGS', 'new_user_balance', str(balance))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        await message.answer(f"✅ <b>Баланс обновлен!</b>\n\n💰 Начальный баланс: {balance} $")

    except ValueError:
        await message.answer("❌ <b>Некорректная сумма</b>")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка:</b> {str(e)}")

@router.callback_query(F.data.startswith("edit_msg_"))
async def edit_message_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    message_type = callback.data.split("edit_msg_")[1]

    message_config = {
        "welcome_new": {
            "key": "welcome_new_user",
            "name": "Приветствие для новых пользователей",
            "description": "Сообщение, которое получают новые пользователи при первом запуске бота"
        },
        "welcome_existing": {
            "key": "welcome_existing_user",
            "name": "Приветствие для существующих пользователей",
            "description": "Сообщение в главном меню для существующих пользователей"
        },
        "payment_info": {
            "key": "payment_info",
            "name": "Информация о платежах",
            "description": "Информация об оплате и условиях использования"
        },
        "pricing_info": {
            "key": "pricing_info",
            "name": "Информация о ценах",
            "description": "Список цен на подписки"
        },
        "bot_info": {
            "key": "bot_info",
            "name": "Информация о боте",
            "description": "Общая информация о возможностях бота"
        }
    }

    if message_type not in message_config:
        await callback.answer("❌ Неизвестный тип сообщения")
        return

    msg_config = message_config[message_type]
    current_message = config.get('MESSAGES', msg_config['key'])

    if msg_config['key'] in ['payment_info', 'pricing_info']:
        current_message = format_message_with_prices(current_message)

    await state.update_data(message_type=message_type)

    text = f"""
📝 <b>Редактирование сообщения</b>

📋 <b>Тип:</b> {msg_config['name']}
📖 <b>Описание:</b> {msg_config['description']}

📄 <b>Текущее сообщение:</b>
{current_message}

📝 <b>Отправьте новый текст сообщения:</b>
• HTML-разметка поддерживается
• Используйте &lt;b&gt;жирный&lt;/b&gt;, &lt;i&gt;курсив&lt;/i&gt;, &lt;u&gt;подчеркнутый&lt;/u&gt;
"""

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_message_edit_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_message_edit)
    await callback.answer()

@router.message(StateFilter(AdminStates.waiting_for_message_edit))
async def process_message_edit(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    data = await state.get_data()
    message_type = data.get("message_type")

    if not message_type:
        await message.answer("❌ Ошибка: тип сообщения не найден")
        await state.clear()
        return

    new_text = message.text.strip()

    message_config = {
        "welcome_new": {
            "key": "welcome_new_user",
            "name": "Приветствие для новых пользователей"
        },
        "welcome_existing": {
            "key": "welcome_existing_user",
            "name": "Приветствие для существующих пользователей"
        },
        "payment_info": {
            "key": "payment_info",
            "name": "Информация о платежах"
        },
        "pricing_info": {
            "key": "pricing_info",
            "name": "Информация о ценах"
        },
        "bot_info": {
            "key": "bot_info",
            "name": "Информация о боте"
        }
    }

    if message_type not in message_config:
        await message.answer("❌ Неизвестный тип сообщения")
        await state.clear()
        return

    msg_config = message_config[message_type]

    try:
        config.set('MESSAGES', msg_config['key'], new_text)
        with open('config.ini', 'w') as configfile:
            config.write(configfile)

        success_text = f"""
✅ <b>Сообщение обновлено!</b>

📋 <b>Тип:</b> {msg_config['name']}

📄 <b>Новый текст:</b>
{new_text}

🔄 <b>Изменения вступили в силу</b>
"""

        await message.answer(
            success_text,
            reply_markup=get_back_to_admin_keyboard(),
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"❌ <b>Ошибка при сохранении:</b> {str(e)}")

    await state.clear()

@router.message(Command("cancel"), StateFilter(AdminStates.waiting_for_message_edit))
async def cancel_message_edit(message: Message, state: FSMContext):
    await message.answer(
        "❌ <b>Редактирование сообщения отменено</b>",
        reply_markup=get_back_to_admin_keyboard()
    )
    await state.clear()

@router.callback_query(F.data == "cancel_message_edit")
async def cancel_message_edit_button(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    await safe_edit_message(
        callback.message,
        "❌ <b>Редактирование сообщения отменено</b>",
        get_message_editing_keyboard()
    )
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "create_promo")
async def create_promo_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    text = """
🆕 <b>Создание промокода</b>

📋 <b>Выберите тип промокода:</b>
• 💰 <b>Бонус к балансу</b> - добавляет деньги на баланс
• 🎁 <b>Бонус в минутах</b> - добавляет бонусные минуты
• 📈 <b>% к пополнению</b> - процентный бонус при пополнении

📝 <b>Что нужно будет указать:</b>
1. Код промокода
2. Размер бонуса (для % - от 1 до 100)
3. Лимит использования
"""

    await safe_edit_message(
        callback.message,
        text,
        get_promo_type_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("promo_type_"))
async def promo_type_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    callback_parts = callback.data.split("_")
    if len(callback_parts) >= 4 and callback_parts[2] == "topup":
        promo_type = "topup_bonus"
    else:
        promo_type = callback_parts[2]

    await state.update_data(promo_type=promo_type)

    if promo_type == "balance":
        type_name = "бонус к балансу"
        unit = "$"
    elif promo_type == "minutes":
        type_name = "бонус в минутах"
        unit = "минут"
    elif promo_type == "topup_bonus":
        type_name = "процентный бонус к пополнению"
        unit = "%"
    else:
        type_name = "неизвестный тип"
        unit = ""

    text = f"""
🆕 <b>Создание промокода</b>

📋 <b>Тип:</b> {type_name}

📝 <b>Напишите код промокода:</b>
• Только латинские буквы и цифры
• Длина: 4-20 символов
• Пример: BONUS100, GIFT50, PROMO2024

💡 <b>Совет:</b> Используйте понятные коды
"""

    await safe_edit_message(
        callback.message,
        text,
        get_back_to_admin_keyboard()
    )

    await state.set_state(AdminStates.waiting_for_promo_code)
    await callback.answer()

@router.message(StateFilter(AdminStates.waiting_for_promo_code))
async def process_promo_code(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    code = message.text.strip().upper()

    if len(code) < 4 or len(code) > 20:
        await message.answer("❌ <b>Код должен быть от 4 до 20 символов</b>")
        return

    if not code.isalnum():
        await message.answer("❌ <b>Код должен содержать только буквы и цифры</b>")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode

        existing_code = session.query(PromoCode).filter(PromoCode.code == code).first()
        if existing_code:
            await message.answer(f"❌ <b>Промокод {code} уже существует</b>")
            return

        await state.update_data(promo_code=code)

        data = await state.get_data()
        promo_type = data.get("promo_type")

        if promo_type == "balance":
            unit = "$"
            example = "10.50"
            type_name = "бонус к балансу"
        elif promo_type == "minutes":
            unit = "минут"
            example = "120"
            type_name = "бонус в минутах"
        elif promo_type == "topup_bonus":
            unit = "%"
            example = "25"
            type_name = "процентный бонус к пополнению"
        else:
            unit = ""
            example = "0"
            type_name = "неизвестный тип"

        additional_info = ""
        if promo_type == "balance":
            additional_info = " (и точка для долларов)"
        elif promo_type == "topup_bonus":
            additional_info = "\n• Для процентов: от 1 до 100"

        text = f"""
🆕 <b>Создание промокода</b>

📋 <b>Код:</b> <code>{code}</code>
🎯 <b>Тип:</b> {type_name}

📝 <b>Напишите размер бонуса:</b>
• Только цифры{additional_info}
• Пример: {example}
• Единица измерения: {unit}
"""

        await message.answer(text)
        await state.set_state(AdminStates.waiting_for_promo_value)

    finally:
        db.close_session(session)

@router.message(StateFilter(AdminStates.waiting_for_promo_value))
async def process_promo_value(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    try:
        value = float(message.text.strip())

        data = await state.get_data()
        promo_type = data.get("promo_type")

        if value <= 0:
            await message.answer("❌ <b>Значение должно быть больше 0</b>")
            return

        if promo_type == "topup_bonus" and value > 100:
            await message.answer("❌ <b>Процентный бонус не может быть больше 100%</b>")
            return

        await state.update_data(promo_value=value)

        if promo_type == "balance":
            unit = "$"
            type_name = "бонус к балансу"
        elif promo_type == "minutes":
            unit = "минут"
            type_name = "бонус в минутах"
        elif promo_type == "topup_bonus":
            unit = "%"
            type_name = "процентный бонус к пополнению"
        else:
            unit = ""
            type_name = "неизвестный тип"

        text = f"""
🆕 <b>Создание промокода</b>

📋 <b>Код:</b> <code>{data.get('promo_code')}</code>
🎯 <b>Тип:</b> {type_name}
💰 <b>Размер:</b> {value} {unit}

📝 <b>Напишите лимит использования:</b>
• Сколько раз можно использовать
• 0 - без ограничений
• Пример: 100, 50, 10
"""

        await message.answer(text)
        await state.set_state(AdminStates.waiting_for_promo_limit)

    except ValueError:
        await message.answer("❌ <b>Некорректное значение</b>")

@router.message(StateFilter(AdminStates.waiting_for_promo_limit))
async def process_promo_limit(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    try:
        limit = int(message.text.strip())

        if limit < 0:
            await message.answer("❌ <b>Лимит не может быть отрицательным</b>")
            return

        await state.update_data(promo_limit=limit)

        data = await state.get_data()
        promo_code = data.get("promo_code")
        promo_type = data.get("promo_type")
        promo_value = data.get("promo_value")

        if promo_type == "balance":
            unit = "$"
            type_name = "бонус к балансу"
        elif promo_type == "minutes":
            unit = "минут"
            type_name = "бонус в минутах"
        elif promo_type == "topup_bonus":
            unit = "%"
            type_name = "процентный бонус к пополнению"
        else:
            unit = ""
            type_name = "неизвестный тип"

        limit_text = "без ограничений" if limit == 0 else f"{limit} раз"

        text = f"""
🆕 <b>Подтверждение создания промокода</b>

📋 <b>Код:</b> <code>{promo_code}</code>
🎯 <b>Тип:</b> {type_name}
💰 <b>Размер:</b> {promo_value} {unit}
📊 <b>Лимит:</b> {limit_text}

⚠️ <b>Подтвердите создание промокода:</b>
"""

        await message.answer(
            text,
            reply_markup=get_promo_confirm_keyboard()
        )

    except ValueError:
        await message.answer("❌ <b>Некорректное значение лимита</b>")

@router.callback_query(F.data == "promo_create_confirm")
async def confirm_promo_create(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    data = await state.get_data()
    promo_code = data.get("promo_code")
    promo_type = data.get("promo_type")
    promo_value = data.get("promo_value")
    promo_limit = data.get("promo_limit")

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode

        new_promo = PromoCode(
            code=promo_code,
            type=promo_type,
            value=promo_value,
            max_uses=promo_limit if promo_limit > 0 else None,
            used_count=0,
            is_active=True
        )

        session.add(new_promo)
        session.commit()

        if promo_type == "balance":
            unit = "$"
        elif promo_type == "minutes":
            unit = "минут"
        elif promo_type == "topup_bonus":
            unit = "%"
        else:
            unit = ""
        limit_text = "без ограничений" if promo_limit == 0 else f"{promo_limit} раз"

        await callback.message.edit_text(
            f"✅ <b>Промокод создан!</b>\n\n"
            f"📋 <b>Код:</b> <code>{promo_code}</code>\n"
            f"💰 <b>Размер:</b> {promo_value} {unit}\n"
            f"📊 <b>Лимит:</b> {limit_text}\n\n"
            f"🎯 <b>Промокод активен и готов к использованию!</b>"
        )

    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Ошибка при создании промокода:</b>\n{str(e)}"
        )
    finally:
        db.close_session(session)

    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "promo_create_cancel")
async def cancel_promo_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ <b>Создание промокода отменено</b>")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "list_promos")
async def list_promos_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode

        promos = session.query(PromoCode).order_by(PromoCode.created_at.desc()).limit(20).all()

        text = "📋 <b>Список промокодов</b> (последние 20)\n\n"

        for i, promo in enumerate(promos, 1):
            status = "🟢" if promo.is_active else "🔴"
            if promo.type == "balance":
                unit = "$"
            elif promo.type == "minutes":
                unit = "мин"
            elif promo.type == "topup_bonus":
                unit = "%"
            else:
                unit = ""
            limit_text = "∞" if promo.max_uses is None else promo.max_uses

            text += f"{i}. {status} <code>{promo.code}</code>\n"
            text += f"   💰 {promo.value} {unit} | "
            text += f"📊 {promo.used_count}/{limit_text}\n\n"

        if not promos:
            text += "📭 Промокоды не найдены"

        await safe_edit_message(
            callback.message,
            text,
            get_back_to_admin_keyboard()
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data == "promo_stats")
async def promo_stats_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode

        total_promos = session.query(PromoCode).count()
        active_promos = session.query(PromoCode).filter(PromoCode.is_active == True).count()
        used_promos = session.query(PromoCode).filter(PromoCode.used_count > 0).count()

        balance_promos = session.query(PromoCode).filter(PromoCode.type == "balance").all()
        minutes_promos = session.query(PromoCode).filter(PromoCode.type == "minutes").all()
        topup_promos = session.query(PromoCode).filter(PromoCode.type == "topup_bonus").all()

        total_balance_given = sum(p.value * p.used_count for p in balance_promos)
        total_minutes_given = sum(p.value * p.used_count for p in minutes_promos)
        total_topup_bonuses = sum(p.used_count for p in topup_promos)

        text = f"""
📊 <b>Статистика промокодов</b>

📋 <b>Общая статистика:</b>
• Всего промокодов: {total_promos}
• Активных: {active_promos}
• Использованных: {used_promos}
• Неактивных: {total_promos - active_promos}

💰 <b>Выданные бонусы:</b>
• Денежные бонусы: {total_balance_given:.2f} $
• Минуты: {total_minutes_given:.0f} мин
• Процентные бонусы: {total_topup_bonuses} применений

📈 <b>Эффективность:</b>
• Коэффициент использования: {(used_promos / max(total_promos, 1) * 100):.1f}%
• Всего применений: {sum(p.used_count for p in session.query(PromoCode).all())}
"""

        await safe_edit_message(
            callback.message,
            text,
            get_back_to_admin_keyboard()
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data == "delete_promos")
async def delete_promos_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode

        promos = session.query(PromoCode).order_by(PromoCode.created_at.desc()).all()

        if not promos:
            await safe_edit_message(
                callback.message,
                "📭 <b>Промокоды для удаления не найдены</b>",
                get_back_to_admin_keyboard()
            )
        else:
            text = f"🗑️ <b>Удаление промокодов</b>\n\n"
            text += f"📋 Выберите промокод для удаления:\n"
            text += f"<i>Всего промокодов: {len(promos)}</i>"

            await safe_edit_message(
                callback.message,
                text,
                get_promo_delete_keyboard(promos)
            )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("delete_promo_"))
async def delete_promo_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    promo_id = int(callback.data.split("_")[2])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode

        promo = session.query(PromoCode).filter(PromoCode.id == promo_id).first()

        if not promo:
            await callback.answer("❌ Промокод не найден")
            return

        status = "🟢 Активный" if promo.is_active else "🔴 Неактивный"
        if promo.type == "balance":
            unit = "$"
        elif promo.type == "minutes":
            unit = "минут"
        elif promo.type == "topup_bonus":
            unit = "%"
        else:
            unit = ""
        limit_text = "без ограничений" if promo.max_uses is None else f"{promo.max_uses} раз"

        text = f"""
🗑️ <b>Подтверждение удаления промокода</b>

📋 <b>Код:</b> <code>{promo.code}</code>
📊 <b>Статус:</b> {status}
💰 <b>Размер:</b> {promo.value} {unit}
📈 <b>Лимит:</b> {limit_text}
🔄 <b>Использований:</b> {promo.used_count}
📅 <b>Создан:</b> {promo.created_at.strftime('%d.%m.%Y %H:%M')}

⚠️ <b>Внимание!</b> Это действие нельзя отменить!
"""

        await safe_edit_message(
            callback.message,
            text,
            get_promo_delete_confirm_keyboard(promo_id)
        )

    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_promo_"))
async def confirm_delete_promo_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    promo_id = int(callback.data.split("_")[3])

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode

        promo = session.query(PromoCode).filter(PromoCode.id == promo_id).first()

        if not promo:
            await callback.answer("❌ Промокод не найден")
            return

        promo_code = promo.code

        session.delete(promo)
        session.commit()

        await callback.message.edit_text(
            f"✅ <b>Промокод удален!</b>\n\n"
            f"📋 <b>Код:</b> <code>{promo_code}</code>\n\n"
            f"🗑️ <b>Промокод успешно удален из системы</b>",
            reply_markup=get_back_to_admin_keyboard()
        )

    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Ошибка при удалении промокода:</b>\n{str(e)}",
            reply_markup=get_back_to_admin_keyboard()
        )
    finally:
        db.close_session(session)

    await callback.answer()

@router.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await callback.answer("❌ Пользователь не найден.")
        return
    accounts = get_user_accounts(telegram_id)
    profile_text = f"""
👤 <b>Ваш профиль:</b>

🆔 <b>Ваш ID:</b> <code>{user.telegram_id}</code>
👤 <b>Никнейм:</b> @{user.username or '<i>Не указан</i>'}
💰 <b>Баланс:</b> {user.balance} $
📱 <b>Подключенных аккаунтов:</b> {len(accounts)}
🎯 <b>Рефералов:</b> {user.referral_count}
"""
    profile_image = FSInputFile("img_static/profile.png")
    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(media=profile_image, caption=profile_text, parse_mode="HTML"),
        reply_markup=get_profile_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "premium_mailing")
async def premium_mailing_callback(callback: CallbackQuery):
    admin_contact_link = get_support_link()

    premium_text = """🚀 <b>Премиальная рассылка</b>

✨ <b>Что это такое?</b>
Это продвинутая рассылочная услуга, где вам не нужно настраивать ничего самостоятельно.

🔥 <b>Преимущества:</b>
• Рассылка выполняется с наших качественных аккаунтов
• Не нужно подключать свои аккаунты
• Высокая скорость доставки сообщений
• Профессиональная настройка всех параметров
• Минимальный риск блокировок

📝 <b>Что нужно от вас:</b>
• Только текст сообщения для рассылки
• Список целевых групп (опционально)
• Остальное мы сделаем за вас

💵 <b>Стоимость:</b> Индивидуально, в зависимости от объема

⚡ <b>Как заказать:</b>
Нажмите кнопку ниже для связи с администратором"""

    from aiogram.types import FSInputFile, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👨‍💼 Связаться с администратором", url=admin_contact_link)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )

    mailer_image = FSInputFile("img_static/mailer.png")

    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(media=mailer_image, caption=premium_text, parse_mode="HTML"),
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data == "buy_aged_account")
async def buy_aged_account_callback(callback: CallbackQuery):
    aged_account_text = f"""💎 <b>Купить аккаунт с отлегой</b>

Мы продаем аккаунты Телеграм с отлегой!

<b>Для чего это надо?</b>
Аккаунты с отлегой от 5 лет намного меньше подвергаются блокировкам от Телеграм.

<b>За покупкой, вопросам о наличии и цене писать сюда:</b> {get_support_username()}"""

    from aiogram.types import FSInputFile, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👨‍💼 Связаться с менеджером", url=get_support_link())],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )

    mailer_image = FSInputFile("img_static/mailer.png")

    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(media=mailer_image, caption=aged_account_text, parse_mode="HTML"),
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data == "group_selection")
async def group_selection_callback(callback: CallbackQuery):
    group_selection_text = f"""📊 <b>Подбор групп для рассылки</b>

Сбор папки с целевыми чатами индивидуально под вас!

<b>Как это работает?</b>
Вы пишите нашему менеджеру о том, что хотите сбор папки с чатами.
Рассказываете менеджеру о вашем бизнесе, мы анализируем вашу целевую аудиторию.
После этого вы производите оплату, и мы начинаем сбор лучших чатов для рассылки вашего объявления.

<b>Стоимость данной услуги:</b>
<i>20 чатов - 8$</i>
<i>50 чатов - 15$</i>
<i>100 чатов - 30$</i>

<b>За покупкой, вопросам о наличии и цене писать сюда:</b> {get_support_username()}"""

    from aiogram.types import FSInputFile, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👨‍💼 Связаться с менеджером", url=get_support_link())],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ]
    )

    mailer_image = FSInputFile("img_static/mailer.png")

    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(media=mailer_image, caption=group_selection_text, parse_mode="HTML"),
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data == "my_accounts")
async def my_accounts_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        await callback.answer("❌ Пользователь не найден.")
        return
    accounts = get_user_accounts(telegram_id)
    from aiogram.types import FSInputFile, InputMediaPhoto
    if not accounts:
        await safe_edit_message(
            callback.message,
            "У вас нет подключенных аккаунтов 😔",
            get_no_accounts_keyboard()
        )
    else:
        mailer_image = FSInputFile("img_static/mailer.png")
        if not getattr(callback.message, 'photo', None):
            sent = await callback.message.answer_photo(
                photo=mailer_image,
                caption=f"📱 <b>Ваши аккаунты</b> ({len(accounts)}):",
                reply_markup=get_account_list_keyboard(accounts),
                parse_mode="HTML"
            )
            try:
                await callback.message.delete()
            except:
                pass
        else:
            await callback.bot.edit_message_media(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                media=InputMediaPhoto(media=mailer_image, caption=f"📱 <b>Ваши аккаунты</b> ({len(accounts)}):", parse_mode="HTML"),
                reply_markup=get_account_list_keyboard(accounts)
            )
    await callback.answer()

def format_message_with_prices(message_text):
    try:
        price_1 = config.get('PRICING', 'day_1', fallback='1.5')
        price_7 = config.get('PRICING', 'day_7', fallback='10')
        price_14 = config.get('PRICING', 'day_14', fallback='19')
        price_30 = config.get('PRICING', 'day_30', fallback='35')

        message_text = message_text.replace('{price_1}', price_1)
        message_text = message_text.replace('{price_7}', price_7)
        message_text = message_text.replace('{price_14}', price_14)
        message_text = message_text.replace('{price_30}', price_30)

        return message_text
    except:
        return message_text

@router.callback_query(F.data == "payment_info")
async def payment_info_callback(callback: CallbackQuery):
    payment_info = config.get('MESSAGES', 'payment_info')
    payment_info = format_message_with_prices(payment_info)
    payment_image = FSInputFile("img_static/payment.png")
    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(media=payment_image, caption=payment_info, parse_mode="HTML"),
        reply_markup=get_payment_methods_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "information")
async def information_callback(callback: CallbackQuery):
    bot_info = config.get('MESSAGES', 'bot_info')
    info_image = FSInputFile("img_static/info.png")
    await callback.bot.edit_message_media(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        media=InputMediaPhoto(media=info_image, caption=bot_info, parse_mode="HTML"),
        reply_markup=get_information_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "top_up_balance")
async def top_up_balance_callback(callback: CallbackQuery):
    await safe_edit_message(
        callback.message,
        f"💸 <b>Выберите способ пополнения:</b><i>(если нету удобного способа пополнения, напишите в поддержку: {get_support_username()})</i>",
        get_top_up_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "pay_crypto")
async def pay_crypto_callback(callback: CallbackQuery):
    await safe_edit_message(
        callback.message,
        "📅 <b>Выберите период подписки:</b>",
        get_payment_periods_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("period_"))
async def period_callback(callback: CallbackQuery, state: FSMContext):
    period_data = callback.data.split("_")
    days = int(period_data[1])
    price = float(period_data[2])

    await state.update_data(days=days, price=price)

    await safe_edit_message(
        callback.message,
        f"💰 <b>Сумма к оплате:</b> {price:.2f} USDT\n\nПосле успешной проведенной операции нажмите кнопку:\n<b>Проверить</b>",
        get_crypto_currencies_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("crypto_"))
async def crypto_callback(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("_")[1]
    data = await state.get_data()

    from services.payment_service import create_payment_invoice, payment_service

    days = data.get('days', 1)
    price = data.get('price', 1.5)
    user_id = str(callback.from_user.id)

    crypto_amount = payment_service.calculate_price_in_currency(price, currency)

    success, invoice_url = await create_payment_invoice(user_id, days, crypto_amount, currency)

    if success and invoice_url:
        from keyboards.keyboards import get_payment_check_keyboard
        payment_id = invoice_url.split('?start=')[-1] if '?start=' in invoice_url else invoice_url.split('/')[-1]

        await safe_edit_message(
            callback.message,
            f"💰 <b>Сумма к оплате:</b> <code>{crypto_amount:.6f}</code> {currency}\n"
            f"📅 <b>Период:</b> {days} дней\n\n"
            f"После успешной проведенной операции нажмите кнопку:\n<b>Проверить</b>",
            get_payment_check_keyboard(payment_id)
        )
    else:
        await safe_edit_message(
            callback.message,
            "❌ Ошибка при создании платежа. Попробуйте позже.",
            get_back_to_main_keyboard()
        )

    await callback.answer()

@router.callback_query(F.data == "show_pricing")
async def show_pricing_callback(callback: CallbackQuery):
    pricing_info = config.get('MESSAGES', 'pricing_info')
    pricing_info = format_message_with_prices(pricing_info)
    await safe_edit_message(
        callback.message,
        pricing_info,
        get_back_to_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "referral_program")
async def referral_program_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    user = get_user_by_telegram_id(telegram_id)

    if not user:
        await callback.answer("❌ Пользователь не найден.")
        return

    try:
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = get_bot_username()

    referral_link = f"https://t.me/{bot_username}?start={telegram_id}"

    referral_text = f"""
🎁 <b>Реферальная программа</b>

👥 <b>Приглашенных пользователей:</b> {user.referral_count}
💰 <b>Процент с пополнений:</b> 25%

🔗 <b>Ваша реферальная ссылка:</b>
<code>{referral_link}</code>

За каждого приглашенного пользователя вы получаете <b>25%</b> с его пополнений!
"""

    await safe_edit_message(
        callback.message,
        referral_text,
        get_back_to_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "activate_promo")
async def activate_promo_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_for_promo)
    await safe_edit_message(
        callback.message,
        "🎟️ <b>Введите промокод:</b>",
        get_back_to_main_keyboard()
    )
    await callback.answer()

@router.message(StateFilter(UserStates.waiting_for_promo))
async def process_promo(message: Message, state: FSMContext):
    promo_code = message.text.strip().upper()
    telegram_id = str(message.from_user.id)

    from database.database import db
    session = db.get_session()
    try:
        from database.models import PromoCode, User

        promo = session.query(PromoCode).filter(
            PromoCode.code == promo_code,
            PromoCode.is_active == True
        ).first()

        if not promo:
            await message.answer(
                f"❌ Промокод '<code>{promo_code}</code>' не найден или неактивен.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
            return


        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            await message.answer(
                f"❌ Промокод '<code>{promo_code}</code>' превысил лимит использований.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
            return

        user = session.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            await message.answer(
                "❌ Пользователь не найден. Отправьте /start для регистрации.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
            return

        from database.database import has_user_used_promocode, record_promocode_usage
        if has_user_used_promocode(telegram_id, promo.id):
            await message.answer(
                f"❌ Вы уже использовали промокод '<code>{promo_code}</code>'.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
            return

        if promo.type == "balance":
            user.balance += promo.value
            bonus_text = f"{promo.value} $"
            user_bonus = f"баланс увеличен на {promo.value} $"
            bonus_amount = promo.value
        elif promo.type == "minutes":
            user.bonus_minutes += int(promo.value)
            bonus_text = f"{int(promo.value)} минут"
            user_bonus = f"добавлено {int(promo.value)} бонусных минут"
            bonus_amount = promo.value
        elif promo.type == "topup_bonus":
            await message.answer(
                f"ℹ️ Промокод '<code>{promo_code}</code>' даёт {promo.value}% бонус к пополнению.\n\n"
                f"🎯 Такие промокоды применяются автоматически при пополнении баланса!\n"
                f"💡 Просто пополните баланс и получите бонус.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
            return
        else:
            await message.answer(
                f"❌ Неизвестный тип промокода.",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
            return

        promo.used_count += 1

        record_promocode_usage(telegram_id, promo.id, bonus_amount)

        session.commit()

        await message.answer(
            f"✅ <b>Промокод активирован!</b>\n\n"
            f"🎟️ <b>Код:</b> <code>{promo_code}</code>\n"
            f"💰 <b>Бонус:</b> {bonus_text}\n\n"
            f"🎉 <b>Ваш {user_bonus}</b>",
            reply_markup=get_main_menu_keyboard()
        )

    except Exception as e:
        await message.answer(
            f"❌ Произошла ошибка при активации промокода: {str(e)}",
            reply_markup=get_main_menu_keyboard()
        )
    finally:
        db.close_session(session)

    await state.clear()

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)
    channel_id = -1002325380229

    try:
        chat_member = await callback.bot.get_chat_member(chat_id=channel_id, user_id=callback.from_user.id)

        if chat_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await callback.answer("❌ Вы не подписаны на канал. Пожалуйста, подпишитесь и попробуйте снова.", show_alert=True)
            return
        else:
            username = callback.from_user.username

            referrer_id = None
            referral_link_code = None

            if hasattr(callback.message, 'text') and callback.message.text and len(callback.message.text.split()) > 1:
                start_param = callback.message.text.split()[1]
                from database.database import get_referral_link_by_code
                ref_link = get_referral_link_by_code(start_param)
                if ref_link:
                    referral_link_code = start_param
                else:
                    referrer_id = start_param

            user = get_user_by_telegram_id(telegram_id)

            if not user:
                user = create_user(telegram_id, username, referrer_id, referral_link_code)
                welcome_message = config.get('MESSAGES', 'welcome_new_user')


                hello_image = get_cached_image("hello.png")
                await callback.message.edit_media(
                    media=InputMediaPhoto(media=hello_image, caption=welcome_message)
                )

                await callback.message.answer("Выберите действие:", reply_markup=get_permanent_reply_keyboard())

            else:
                accounts = get_user_accounts(telegram_id)

                account_info = f"<b>Подключенные аккаунты:</b> {len(accounts)}"
                active_accounts = sum(1 for acc in accounts if acc.is_active)
                account_info += f"\n<b>Аккаунты в работе:</b> {active_accounts}"
                account_info += f"\n<b>Ваш баланс:</b> {user.balance} $"

                full_message = f"📊 <b>Главное меню</b>\n\n{account_info}"


                main_image = get_cached_image("main.png")
                await callback.message.edit_media(
                    media=InputMediaPhoto(media=main_image, caption=full_message),
                    reply_markup=get_main_menu_keyboard()
                )

            await callback.answer("✅ Подписка подтверждена! Добро пожаловать!")

    except Exception as e:
        await callback.answer(f"❌ Ошибка при проверке подписки: {str(e)}", show_alert=True)
        print(f"Ошибка при проверке подписки: {e}")

@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_message(
        callback.message,
        "❌ <b>Операция отменена.</b>",
        get_main_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment_callback(callback: CallbackQuery):
    payment_id = callback.data.split("_")[2]

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"=== ВЫЗВАН CHECK_PAYMENT_CALLBACK ===")
    logger.info(f"Сырые данные callback: '{callback.data}'")
    logger.info(f"Извлечённый payment_id: '{payment_id}'")
    logger.info(f"ID пользователя: {callback.from_user.id}")

    from services.payment_service import check_payment_status

    success, message, status = await check_payment_status(payment_id)

    if success:
        try:
            await callback.message.edit_caption(
                caption=message,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
        except:
            try:
                await callback.message.edit_text(
                    message,
                    reply_markup=get_main_menu_keyboard(),
                    parse_mode="HTML"
                )
            except:
                await callback.message.answer(
                    message,
                    reply_markup=get_main_menu_keyboard(),
                    parse_mode="HTML"
                )
        await callback.answer("🎉 Платеж успешно подтвержден!")
    else:
        if status == "pending":
            await callback.answer("⏳ Платеж еще не подтвержден. Попробуйте через несколько минут.", show_alert=True)
        elif status == "not_found":
            await callback.answer("❌ Платеж не найден. Убедитесь, что оплата прошла успешно.", show_alert=True)
        elif status == "already_processed":
            await callback.answer("✅ Платеж уже был обработан ранее.", show_alert=True)
        else:
            await callback.answer(f"❌ {message}", show_alert=True)

@router.callback_query(F.data == "admin_referral_links")
async def admin_referral_links_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    links = get_all_referral_links()

    text = f"""
🔗 <b>Управление реферальными ссылками</b>

📊 <b>Статистика:</b>
• Всего ссылок: {len(links)}
• Общее количество переходов: {sum(link.users_joined for link in links)}
• Пользователи с пополнениями: {sum(link.users_paid for link in links)}
• Общая сумма пополнений: {sum(link.total_payments for link in links):.2f} $

🔧 <b>Управление:</b>
Создавайте персонализированные реферальные ссылки для отслеживания эффективности разных источников трафика.
"""

    await safe_edit_message(
        callback.message,
        text,
        get_referral_links_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "referral_links_list")
async def referral_links_list_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    links = get_all_referral_links()

    if not links:
        await safe_edit_message(
            callback.message,
            "📋 <b>Список реферальных ссылок</b>\n\n❌ Реферальные ссылки не найдены",
            get_referral_links_empty_keyboard()
        )
    else:
        text = f"📋 <b>Список реферальных ссылок</b>\n\nВсего: {len(links)}"
        await safe_edit_message(
            callback.message,
            text,
            get_referral_links_list_keyboard(links, 0)
        )

    await callback.answer()

@router.callback_query(F.data.startswith("referral_links_page_"))
async def referral_links_page_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    page = int(callback.data.split("_")[-1])
    links = get_all_referral_links()

    text = f"📋 <b>Список реферальных ссылок</b>\n\nВсего: {len(links)}"

    await safe_edit_message(
        callback.message,
        text,
        get_referral_links_list_keyboard(links, page)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("referral_link_view_"))
async def referral_link_view_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    link_id = int(callback.data.split("_")[-1])
    link = get_referral_link_by_id(link_id)

    if not link:
        await callback.answer("❌ Ссылка не найдена")
        return

    try:
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username
    except:
        bot_username = get_bot_username()

    full_link = f"https://t.me/{bot_username}?start={link.link_code}"

    text = f"""
🔗 <b>Реферальная ссылка: {link.name}</b>

📋 <b>Информация:</b>
• Название: {link.name}
• Ссылка: <code>{full_link}</code>
• Создана: {link.created_at.strftime('%d.%m.%Y %H:%M')}

📊 <b>Статистика:</b>
• Переходов по ссылке: {link.users_joined}
• Пользователи с пополнениями: {link.users_paid}
• Общая сумма пополнений: {link.total_payments:.2f} $

💡 <b>Совет:</b> Используйте кнопку "Скопировать" для быстрого копирования ссылки
"""

    await safe_edit_message(
        callback.message,
        text,
        get_referral_link_view_keyboard(link_id)
    )
    await callback.answer()

@router.callback_query(F.data == "referral_link_create")
async def referral_link_create_callback(callback: CallbackQuery, state: FSMContext):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    await state.set_state(AdminStates.waiting_for_referral_link_name)

    await safe_edit_message(
        callback.message,
        "➕ <b>Создание реферальной ссылки</b>\n\n"
        "📝 <b>Введите название для ссылки:</b>\n"
        "Это поможет вам различать ссылки между собой.\n\n"
        "Примеры:\n"
        "• YouTube реклама\n"
        "• Telegram каналы\n"
        "• Партнерская программа\n"
        "• VK группы",
        get_back_to_admin_keyboard()
    )
    await callback.answer()

@router.message(StateFilter(AdminStates.waiting_for_referral_link_name))
async def process_referral_link_name(message: Message, state: FSMContext):
    telegram_id = str(message.from_user.id)

    if not is_admin(telegram_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        await state.clear()
        return

    link_name = message.text.strip()

    if len(link_name) < 2 or len(link_name) > 50:
        await message.answer("❌ <b>Название должно быть от 2 до 50 символов</b>")
        return

    try:
        referral_link = create_referral_link(link_name)

        try:
            bot_info = await message.bot.get_me()
            bot_username = bot_info.username
        except:
            bot_username = get_bot_username()

        full_link = f"https://t.me/{bot_username}?start={referral_link.link_code}"

        try:
            await message.delete()
        except:
            pass

        await message.answer(
            f"✅ <b>Реферальная ссылка создана!</b>\n\n"
            f"📋 <b>Название:</b> {referral_link.name}\n"
            f"🔗 <b>Ссылка:</b> <code>{full_link}</code>\n"
            f"🆔 <b>Код:</b> <code>{referral_link.link_code}</code>\n\n"
            f"📊 <b>Начальная статистика:</b>\n"
            f"• Переходов: 0\n"
            f"• Пополнений: 0\n"
            f"• Сумма: 0.00 $\n\n"
            f"🎯 <b>Ссылка готова к использованию!</b>",
            reply_markup=get_referral_links_keyboard()
        )

        await state.clear()

    except Exception as e:
        await message.answer(f"❌ <b>Ошибка при создании ссылки:</b>\n{str(e)}")
        await state.clear()

@router.callback_query(F.data.startswith("referral_link_delete_") & ~F.data.startswith("referral_link_delete_confirm_"))
async def referral_link_delete_callback(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)

    if not is_admin(telegram_id):
        await callback.answer("❌ Нет прав доступа")
        return

    link_id = int(callback.data.split("_")[-1])
    link = get_referral_link_by_id(link_id)

    if not link:
        await callback.answer("❌ Ссылка не найдена")
        return

    text = f"""
🗑️ <b>Подтверждение удаления</b>

📋 <b>Ссылка:</b> {link.name}
📊 <b>Статистика:</b>
• Переходов: {link.users_joined}
• Пополнений: {link.users_paid}
• Сумма: {link.total_payments:.2f} $

⚠️ <b>Внимание!</b> Это действие нельзя отменить!
Статистика по ссылке будет потеряна навсегда.
"""

    await safe_edit_message(
        callback.message,
        text,
        get_referral_link_delete_confirm_keyboard(link_id)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("referral_link_delete_confirm_"))
async def referral_link_delete_confirm_callback(callback: CallbackQuery):
    try:
        await callback.answer()

        telegram_id = str(callback.from_user.id)

        if not is_admin(telegram_id):
            await callback.message.answer("❌ Нет прав доступа")
            return

        try:
            link_id = int(callback.data.split("_")[-1])
        except Exception as e:
            await callback.message.answer("❌ Ошибка в данных ссылки")
            return

        link = get_referral_link_by_id(link_id)

        if not link:
            await callback.message.answer("❌ Ссылка не найдена")
            return

        link_name = link.name

        delete_result = delete_referral_link(link_id)

        if delete_result:
            links = get_all_referral_links()

            if not links:
                text = f"📋 <b>Список реферальных ссылок</b>\n\n✅ Ссылка '{link_name}' удалена успешно!\n\n❌ Реферальные ссылки не найдены"
                keyboard = get_referral_links_empty_keyboard()
            else:
                text = f"📋 <b>Список реферальных ссылок</b>\n\n✅ Ссылка '{link_name}' удалена успешно!\n\nВсего: {len(links)}"
                keyboard = get_referral_links_list_keyboard(links, 0)

            try:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except Exception as e:
                if "exactly the same" in str(e).lower() or "message is not modified" in str(e).lower():
                    pass
                else:
                    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            links = get_all_referral_links()
            text = f"📋 <b>Список реферальных ссылок</b>\n\n❌ Не удалось удалить ссылку '{link_name}'\n\nВсего: {len(links)}"

            try:
                await callback.message.edit_text(text, reply_markup=get_referral_links_list_keyboard(links, 0), parse_mode="HTML")
            except Exception as e:
                if "exactly the same" in str(e).lower() or "message is not modified" in str(e).lower():
                    pass
                else:
                    await callback.message.answer(text, reply_markup=get_referral_links_list_keyboard(links, 0), parse_mode="HTML")

    except Exception as e:
        print(f"Ошибка в referral_link_delete_confirm_callback: {e}")
        try:
            await callback.answer("❌ Произошла ошибка при удалении ссылки")
        except:
            pass

@router.message(StateFilter(None))
async def default_handler(message: Message):
    await message.answer(
        "❓ <b>Не понимаю эту команду.</b> Используйте кнопки меню.",
        reply_markup=get_main_menu_keyboard()
    )
