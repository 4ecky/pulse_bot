"""
Модуль для создания и управления уведомлениями
"""
import logging
from typing import Dict
from config import MODE_70_MINUTE

logger = logging.getLogger(__name__)

# Импорт переводов
try:
    from translations import translate_league, translate_team
except ImportError:
    # Если файл переводов отсутствует - используем оригинальные названия
    def translate_league(league_name: str, country: str = None) -> str:
        return league_name

    def translate_team(team_name: str) -> str:
        return team_name


class NotificationManager:
    """Класс для управления уведомлениями о голах"""

    def __init__(self):
        pass

    def is_goal_event(self, event: Dict) -> bool:
        """
        Проверяет является ли событие голом

        Args:
            event: Событие из API

        Returns:
            True если это гол
        """
        event_type = event.get('type', '').lower()
        detail = event.get('detail', '').lower()

        # Типы событий которые считаются голами
        goal_types = ['goal', 'normal goal']
        goal_details = ['normal goal', 'penalty', 'own goal']

        return event_type in goal_types or detail in goal_details

    def should_notify_70_minute_mode(self, minute: int, match_info: Dict, event: Dict) -> bool:
        """
        Проверяет подходит ли гол под режим "70 минута"

        УСЛОВИЯ:
        1. Гол забит на 69-й или 70-й минуте (69:00-70:59)
        2. Это ПЕРВЫЙ гол в матче (счет после гола: 1:0 или 0:1)

        Args:
            minute: Минута гола
            match_info: Информация о матче
            event: Событие гола

        Returns:
            True если нужно уведомление
        """
        min_minute = MODE_70_MINUTE['min_minute']
        max_minute = MODE_70_MINUTE['max_minute']

        # УСЛОВИЕ 1: Проверяем что гол забит на 69-й или 70-й минуте
        if not (min_minute <= minute <= max_minute):
            logger.debug(f"❌ Режим '70 минута': Гол не на 69-70 минуте (минута: {minute})")
            return False

        # УСЛОВИЕ 2: Получаем текущий счет после гола
        home_goals = match_info.get('home_goals', 0)
        away_goals = match_info.get('away_goals', 0)

        # Проверяем: это первый гол в матче?
        # Счет должен быть СТРОГО 1:0 или 0:1
        total_goals = home_goals + away_goals

        if total_goals != 1:
            logger.info(
                f"❌ Режим '70 минута': НЕ первый гол на {minute}' "
                f"(счет {home_goals}:{away_goals}, всего голов: {total_goals})"
            )
            return False

        # ✅ ОБА УСЛОВИЯ ВЫПОЛНЕНЫ!
        # Гол на 69-й или 70-й минуте И это первый гол в матче
        logger.info(
            f"✅ Режим '70 минута' СРАБОТАЛ: "
            f"ПЕРВЫЙ гол на {minute}' минуте (счет {home_goals}:{away_goals})"
        )
        return True

    def create_goal_notification(self, match_info: Dict, event: Dict, mode_name: str) -> str:
        """
        Создает текст уведомления о голе

        Args:
            match_info: Информация о матче
            event: Событие гола
            mode_name: Название режима уведомления

        Returns:
            Отформатированное сообщение
        """
        # Базовая информация
        league = match_info.get('league_name', 'Неизвестная лига')
        league_country = match_info.get('league_country', '')
        home_team = match_info.get('home_team', '?')
        away_team = match_info.get('away_team', '?')
        home_goals = match_info.get('home_goals', 0)
        away_goals = match_info.get('away_goals', 0)
        minute = event.get('time', {}).get('elapsed', '?')

        # ПЕРЕВОДИМ НА РУССКИЙ
        league_ru = translate_league(league, league_country)
        home_team_ru = translate_team(home_team)
        away_team_ru = translate_team(away_team)

        # Информация о голе
        player_name = event.get('player', {}).get('name', 'Неизвестный игрок')
        team_name = event.get('team', {}).get('name', '')
        team_name_ru = translate_team(team_name)
        detail = event.get('detail', 'Goal')

        # Эмодзи в зависимости от типа гола
        if 'penalty' in detail.lower():
            goal_emoji = '⚽️ (П)'
        elif 'own' in detail.lower():
            goal_emoji = '⚽️ (АГ)'
        else:
            goal_emoji = '⚽️'

        # Формируем сообщение
        message = f"{mode_name}\n\n"
        message += f"🏆 **{league_ru}**\n"
        message += f"{home_team_ru} **{home_goals}:{away_goals}** {away_team_ru}\n\n"
        message += f"{goal_emoji} **{player_name}** ({team_name_ru})\n"
        message += f"🕐 {minute}'\n"

        # БЕЗ ссылки (чтобы не было 404)
        # Пользователь сам откроет своё приложение

        return message