import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from database.database import db
from database.models import (
    Base, User, Account, Proxy, GroupSettings, Payment, Referral,
    PromoCode, SystemSettings, MessageLog, AutoresponderDialog,
    AccountTemplate, GroupTemplate, SuperGroup, SelectedTopics, ReferralLink
)

def create_all_tables():
    try:
        print("🔧 Создание всех таблиц в базе данных...")
        print(f"📊 Подключение к БД: {db.database_url.split('@')[1] if '@' in db.database_url else db.database_url}")

        Base.metadata.create_all(bind=db.engine)

        print("✅ Все таблицы успешно созданы!")
        print("\n📋 Созданные таблицы:")

        inspector = db.engine.dialect.inspector(db.engine)
        tables = inspector.get_table_names()

        for table in sorted(tables):
            print(f"  - {table}")

        print(f"\n🎉 Всего создано таблиц: {len(tables)}")

    except Exception as e:
        print(f"❌ Ошибка при создании таблиц: {e}")
        print(f"Тип ошибки: {type(e).__name__}")
        return False

    return True

def check_database_connection():
    try:
        print("🔍 Проверка подключения к базе данных...")

        with db.engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            print("✅ Подключение к базе данных успешно!")
            return True

    except Exception as e:
        print(f"❌ Ошибка подключения к базе данных: {e}")
        print(f"Тип ошибки: {type(e).__name__}")
        return False

def show_models_info():
    print("\n📋 Модели для создания таблиц:")
    models = [
        ("User", User),
        ("Account", Account),
        ("Proxy", Proxy),
        ("GroupSettings", GroupSettings),
        ("Payment", Payment),
        ("Referral", Referral),
        ("ReferralLink", ReferralLink),
        ("PromoCode", PromoCode),
        ("SystemSettings", SystemSettings),
        ("MessageLog", MessageLog),
        ("AutoresponderDialog", AutoresponderDialog),
        ("AccountTemplate", AccountTemplate),
        ("GroupTemplate", GroupTemplate),
        ("SuperGroup", SuperGroup),
        ("SelectedTopics", SelectedTopics)
    ]

    for name, model in models:
        print(f"  - {name}: {model.__tablename__}")

def main():
    print("🚀 Запуск создания базы данных...")
    print("=" * 50)

    show_models_info()

    if not check_database_connection():
        print("\n❌ Не удалось подключиться к базе данных!")
        print("Проверьте настройки в config.ini:")
        print("  - host")
        print("  - port")
        print("  - username")
        print("  - password")
        print("  - database")
        return

    print()

    if create_all_tables():
        print("\n🎉 База данных успешно создана!")
    else:
        print("\n❌ Ошибка при создании базы данных!")

if __name__ == "__main__":
    main()
