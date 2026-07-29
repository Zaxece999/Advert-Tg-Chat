# Advert-Tg-Chat

Telegram-бот для автоматической рассылки объявлений по группам и темам форумов. Отправка идёт от пользовательских аккаунтов через Telethon, управление — через бота на aiogram.

## Возможности

- Подключение аккаунтов по номеру телефона, поддержка 2FA и прокси
- Рассылка по группам и темам супергрупп, отдельный текст для каждой темы
- Шаблоны аккаунтов и групп
- Ротация api_id/api_hash при запросе кода авторизации
- Автоответчик на входящие сообщения
- Подписка по времени работы, оплата через CryptoBot
- Реферальная система и промокоды
- Админ-панель: пользователи, платежи, статистика, тексты сообщений

## Требования

- Python 3.11+
- PostgreSQL 13+
- Node.js — используется для разбора форматирования и кастомных эмодзи (`utils/text_formatter.js`)

## Установка

```
git clone https://github.com/Zaxece999/Advert-Tg-Chat.git
cd Advert-Tg-Chat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Настройка

Скопируйте `config.example.ini` в `config.ini` и заполните значения:

- `DATABASE` — параметры подключения к PostgreSQL
- `TELEGRAM` — токен бота от @BotFather, `api_id` и `api_hash` с my.telegram.org
- `TELEGRAM_API` — дополнительные пары `api_N_id` / `api_N_hash` для ротации, количество произвольное
- `CRYPTOBOT` — токен приложения из @CryptoBot
- `SETTINGS` — `admin_ids` через запятую, бонусы новым пользователям, `bot_username` (юзернейм бота без @, нужен для реферальных ссылок и кнопки возврата после оплаты), `admin_contact_link`, `rules_link`, `channel_link`, `manual_link`
- `PRICING` — цены подписки в долларах
- `PERFORMANCE`, `BATCH_SIZE` — лимиты параллельной отправки
- `MESSAGES` — тексты меню, поддерживают HTML и подстановки `{price_1}`, `{price_7}`, `{price_14}`, `{price_30}`

Реальный `config.ini` в репозиторий не попадает — он в `.gitignore`.

## Запуск

Создание таблиц (один раз):

```
python create_database.py
```

Запуск бота:

```
python bot.py
```

## Служебные скрипты

`check.py` показывает состояние супергрупп и выбранных тем по всем аккаунтам. С аргументом `fix` синхронизирует таблицы `SelectedTopics` и `SuperGroup`:

```
python check.py
python check.py fix
```

## Структура

```
bot.py                точка входа, инициализация бота и роутеров
create_database.py    создание таблиц
check.py              проверка и синхронизация супергрупп
config.example.ini    пример конфигурации
database/             модели SQLAlchemy и работа с БД
handlers/             обработчики команд и колбэков
keyboards/            клавиатуры
services/             рассылка, платежи, автоответчик, фоновые задачи
utils/                прокси, форматирование текста, эмодзи, ротация API
img_static/           изображения для меню
sessions/             сессии Telethon, создаются при подключении аккаунтов
```
