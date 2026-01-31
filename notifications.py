"""
Модуль для формирования и отправки уведомлений
"""
import logging
from typing import Dict
from config import MODE_70_MINUTE, MELBET_BASE_URL
from translations import translate_league, translate_team

logger = logging.getLogger(__name__)


class NotificationManager:
    """Класс для управления уведомлениями"""

    @staticmethod
    def create_goal_notification(self, match_info: Dict, event: Dict, mode_name: str) -> str:
        """
        Создает текст уведомления о голе
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
        message += f"🕐 {minute}'\n\n"

        # Ссылка на матч
        fixture_id = match_info.get('fixture_id', '')
        message += f"[📺 Смотреть онлайн](https://www.sofascore.com/)\n"

        return message

    @staticmethod
    def should_notify_70_minute_mode(self, minute: int, match_info: Dict, event: Dict) -> bool:
        """
        Проверяет подходит ли гол под режим "70 минута"
        НОВОЕ УСЛОВИЕ: Только первый гол в матче (счет должен стать 1:0 или 0:1)

        Args:
            minute: Минута гола
            match_info: Информация о матче
            event: Событие гола

        Returns:
            True если нужно уведомление
        """
        min_minute = MODE_70_MINUTE['min_minute']
        max_minute = MODE_70_MINUTE['max_minute']

        # Проверяем минуту
        if not (min_minute <= minute <= max_minute):
            return False

        # Получаем текущий счет после гола
        home_goals = match_info.get('home_goals', 0)
        away_goals = match_info.get('away_goals', 0)

        # Определяем какая команда забила
        team_name = event.get('team', {}).get('name', '')
        home_team = match_info.get('home_team', '')

        # Проверяем: это первый гол в матче?
        # Счет должен быть 1:0 или 0:1
        total_goals = home_goals + away_goals

        if total_goals != 1:
            return False  # Не первый гол

        # Это первый гол! Уведомляем
        logger.info(f"✅ Режим '70 минута': ПЕРВЫЙ гол на {minute}' ({home_goals}:{away_goals})")
        return True

    @staticmethod
    def is_goal_event(event: Dict) -> bool:
        """
        Проверяет, является ли событие голом

        Args:
            event: Событие матча

        Returns:
            True, если это гол
        """
        event_type = event.get('type', '').lower()
        event_detail = event.get('detail', '').lower()

        # Проверяем различные типы голов
        goal_types = ['goal', 'normal goal']
        goal_details = ['normal goal', 'penalty', 'own goal']

        is_goal = event_type in goal_types or event_detail in goal_details

        return is_goal