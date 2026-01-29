"""
Модуль для работы с API-Football
Получает данные о матчах и событиях
"""
import aiohttp
import logging
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
                    if remaining:
                        logger.info(f"Осталось запросов: {remaining}")

                        # Если запросы заканчиваются
                        if int(remaining) < 10:
                            logger.warning(f"Внимание! Осталось всего {remaining} запросов!")

                    return data

                elif response.status == 429:
                    # Превышен лимит запросов
                    logger.error("Превышен лимит запросов к API!")
                    return {'quota_exceeded': True}

                else:
                    logger.error(f"Ошибка API: {response.status}")
                    return None

        except Exception as e:
            logger.error(f"Ошибка при запросе к API: {e}")
            return None

    async def get_live_matches(self) -> List[Dict]:
        """
        Получает список текущих (живых) матчей

        Returns:
            Список матчей
        """
        matches = []

        # Получаем матчи для каждой лиги
        for league_id in LEAGUES_TO_TRACK:
            params = {
                'league': league_id,
                'season': 2024,  # Текущий сезон
                'status': 'live'  # Только живые матчи
            }

            data = await self._make_request('fixtures', params)

            if data and 'quota_exceeded' in data:
                return [{'quota_exceeded': True}]

            if data and data.get('response'):
                matches.extend(data['response'])

        logger.info(f"Найдено {len(matches)} активных матчей")
        return matches

    async def get_match_events(self, fixture_id: int) -> List[Dict]:
        """
        Получает события конкретного матча

        Args:
            fixture_id: ID матча

        Returns:
            Список событий матча
        """
        params = {'fixture': fixture_id}
        data = await self._make_request('fixtures/events', params)

        if data and 'quota_exceeded' in data:
            return [{'quota_exceeded': True}]

        if data and data.get('response'):
            return data['response']

        return []

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
            logger.error(f"Ошибка при форматировании матча: {e}")
            return {}