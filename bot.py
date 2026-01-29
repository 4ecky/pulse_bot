"""
Главный файл телеграм-бота
Содержит всю логику работы бота
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Set
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_ID,
    CHECK_INTERVAL,
    MESSAGES,
    MODE_70_MINUTE
)
from football_api import FootballAPI
from notifications import NotificationManager

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class FootballBot:
    """Основной класс телеграм-бота"""

    def __init__(self):
        self.api = FootballAPI()
        self.notification_manager = NotificationManager()

        # Словарь для хранения состояния каждого пользователя
        self.user_states: Dict[int, Dict] = {}

        # Множество для отслеживания уже отправленных уведомлений
        # Ключ: (user_id, fixture_id, event_time)
        self.sent_notifications: Set[tuple] = set()

        # Флаг для тестового режима
        self.test_mode_active = False

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        user_id = user.id

        # Инициализируем состояние пользователя
        if user_id not in self.user_states:
            self.user_states[user_id] = {
                'is_running': False,
                'username': user.first_name
            }

        # Проверяем, не запущен ли уже бот
        if self.user_states[user_id]['is_running']:
            await update.message.reply_text(MESSAGES['already_running'])
            return

        # Запускаем бота для пользователя
        self.user_states[user_id]['is_running'] = True

        # Отправляем приветственное сообщение
        welcome_message = MESSAGES['welcome'].format(name=user.first_name)
        await update.message.reply_text(welcome_message)

        logger.info(f"Бот запущен для пользователя {user_id} ({user.first_name})")

        # Запускаем фоновую задачу для этого пользователя
        context.application.create_task(
            self.check_matches_loop(user_id, context)
        )

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stop"""
        user_id = update.effective_user.id

        if user_id not in self.user_states or not self.user_states[user_id]['is_running']:
            await update.message.reply_text(MESSAGES['not_running'])
            return

        # Останавливаем бота
        self.user_states[user_id]['is_running'] = False
        await update.message.reply_text(MESSAGES['stopped'])

        logger.info(f"Бот остановлен для пользователя {user_id}")

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /test (только для администратора)"""
        user_id = update.effective_user.id

        # Проверяем, является ли пользователь администратором
        if user_id != ADMIN_ID:
            await update.message.reply_text(MESSAGES['not_admin'])
            return

        # Включаем тестовый режим
        self.test_mode_active = True
        await update.message.reply_text(MESSAGES['test_mode_on'])

        logger.info(f"Тестовый режим включен администратором {user_id}")

    async def check_matches_loop(self, user_id: int, context: ContextTypes.DEFAULT_TYPE):
        """
        Основной цикл проверки матчей для конкретного пользователя

        Args:
            user_id: ID пользователя Telegram
            context: Контекст бота
        """
        logger.info(f"Запущен цикл проверки матчей для пользователя {user_id}")

        while self.user_states.get(user_id, {}).get('is_running', False):
            try:
                # Получаем список текущих матчей
                matches = await self.api.get_live_matches()

                # Проверяем, не закончились ли запросы
                if matches and isinstance(matches, list) and len(matches) > 0:
                    if matches[0].get('quota_exceeded'):
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=MESSAGES['quota_exceeded']
                        )
                        self.user_states[user_id]['is_running'] = False
                        logger.warning(f"Квота API исчерпана для пользователя {user_id}")
                        break

                # Обрабатываем каждый матч
                for match in matches:
                    if not self.user_states.get(user_id, {}).get('is_running', False):
                        break

                    await self.process_match(user_id, match, context)

                # Ждем перед следующей проверкой
                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Ошибка в цикле проверки матчей для пользователя {user_id}: {e}")
                await asyncio.sleep(CHECK_INTERVAL)

        logger.info(f"Цикл проверки матчей остановлен для пользователя {user_id}")

    async def process_match(self, user_id: int, match: Dict, context: ContextTypes.DEFAULT_TYPE):
        """
        Обрабатывает один матч и проверяет события

        Args:
            user_id: ID пользователя
            match: Данные о матче
            context: Контекст бота
        """
        try:
            # Форматируем информацию о матче
            match_info = self.api.format_match_info(match)
            fixture_id = match_info.get('fixture_id')

            if not fixture_id:
                return

            # Получаем события матча
            events = await self.api.get_match_events(fixture_id)

            # Проверяем квоту
            if events and isinstance(events, list) and len(events) > 0:
                if events[0].get('quota_exceeded'):
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=MESSAGES['quota_exceeded']
                    )
                    self.user_states[user_id]['is_running'] = False
                    return

            # Обрабатываем каждое событие
            for event in events:
                # Проверяем, является ли событие голом
                if not self.notification_manager.is_goal_event(event):
                    continue

                # Получаем минуту гола
                minute = event.get('time', {}).get('elapsed', 0)

                # Создаем уникальный ключ для этого события
                event_key = (user_id, fixture_id, minute, event.get('player', {}).get('name', ''))

                # Проверяем, не отправляли ли мы уже это уведомление
                if event_key in self.sent_notifications:
                    continue

                # Определяем, нужно ли отправлять уведомление
                should_notify = False
                mode_name = ""

                if self.test_mode_active:
                    # В тестовом режиме отправляем все голы
                    should_notify = True
                    mode_name = "🧪 Тестовый режим"

                    # Выключаем тестовый режим после первого уведомления
                    self.test_mode_active = False
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=MESSAGES['test_mode_off']
                    )
                    logger.info("Тестовый режим автоматически выключен")

                elif self.notification_manager.should_notify_70_minute_mode(minute):
                    # Режим "70 минута"
                    should_notify = True
                    mode_name = MODE_70_MINUTE['name']

                # Отправляем уведомление, если нужно
                if should_notify:
                    notification_text = self.notification_manager.create_goal_notification(
                        match_info, event, mode_name
                    )

                    await context.bot.send_message(
                        chat_id=user_id,
                        text=notification_text,
                        parse_mode='Markdown'
                    )

                    # Добавляем в множество отправленных
                    self.sent_notifications.add(event_key)

                    logger.info(f"Отправлено уведомление пользователю {user_id}: "
                                f"{match_info['home_team']} vs {match_info['away_team']}, "
                                f"минута {minute}")

        except Exception as e:
            logger.error(f"Ошибка при обработке матча: {e}")

    async def cleanup(self):
        """Очистка ресурсов перед завершением работы"""
        await self.api.close_session()
        logger.info("Ресурсы очищены")

    def run(self):
        """Запуск бота"""
        # Создаем приложение
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Добавляем обработчики команд
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("stop", self.stop_command))
        application.add_handler(CommandHandler("test", self.test_command))

        # Запускаем бота
        logger.info("Бот запущен и готов к работе!")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Главная функция"""
    bot = FootballBot()

    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        # Очистка при завершении
        asyncio.run(bot.cleanup())


if __name__ == '__main__':
    main()