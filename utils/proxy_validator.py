import aiohttp
import asyncio
from typing import Dict, Tuple, Optional
import time

class ProxyValidator:
    def __init__(self):
        self.timeout = 10
        self.test_url = "https://httpbin.org/ip"

    async def validate_proxy(self, proxy_data: Dict) -> Tuple[bool, Optional[str]]:
        proxy_type = proxy_data.get('proxy_type', 'HTTP').upper()
        if proxy_type in ['SOCKS5', 'SOCKS4']:
            return await self._validate_socks_proxy(proxy_data)
        else:
            return await self._validate_http_proxy(proxy_data)

    async def _validate_http_proxy(self, proxy_data: Dict) -> Tuple[bool, Optional[str]]:
        try:
            proxy_url = self._build_proxy_url(proxy_data)
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.get(
                    self.test_url,
                    proxy=proxy_url
                ) as response:
                    if response.status == 200:
                        return True, None
                    else:
                        return False, f"HTTP {response.status}"
        except asyncio.TimeoutError:
            return False, "Таймаут"
        except aiohttp.ClientError as e:
            return False, f"Ошибка соединения: {str(e)}"
        except Exception as e:
            return False, f"Неожиданная ошибка: {str(e)}"

    async def _validate_socks_proxy(self, proxy_data: Dict) -> Tuple[bool, Optional[str]]:
        try:
            import socks
            import socket

            proxy_type = proxy_data.get('proxy_type', 'SOCKS5').upper()
            host = proxy_data.get('host')
            port = proxy_data.get('port')
            username = proxy_data.get('username')
            password = proxy_data.get('password')

            sock = socks.socksocket()

            if proxy_type == 'SOCKS5':
                sock.set_proxy(socks.SOCKS5, host, port, username=username, password=password)
            elif proxy_type == 'SOCKS4':
                sock.set_proxy(socks.SOCKS4, host, port, username=username)
            else:
                return False, f"Неизвестный тип SOCKS: {proxy_type}"

            sock.settimeout(self.timeout)
            try:
                sock.connect(("httpbin.org", 80))
                sock.close()
                return True, None
            except Exception as e:
                sock.close()
                return False, f"Ошибка соединения через SOCKS: {str(e)}"
        except ImportError:
            return False, "Для проверки SOCKS-прокси требуется библиотека PySocks. Установите: pip install PySocks"
        except Exception as e:
            return False, f"Ошибка проверки SOCKS-прокси: {str(e)}"

    def _build_proxy_url(self, proxy_data: Dict) -> str:
        host = proxy_data.get('host')
        port = proxy_data.get('port')
        username = proxy_data.get('username')
        password = proxy_data.get('password')

        if username and password:
            auth = f"{username}:{password}@"
        else:
            auth = ""
        return f"http://{auth}{host}:{port}"

    def parse_proxy_string(self, proxy_string: str) -> Optional[Dict]:
        try:
            proxy_string = proxy_string.strip()

            if '@' in proxy_string:
                auth_part, host_part = proxy_string.split('@', 1)
                if ':' in auth_part and ':' in host_part:
                    username, password = auth_part.split(':', 1)
                    host, port = host_part.split(':', 1)
                    return {
                        'host': host,
                        'port': int(port),
                        'username': username,
                        'password': password,
                        'proxy_type': 'SOCKS5'
                    }
                elif ':' in host_part:
                    host, port = host_part.split(':', 1)
                    return {
                        'host': host,
                        'port': int(port),
                        'username': None,
                        'password': None,
                        'proxy_type': 'SOCKS5'
                    }

            parts = proxy_string.split(':')
            if len(parts) < 2:
                return None

            proxy_data = {
                'host': parts[0],
                'port': int(parts[1]),
                'username': parts[2] if len(parts) > 2 else None,
                'password': parts[3] if len(parts) > 3 else None,
                'proxy_type': 'SOCKS5'
            }
            return proxy_data

        except (ValueError, IndexError):
            return None

    async def validate_proxy_string(self, proxy_string: str) -> Tuple[bool, Optional[str], Optional[Dict]]:
        proxy_data = self.parse_proxy_string(proxy_string)
        if not proxy_data:
            return False, "Неверный формат прокси. Поддерживаемые форматы: host:port:username:password или user:pass@host:port", None
        is_valid, error = await self.validate_proxy(proxy_data)
        if not is_valid:
            return False, error, proxy_data
        try:
            import socks
            import socket
            sock = socks.socksocket()
            if proxy_data.get('proxy_type', 'SOCKS5').upper() == 'SOCKS5':
                sock.set_proxy(socks.SOCKS5, proxy_data['host'], proxy_data['port'],
                              username=proxy_data.get('username'), password=proxy_data.get('password'))
            elif proxy_data.get('proxy_type', 'SOCKS5').upper() == 'SOCKS4':
                sock.set_proxy(socks.SOCKS4, proxy_data['host'], proxy_data['port'],
                              username=proxy_data.get('username'))
            else:
                sock.set_proxy(socks.HTTP, proxy_data['host'], proxy_data['port'],
                              username=proxy_data.get('username'), password=proxy_data.get('password'))
            sock.settimeout(10)
            telegram_servers = [
                ("149.154.167.51", 443),
                ("149.154.175.50", 443),
                ("149.154.167.91", 443),
                ("149.154.167.92", 443),
                ("91.108.56.130", 443)
            ]
            telegram_working = False
            for server_ip, server_port in telegram_servers:
                try:
                    sock.connect((server_ip, server_port))
                    sock.close()
                    telegram_working = True
                    break
                except Exception:
                    continue
            if not telegram_working:
                return False, "Прокси не может подключиться к серверам Telegram", proxy_data
        except ImportError:
            pass
        except Exception:
            pass
        return True, None, proxy_data

    async def check_proxy_health(self, proxy_data: Dict) -> Dict:
        start_time = time.time()
        is_valid, error = await self.validate_proxy(proxy_data)
        response_time = time.time() - start_time
        return {
            'is_valid': is_valid,
            'error': error,
            'response_time': response_time,
            'timestamp': time.time()
        }

