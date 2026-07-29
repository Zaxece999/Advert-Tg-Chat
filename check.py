import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.database import db
from database.models import Account, SuperGroup, SelectedTopics

def check_super_groups():
    session = db.get_session()
    try:
        accounts = session.query(Account).all()

        print("🔍 ПРОВЕРКА СОСТОЯНИЯ СУПЕР ГРУПП\n")

        for account in accounts:
            print(f"📱 Аккаунт: {account.phone_number} (ID: {account.id})")
            print(f"   Активен: {'✅' if account.is_active else '❌'}")
            print(f"   Подписка: {account.subscription_minutes} минут")

            selected_topics = session.query(SelectedTopics).filter(
                SelectedTopics.account_id == account.id,
                SelectedTopics.is_enabled == True
            ).all()

            print(f"   📋 Выбранные темы (SelectedTopics): {len(selected_topics)}")
            for topic in selected_topics:
                print(f"      • {topic.group_name} | {topic.topic_name} (ID: {topic.group_id}_{topic.topic_id})")

            super_groups = session.query(SuperGroup).filter(
                SuperGroup.account_id == account.id
            ).all()

            enabled_super_groups = [sg for sg in super_groups if sg.is_enabled]
            disabled_super_groups = [sg for sg in super_groups if not sg.is_enabled]

            print(f"   🏗️ Супер группы (SuperGroup):")
            print(f"      ✅ Включенные: {len(enabled_super_groups)}")
            print(f"      ❌ Отключенные: {len(disabled_super_groups)}")

            for sg in enabled_super_groups:
                has_message = "✉️" if sg.custom_message else "📝"
                print(f"         {has_message} {sg.base_group_name} | {sg.topic_name} (ID: {sg.base_group_id}_{sg.topic_id})")

            for sg in disabled_super_groups:
                has_message = "✉️" if sg.custom_message else "📝"
                print(f"         ❌ {has_message} {sg.base_group_name} | {sg.topic_name} (ID: {sg.base_group_id}_{sg.topic_id})")

            selected_topic_ids = set(f"{t.group_id}_{t.topic_id}" for t in selected_topics)
            super_group_ids = set(f"{sg.base_group_id}_{sg.topic_id}" for sg in enabled_super_groups)

            missing_in_super_groups = selected_topic_ids - super_group_ids
            extra_in_super_groups = super_group_ids - selected_topic_ids

            if missing_in_super_groups:
                print(f"   ⚠️ Темы есть в SelectedTopics, но нет в SuperGroup: {missing_in_super_groups}")

            if extra_in_super_groups:
                print(f"   ⚠️ Темы есть в SuperGroup, но нет в SelectedTopics: {extra_in_super_groups}")

            print()

    finally:
        db.close_session(session)

def fix_super_groups():
    session = db.get_session()
    try:
        accounts = session.query(Account).all()

        print("🔧 ИСПРАВЛЕНИЕ СИНХРОНИЗАЦИИ\n")

        for account in accounts:
            print(f"📱 Обработка аккаунта: {account.phone_number}")

            selected_topics = session.query(SelectedTopics).filter(
                SelectedTopics.account_id == account.id,
                SelectedTopics.is_enabled == True
            ).all()

            all_super_groups = session.query(SuperGroup).filter(
                SuperGroup.account_id == account.id
            ).all()

            selected_topic_ids = set(f"{t.group_id}_{t.topic_id}" for t in selected_topics)
            super_group_dict = {f"{sg.base_group_id}_{sg.topic_id}": sg for sg in all_super_groups}

            created_count = 0
            enabled_count = 0
            deleted_count = 0

            for topic in selected_topics:
                topic_id = f"{topic.group_id}_{topic.topic_id}"

                if topic_id not in super_group_dict:
                    super_group = SuperGroup(
                        account_id=account.id,
                        base_group_id=topic.group_id,
                        base_group_name=topic.group_name,
                        topic_name=topic.topic_name,
                        topic_id=topic.topic_id,
                        is_enabled=True
                    )
                    session.add(super_group)
                    created_count += 1
                    print(f"   ➕ Создана: {topic.group_name} | {topic.topic_name}")
                else:
                    super_group = super_group_dict[topic_id]
                    if not super_group.is_enabled:
                        super_group.is_enabled = True
                        enabled_count += 1
                        print(f"   ✅ Включена: {super_group.base_group_name} | {super_group.topic_name}")

            for topic_id, super_group in super_group_dict.items():
                if topic_id not in selected_topic_ids:
                    print(f"   🗑️ Удаляется лишняя: {super_group.base_group_name} | {super_group.topic_name}")
                    session.delete(super_group)
                    deleted_count += 1

            session.commit()
            print(f"   📊 Создано: {created_count}, Включено: {enabled_count}, Удалено: {deleted_count}")
            print()

    finally:
        db.close_session(session)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fix":
        fix_super_groups()
    else:
        check_super_groups()
        print("💡 Для исправления проблем запустите: python check.py fix")
