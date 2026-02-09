"""
Модуль для работы с API-Football
Получает данные о матчах и событиях
"""
import aiohttp
import logging
import time
from typing import List, Dict, Optional
from config import FOOTBALL_API_BASE_URL, FOOTBALL_API_KEY, LEAGUES_TO_TRACK

logger = logging.getLogger(__name__)


class FootballAPI:
    """Класс для работы с API-Football"""

    def __init__(self):
        self.base_url = FOOTBALL_API_BASE_URL
        self.headers = {
            'x-apisports-key': FOOTBALL_API_KEY
        }
        self.session: Optional[aiohttp.ClientSession] = None

        # Кэш событий матчей
        self.events_cache: Dict[int, Dict] = {}
        self.cache_duration = 15  # Кэш на 15 секунд (для Pro тарифа с 75k запросами)

        # Сохраняем ВСЕ матчи из последнего запроса (для переиспользования)
        self.all_fixtures_today = []
        self.last_fixtures_update = None

    async def init_session(self):
        """Инициализация сессии для запросов"""
        if self.session is None:
            self.session = aiohttp.ClientSession(headers=self.headers)

    async def get_fixtures_by_date(self, date: str) -> List[Dict]:
        """
        Получает ВСЕ матчи на указанную дату
        ОДИН запрос на весь день!

        Args:
            date: Дата в формате YYYY-MM-DD

        Returns:
            Список всех матчей на эту дату
        """
        all_fixtures = []

        # Один запрос для всех лиг на эту дату
        params = {
            'date': date
        }

        data = await self._make_request('fixtures', params)

        if data and 'quota_exceeded' in data:
            logger.error("❌ Квота исчерпана при запросе расписания")
            return []

        if not data or not data.get('response'):
            return []

        # Фильтруем по нашим лигам
        all_matches = data['response']

        filtered_fixtures = [
            match for match in all_matches
            if match.get('league', {}).get('id') in LEAGUES_TO_TRACK
        ]

        logger.info(f"📅 Получено {len(filtered_fixtures)} матчей на {date}")

        return filtered_fixtures

    async def close_session(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            self.session = None

    async def _make_request(self, endpoint: str, params: dict = None) -> Optional[Dict]:
        """
        ПУБЛИЧНЫЙ метод для выполнения запросов к API
        (используется аналитикой)

        Args:
            endpoint: Конечная точка API
            params: Параметры запроса

        Returns:
            JSON ответ или None
        """
        if self.session is None:
            self.session = aiohttp.ClientSession()

        url = f"{self.base_url}/{endpoint}"

        try:
            async with self.session.get(url, headers=self.headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()

                    # Проверка квоты
                    if 'errors' in data and data['errors']:
                        if 'requests limit' in str(data['errors']).lower():
                            logger.error(f"⚠️ Квота API исчерпана!")
                            return {'quota_exceeded': True}

                    return data
                else:
                    logger.error(f"❌ API error {response.status}: {await response.text()}")
                    return None

        except Exception as e:
            logger.error(f"❌ Request error: {e}")
            return None

    async def get_live_matches(self) -> List[Dict]:
        """
        Получает список текущих (живых) матчей
        ОПТИМИЗИРОВАНО: Один запрос вместо 10!
        БОНУС: Сохраняет ВСЕ матчи на день для переиспользования!

        Returns:
            Список LIVE матчей
        """
        from datetime import datetime

        # Один запрос для ВСЕХ live матчей (включая предстоящие!)
        params = {
            'live': 'all'
        }

        data = await self._make_request('fixtures', params)

        if data and 'quota_exceeded' in data:
            return [{'quota_exceeded': True}]

        if not data or not data.get('response'):
            return []

        # СОХРАНЯЕМ ВСЕ матчи (live + предстоящие на день)
        all_matches = data['response']

        # Фильтруем по нашим лигам
        filtered_all = [
            match for match in all_matches
            if match.get('league', {}).get('id') in LEAGUES_TO_TRACK
        ]

        # НОВОЕ: Сохраняем ВСЕ матчи на день для переиспользования
        # Это позволяет показывать расписание в /start БЕЗ дополнительных запросов!
        self.all_fixtures_today = filtered_all
        self.last_fixtures_update = datetime.now()

        # Фильтруем только LIVE для возврата
        # Статусы live матчей: 1H, 2H, HT, ET, BT, P, LIVE
        live_matches = [
            match for match in filtered_all
            if match.get('fixture', {}).get('status', {}).get('short') in ['1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE']
        ]

        logger.info(
            f"⚽ Найдено {len(live_matches)} live матчей и {len(filtered_all)} всего на день "
            f"(из них {len(filtered_all) - len(live_matches)} предстоящих)"
        )

        return live_matches

    def get_all_fixtures_today(self) -> List[Dict]:
        """
        Возвращает ВСЕ матчи на день из последнего запроса
        БЕЗ дополнительных запросов к API!

        Данные обновляются автоматически каждые 30 секунд 
        глобальным циклом проверки.

        Returns:
            Список всех матчей на день (live + предстоящие)
        """
        if not self.all_fixtures_today:
            logger.warning("⚠️ Нет данных о матчах. Возможно глобальный цикл ещё не запущен.")
            return []

        logger.info(f"💾 Возвращаем {len(self.all_fixtures_today)} матчей из кэша (БЕЗ запроса к API)")

        return self.all_fixtures_today

    # Метод для получения статистики
    async def get_match_statistics(self, fixture_id: int) -> Optional[Dict]:
        """
        Получает статистику матча

        Args:
            fixture_id: ID матча

        Returns:
            Статистика или None
        """
        params = {'fixture': fixture_id}
        data = await self._make_request('fixtures/statistics', params)

        if data and 'quota_exceeded' in data:
            return None

        return data

    async def get_match_events(self, fixture_id: int) -> List[Dict]:
        """
        Получает события конкретного матча с кэшированием
        ОПТИМИЗИРОВАНО: Кэш на 30 секунд!

        Args:
            fixture_id: ID матча

        Returns:
            Список событий матча
        """
        # Проверяем кэш
        if fixture_id in self.events_cache:
            cached = self.events_cache[fixture_id]
            cache_age = time.time() - cached['timestamp']

            # Если кэш свежий (< 30 секунд) - используем его
            if cache_age < self.cache_duration:
                logger.info(f"💾 Используем кэш для матча {fixture_id} (возраст: {int(cache_age)}с)")
                return cached['events']

        # Если кэша нет или устарел - делаем запрос
        params = {'fixture': fixture_id}
        data = await self._make_request('fixtures/events', params)

        if data and 'quota_exceeded' in data:
            return [{'quota_exceeded': True}]

        events = []
        if data and data.get('response'):
            events = data['response']

        # Сохраняем в кэш
        self.events_cache[fixture_id] = {
            'events': events,
            'timestamp': time.time()
        }

        logger.info(f"🔄 Обновлён кэш для матча {fixture_id} ({len(events)} событий)")

        return events

    def clean_cache(self, active_fixture_ids: List[int]):
        """
        Очищает кэш для матчей, которые больше не активны

        Args:
            active_fixture_ids: Список ID активных матчей
        """
        # Удаляем из кэша все матчи, которых нет в списке активных
        to_remove = [
            fixture_id for fixture_id in self.events_cache.keys()
            if fixture_id not in active_fixture_ids
        ]

        for fixture_id in to_remove:
            del self.events_cache[fixture_id]

        if to_remove:
            logger.info(f"🧹 Очищен кэш для {len(to_remove)} завершённых матчей")

    def format_match_info(self, match: Dict) -> Dict:
        """
        Форматирует информацию о матче в удобный вид

        Args:
            match: Данные о матче от API

        Returns:
            Отформатированная информация о матче
        """
        try:
            fixture = match.get('fixture', {})
            league = match.get('league', {})
            teams = match.get('teams', {})
            goals = match.get('goals', {})

            return {
                'fixture_id': fixture.get('id'),
                'league_name': league.get('name'),
                'league_country': league.get('country'),
                'home_team': teams.get('home', {}).get('name'),
                'away_team': teams.get('away', {}).get('name'),
                'home_goals': goals.get('home', 0),
                'away_goals': goals.get('away', 0),
                'status': fixture.get('status', {}).get('short'),
                'elapsed': fixture.get('status', {}).get('elapsed'),
            }
        except Exception as e:
            logger.error(f"❌ Ошибка при форматировании матча: {e}")
            return {}

