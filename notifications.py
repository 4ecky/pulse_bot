"""
Модуль для формирования и отправки уведомлений
"""
import logging
from typing import Dict
from config import MODE_70_MINUTE, MELBET_BASE_URL

logger = logging.getLogger(__name__)


class NotificationManager:
    """Класс для управления уведомлениями"""

    @staticmethod
    def create_goal_notification(match_info: Dict, event: Dict, mode_name: str) -> str:
        """
        Создает текст уведомления о голе

        Args:
            match_info: Информация о матче
            event: Информация о событии (гол)
            mode_name: Название режима

        Returns:
            Отформатированный текст уведомления
        """
        try:
            # Получаем данные о голе
            minute = event.get('time', {}).get('elapsed', 0)
            extra_time = event.get('time', {}).get('extra', 0)
            team_name = event.get('team', {}).get('name', 'Неизвестная команда')
            player_name = event.get('player', {}).get('name', 'Неизвестный игрок')

            # Формируем строку с минутой
            if extra_time:
                minute_str = f"{minute}+{extra_time}'"
            else:
                minute_str = f"{minute}'"

            # Формируем счет
            score = f"{match_info['home_goals']}:{match_info['away_goals']}"

            # Создаем ссылку на матч в Мелбет
            # Примечание: реальная ссылка может отличаться, это базовый вариант
            melbet_link = f"{MELBET_BASE_URL}/live/football"

            # Формируем текст уведомления
            notification = (
                f"⚽ {mode_name}\n\n"
                f"🏆 {match_info['league_name']}\n"
                f"📍 {match_info['league_country']}\n\n"
                f"🏟 {match_info['home_team']} vs {match_info['away_team']}\n\n"
                f"⚡ ГОЛ! {team_name}\n"
                f"👤 {player_name}\n\n"
                f"📊 Счет: {score}\n"
                f"⏱ Минута: {minute_str}\n\n"
                f"🔗 [Смотреть матч в Мелбет]({melbet_link})"
            )

            return notification

        except Exception as e:
            logger.error(f"Ошибка при создании уведомления: {e}")
            return "Ошибка при формировании уведомления"

    @staticmethod
    def should_notify_70_minute_mode(minute: int) -> bool:
        """
        Проверяет, нужно ли отправлять уведомление в режиме "70 минута"

        Args:
            minute: Минута, на которой забит гол

        Returns:
            True, если нужно отправить уведомление
        """
        min_minute = MODE_70_MINUTE['min_minute']
        max_minute = MODE_70_MINUTE['max_minute']

        return min_minute <= minute <= max_minute

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