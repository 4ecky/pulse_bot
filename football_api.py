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
        self.cache_duration = 120  # Кэш на 2 минуты

    async def init_session(self):
        """Инициализация сессии для запросов"""
        if self.session is None:
            self.session = aiohttp.ClientSession(headers=self.headers)

    async def close_session(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            self.session = None

    async def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """
        Выполняет запрос к API

        Args:
            endpoint: Конечная точка API
            params: Параметры запроса

        Returns:
            Ответ от API или None в случае ошибки
        """
        await self.init_session()

        url = f"{self.base_url}/{endpoint}"

        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()

                    # Проверяем лимиты API
                    remaining = response.headers.get('x-ratelimit-requests-remaining')
                    limit = response.headers.get('x-ratelimit-requests-limit')

                    if remaining and limit:
                        logger.info(f"📊 API квота: {remaining}/{limit} запросов осталось")

                        # Предупреждение если мало осталось
                        if int(remaining) < 20:
                            logger.warning(f"⚠️ Мало запросов! Осталось: {remaining}/{limit}")

                    return data

                elif response.status == 429:
                    # Превышен лимит запросов
                    logger.error("❌ Превышен лимит запросов к API!")
                    return {'quota_exceeded': True}

                else:
                    logger.error(f"❌ Ошибка API: {response.status}")
                    return None

        except Exception as e:
            logger.error(f"❌ Ошибка при запросе к API: {e}")
            return None

    async def get_live_matches(self) -> List[Dict]:
        """
        Получает список текущих (живых) матчей

        Returns:
            Список матчей
        """
        # Один запрос для ВСЕХ live матчей
        params = {
            'live': 'all'
        }

        data = await self._make_request('fixtures', params)

        if data and 'quota_exceeded' in data:
            return [{'quota_exceeded': True}]

        if not data or not data.get('response'):
            return []

        # Фильтруем только матчи из нужных нам лиг
        all_matches = data['response']
        filtered_matches = [
            match for match in all_matches
            if match.get('league', {}).get('id') in LEAGUES_TO_TRACK
        ]

        logger.info(f"⚽ Найдено {len(filtered_matches)} активных матчей в отслеживаемых лигах")
        return filtered_matches

    async def get_match_events(self, fixture_id: int) -> List[Dict]:
        """
        Получает события конкретного матча с кэшированием
        ОПТИМИЗИРОВАНО: Кэш на 2 минуты!

        Args:
            fixture_id: ID матча

        Returns:
            Список событий матча
        """
        # Проверяем кэш
        if fixture_id in self.events_cache:
            cached = self.events_cache[fixture_id]
            cache_age = time.time() - cached['timestamp']

            # Если кэш свежий (< 2 минут) - используем его
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