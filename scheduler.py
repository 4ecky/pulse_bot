"""
Планировщик матчей для оптимизации API запросов
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pytz

logger = logging.getLogger(__name__)


class MatchScheduler:
    """Класс для управления расписанием матчей и оптимизации запросов"""

    def __init__(self, api):
        self.api = api
        self.today_fixtures = []
        self.last_update_date = None

        # Таймзона Москвы
        self.moscow_tz = pytz.timezone('Europe/Moscow')

        # За сколько минут до матча начинаем проверки
        self.start_check_before_minutes = 5

        # Сколько минут после окончания продолжаем проверки
        self.continue_check_after_minutes = 15

    def get_current_date(self) -> str:
        """Возвращает текущую дату в Москве"""
        now_moscow = datetime.now(self.moscow_tz)
        return now_moscow.strftime('%Y-%m-%d')

    async def update_daily_schedule(self) -> bool:
        """
        Обновляет расписание матчей на день
        Вызывается в 00:00 каждого дня

        Returns:
            True если обновление успешно
        """
        try:
            current_date = self.get_current_date()

            logger.info(f"📅 Обновление расписания матчей на {current_date}...")

            # Запрашиваем матчи на сегодня (ОДИН запрос на весь день!)
            fixtures = await self.api.get_fixtures_by_date(current_date)

            if not fixtures:
                logger.warning(f"⚠️ Не найдено матчей на {current_date}")
                self.today_fixtures = []
                self.last_update_date = current_date
                return False

            self.today_fixtures = fixtures
            self.last_update_date = current_date

            logger.info(f"✅ Загружено {len(fixtures)} матчей на {current_date}")

            # Логируем расписание
            self.log_schedule()

            return True

        except Exception as e:
            logger.error(f"❌ Ошибка обновления расписания: {e}")
            return False

    def log_schedule(self):
        """Выводит расписание матчей в лог"""
        if not self.today_fixtures:
            return

        logger.info("=" * 60)
        logger.info(f"📋 РАСПИСАНИЕ НА {self.last_update_date}")
        logger.info("=" * 60)

        # Группируем по времени начала
        by_time = {}

        for fixture in self.today_fixtures:
            fixture_date_str = fixture.get('fixture', {}).get('date')
            if not fixture_date_str:
                continue

            try:
                utc_time = datetime.fromisoformat(fixture_date_str.replace('Z', '+00:00'))
                moscow_time = utc_time.astimezone(self.moscow_tz)
                time_key = moscow_time.strftime('%H:%M')

                if time_key not in by_time:
                    by_time[time_key] = []

                home = fixture.get('teams', {}).get('home', {}).get('name', '?')
                away = fixture.get('teams', {}).get('away', {}).get('name', '?')
                league = fixture.get('league', {}).get('name', '?')

                by_time[time_key].append(f"{home} - {away} ({league})")
            except:
                continue

        # Выводим по времени
        for time_key in sorted(by_time.keys()):
            logger.info(f"\n🕐 {time_key} МСК:")
            for match in by_time[time_key]:
                logger.info(f"  ⚽ {match}")

        logger.info("=" * 60)

    def get_next_match_window(self) -> Optional[Tuple[datetime, datetime]]:
        """
        Находит следующее окно времени когда нужно проверять матчи

        Returns:
            (start_time, end_time) или None если матчей нет
        """
        if not self.today_fixtures:
            return None

        now_moscow = datetime.now(self.moscow_tz)

        # Ищем ближайший матч который ещё не закончился
        upcoming_matches = []

        for fixture in self.today_fixtures:
            status = fixture.get('fixture', {}).get('status', {}).get('short', 'NS')
            fixture_date_str = fixture.get('fixture', {}).get('date')

            if not fixture_date_str:
                continue

            try:
                utc_time = datetime.fromisoformat(fixture_date_str.replace('Z', '+00:00'))
                match_start = utc_time.astimezone(self.moscow_tz)

                # Примерное время окончания (начало + 120 минут)
                match_end = match_start + timedelta(minutes=120 + self.continue_check_after_minutes)

                # Начинаем проверять за N минут до начала
                check_start = match_start - timedelta(minutes=self.start_check_before_minutes)

                # Если матч ещё не закончился
                if now_moscow < match_end:
                    upcoming_matches.append({
                        'start': check_start,
                        'end': match_end,
                        'match_start': match_start,
                        'status': status
                    })
            except:
                continue

        if not upcoming_matches:
            return None

        # Сортируем по времени начала
        upcoming_matches.sort(key=lambda x: x['start'])

        # Объединяем пересекающиеся окна
        merged_windows = []
        current_window = upcoming_matches[0]

        for match in upcoming_matches[1:]:
            # Если матчи пересекаются - объединяем
            if match['start'] <= current_window['end']:
                current_window['end'] = max(current_window['end'], match['end'])
            else:
                merged_windows.append(current_window)
                current_window = match

        merged_windows.append(current_window)

        # Возвращаем ближайшее окно
        for window in merged_windows:
            if now_moscow < window['end']:
                return (window['start'], window['end'])

        return None

    def should_check_now(self) -> bool:
        """
        Определяет нужно ли сейчас проверять матчи

        Returns:
            True если мы внутри окна проверки матчей
        """
        window = self.get_next_match_window()

        if not window:
            return False

        start_time, end_time = window
        now_moscow = datetime.now(self.moscow_tz)

        # Проверяем находимся ли мы внутри окна
        return start_time <= now_moscow <= end_time

    def get_time_until_next_check(self) -> Optional[int]:
        """
        Возвращает количество секунд до следующей проверки

        Returns:
            Секунды до следующей проверки или None если проверок больше нет
        """
        window = self.get_next_match_window()

        if not window:
            # Нет матчей - спим до полуночи
            now_moscow = datetime.now(self.moscow_tz)
            tomorrow = now_moscow + timedelta(days=1)
            next_midnight = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

            seconds = (next_midnight - now_moscow).total_seconds()
            return int(seconds)

        start_time, end_time = window
        now_moscow = datetime.now(self.moscow_tz)

        # Если мы внутри окна - не спим
        if start_time <= now_moscow <= end_time:
            return 0

        # Если окно ещё не началось - спим до его начала
        if now_moscow < start_time:
            seconds = (start_time - now_moscow).total_seconds()
            return int(seconds)

        # Если окно закончилось - ищем следующее
        # (этот случай не должен происходить, но на всякий случай)
        return None

    def get_active_matches_count(self) -> int:
        """Возвращает количество активных матчей прямо сейчас"""
        count = 0

        for fixture in self.today_fixtures:
            status = fixture.get('fixture', {}).get('status', {}).get('short', 'NS')
            if status in ['1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE']:
                count += 1

        return count

    async def schedule_daily_update(self):
        """
        Запускает автоматическое обновление расписания каждый день в 00:00
        """
        while True:
            try:
                now_moscow = datetime.now(self.moscow_tz)

                # Вычисляем время до следующей полуночи
                tomorrow = now_moscow + timedelta(days=1)
                next_midnight = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

                seconds_until_midnight = (next_midnight - now_moscow).total_seconds()

                hours = seconds_until_midnight / 3600
                logger.info(f"⏰ Следующее обновление расписания через {hours:.1f}ч ({next_midnight.strftime('%H:%M')} МСК)")

                # Ждём до полуночи
                await asyncio.sleep(seconds_until_midnight)

                # Обновляем расписание
                await self.update_daily_schedule()

            except Exception as e:
                logger.error(f"❌ Ошибка в планировщике: {e}")
                await asyncio.sleep(3600)  # Повтор через час при ошибке