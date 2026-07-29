import configparser
import logging
import random
from typing import Tuple, Optional, List, Dict

logger = logging.getLogger(__name__)

class APIManager:
    def __init__(self, config_path: str = 'config.ini'):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        self.api_credentials = self._load_api_credentials()
        self.failed_apis = set()

    def _load_api_credentials(self) -> List[Dict[str, str]]:
        credentials = []

        if 'TELEGRAM_API' in self.config:
            section = self.config['TELEGRAM_API']

            api_numbers = set()
            for key in section.keys():
                if key.startswith('api_') and key.endswith('_id'):
                    api_num = key.replace('api_', '').replace('_id', '')
                    api_numbers.add(api_num)

            for api_num in sorted(api_numbers):
                id_key = f'api_{api_num}_id'
                hash_key = f'api_{api_num}_hash'

                if id_key in section and hash_key in section:
                    try:
                        api_id = int(section[id_key])
                        api_hash = section[hash_key]
                        credentials.append({
                            'api_id': api_id,
                            'api_hash': api_hash,
                            'name': f'API_{api_num}'
                        })
                        logger.info(f"Загружен API credential: {id_key} = {api_id}")
                    except ValueError as e:
                        logger.error(f"Ошибка при загрузке API {api_num}: {e}")

        logger.info(f"Всего загружено API credentials: {len(credentials)}")
        return credentials

    def get_api_credentials(self, exclude_failed: bool = True) -> Optional[Tuple[int, str, str]]:
        available_apis = []

        for cred in self.api_credentials:
            api_key = f"{cred['api_id']}_{cred['api_hash']}"
            if not exclude_failed or api_key not in self.failed_apis:
                available_apis.append(cred)

        if not available_apis:
            if exclude_failed and self.failed_apis:
                logger.warning("Все API помечены как неудачные, сбрасываем список неудач")
                self.failed_apis.clear()
                return self.get_api_credentials(exclude_failed=False)
            else:
                logger.error("Нет доступных API credentials")
                return None

        selected = random.choice(available_apis)
        logger.info(f"Выбран API: {selected['name']} (ID: {selected['api_id']})")

        return selected['api_id'], selected['api_hash'], selected['name']

    def mark_api_as_failed(self, api_id: int, api_hash: str, error: str = ""):
        api_key = f"{api_id}_{api_hash}"
        self.failed_apis.add(api_key)

        api_name = "Unknown"
        for cred in self.api_credentials:
            if cred['api_id'] == api_id and cred['api_hash'] == api_hash:
                api_name = cred['name']
                break

        logger.error(f"API {api_name} (ID: {api_id}) помечен как неудачный. Ошибка: {error}")
        logger.info(f"Всего неудачных API: {len(self.failed_apis)}")

    def reset_failed_apis(self):
        count = len(self.failed_apis)
        self.failed_apis.clear()
        logger.info(f"Сброшен список неудачных API ({count} записей)")

    def get_available_apis_count(self) -> int:
        available = 0
        for cred in self.api_credentials:
            api_key = f"{cred['api_id']}_{cred['api_hash']}"
            if api_key not in self.failed_apis:
                available += 1
        return available

    def get_total_apis_count(self) -> int:
        return len(self.api_credentials)

api_manager = APIManager()

def get_api_credentials_with_rotation() -> Optional[Tuple[int, str, str]]:
    return api_manager.get_api_credentials()

def log_code_sending(phone_number: str, api_name: str, success: bool, error: str = ""):
    if success:
        logger.info(f"✅ Код успешно отправлен на {phone_number} через {api_name}")
    else:
        logger.error(f"❌ Ошибка отправки кода на {phone_number} через {api_name}: {error}")

def mark_api_failed(api_id: int, api_hash: str, error: str = ""):
    api_manager.mark_api_as_failed(api_id, api_hash, error)