proxy_validator = ProxyValidator()

async def validate_proxy_for_telethon(proxy_data: Dict) -> Tuple[bool, Optional[str]]:
    try:
        is_valid, error = await proxy_validator.validate_proxy(proxy_data)
        if not is_valid:
            return False, error
        if proxy_data.get('proxy_type', '').upper() not in ['SOCKS5', 'SOCKS4', 'HTTP']:
            return False, "Неподдерживаемый тип прокси для Telethon"
        return True, None
    except Exception as e:
        return False, f"Ошибка проверки прокси для Telethon: {str(e)}"

def get_telethon_proxy_config(proxy_data: Dict) -> tuple:
    try:
        import socks
        proxy_type = proxy_data.get('proxy_type', 'SOCKS5').upper()
        host = proxy_data.get('host')
        port = proxy_data.get('port')
        username = proxy_data.get('username')
        password = proxy_data.get('password')

        if not host or not port:
            print(f"❌ Ошибка: отсутствует host или port в прокси данных: {proxy_data}")
            return None

        if proxy_type == 'SOCKS5':
            socks_type = socks.SOCKS5
        elif proxy_type == 'SOCKS4':
            socks_type = socks.SOCKS4
        elif proxy_type == 'HTTP':
            socks_type = socks.HTTP
        else:
            socks_type = socks.SOCKS5

        proxy_config = (socks_type, host, port, True, username, password)
        print(f"✅ Создана конфигурация прокси: {proxy_type} {host}:{port}")
        return proxy_config
    except ImportError as e:
        print(f"❌ Ошибка импорта socks: {e}")
        return None
    except Exception as e:
        print(f"❌ Ошибка создания конфигурации прокси: {e}")
        return None
