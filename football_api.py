def get_all_fixtures_today(self) -> List[Dict]:
    """
    Возвращает ВСЕ матчи на день из последнего запроса
    БЕЗ дополнительных запросов к API!

    Данные обновляются автоматически каждые 2 минуты
    глобальным циклом проверки.

    Returns:
        Список всех матчей на день (live + предстоящие)
    """
    if not self.all_fixtures_today:
        logger.warning("⚠️ Нет данных о матчах. Возможно глобальный цикл ещё не запущен.")
        return []

    logger.info(f"💾 Возвращаем {len(self.all_fixtures_today)} матчей из кэша (БЕЗ запроса к API)")

    return self.all_fixtures_today

def __init__(self):
    self.base_url = FOOTBALL_API_BASE_URL
    self.headers = {
        'x-apisports-key': FOOTBALL_API_KEY
    }
    self.session: Optional[aiohttp.ClientSession] = None

    # Кэш событий матчей
    self.events_cache: Dict[int, Dict] = {}
    self.cache_duration = 30  # Кэш на 30 секунд

    # НОВОЕ: Сохраняем ВСЕ матчи из последнего запроса
    self.all_fixtures_today = []
    self.last_fixtures_update = None


async def get_live_matches(self) -> List[Dict]:
    """
    Получает список текущих (живых) матчей
    ОПТИМИЗИРОВАНО: Один запрос вместо 12!
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
    self.all_fixtures_today = filtered_all
    self.last_fixtures_update = datetime.now()

    # Фильтруем только LIVE для возврата
    live_matches = [
        match for match in filtered_all
        if match.get('fixture', {}).get('status', {}).get('short') in ['1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE']
    ]

    logger.info(
        f"⚽ Найдено {len(live_matches)} live матчей и {len(filtered_all)} всего на день "
        f"(из них {len(filtered_all) - len(live_matches)} предстоящих)"
    )

    return live_matches
