import asyncio
import logging
import json
from pathlib import Path
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
    MODE_70_MINUTE,
    BOT_VERSION
)
from football_api import FootballAPI
from notifications import NotificationManager
from functools import wraps
from config import ALLOWED_USERS, ACCESS_DENIED_MESSAGE

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Отключаем надоедливые логи от библиотек
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

# Проверка доступа
def private_access_required(func):
    """Декоратор для проверки доступа с динамическим списком"""

    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        # Проверяем доступ
        if not self.is_user_allowed(user_id):
            logger.warning(f"🚫 Неавторизованный доступ: {user_id} ({update.effective_user.first_name})")

            await update.message.reply_text(
                f"🔒 **Доступ запрещён**\n\n"
                f"Этот бот приватный.\n\n"
                f"Ваш ID: `{user_id}`\n\n"
                f"Для получения доступа свяжитесь с администратором и отправьте ему ваш ID.",
                parse_mode='Markdown'
            )
            return

        return await func(self, update, context)

    return wrapper

# обработчики команд
@private_access_required
async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id

@private_access_required
async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stop"""

@private_access_required
async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /test"""

@private_access_required
async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /status"""

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"❌ Ошибка при обработке update: {context.error}")


    if "Conflict" in str(context.error):
        logger.error("⚠️ КОНФЛИКТ: Запущено несколько экземпляров бота!")

# Команда для админа
async def allow_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /allow - даёт доступ пользователю (только админ)"""
    user_id = update.effective_user.id

    # Только админ может давать доступ
    if user_id != ADMIN_ID:
        await update.message.reply_text(MESSAGES['not_admin'])
        return

    # Проверяем аргументы команды
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "❌ Укажите ID пользователя для разрешения доступа.\n\n"
            "Пример: `/allow 123456789`",
            parse_mode='Markdown'
        )
        return

    try:
        target_user_id = int(context.args[0])

        # Загружаем список
        allowed = self.load_allowed_users()

        # Проверяем не добавлен ли уже
        if target_user_id in allowed:
            await update.message.reply_text(f"ℹ️ Пользователь {target_user_id} уже имеет доступ.")
            return

        # Добавляем
        allowed.append(target_user_id)
        self.save_allowed_users(allowed)

        await update.message.reply_text(
            f"✅ Доступ предоставлен пользователю `{target_user_id}`\n\n"
            f"Теперь он может использовать бота.",
            parse_mode='Markdown'
        )

        # Пытаемся уведомить пользователя
        try:
            await self.application.bot.send_message(
                chat_id=target_user_id,
                text="🎉 Вам предоставлен доступ к боту!\n\nИспользуйте /start для начала работы."
            )
        except:
            pass  # Не можем отправить если пользователь не писал боту

        logger.info(f"✅ Админ {user_id} дал доступ пользователю {target_user_id}")

    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Укажите числовой ID.")

"""Команда /revoke - отзывает доступ (только админ)"""
async def revoke_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text(MESSAGES['not_admin'])
        return

    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "❌ Укажите ID пользователя для отзыва доступа.\n\n"
            "Пример: `/revoke 123456789`",
            parse_mode='Markdown'
        )
        return

    try:
        target_user_id = int(context.args[0])

        # Загружаем список
        allowed = self.load_allowed_users()

        # Проверяем есть ли в списке
        if target_user_id not in allowed:
            await update.message.reply_text(f"ℹ️ Пользователь {target_user_id} не имеет доступа.")
            return

        # Удаляем
        allowed.remove(target_user_id)
        self.save_allowed_users(allowed)

        # Останавливаем бота для этого пользователя
        if target_user_id in self.user_states:
            self.user_states[target_user_id]['is_running'] = False
            self.save_active_users()

        await update.message.reply_text(
            f"✅ Доступ отозван у пользователя `{target_user_id}`",
            parse_mode='Markdown'
        )

        # Уведомляем пользователя
        try:
            await self.application.bot.send_message(
                chat_id=target_user_id,
                text="⛔ Ваш доступ к боту был отозван администратором."
            )
        except:
            pass

        logger.info(f"⛔ Админ {user_id} отозвал доступ у {target_user_id}")

    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID.")

"""Команда /list - показывает список разрешённых пользователей (только админ)"""
async def list_users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text(MESSAGES['not_admin'])
        return

    allowed = self.load_allowed_users()

    if not allowed:
        await update.message.reply_text("ℹ️ Список разрешённых пользователей пуст.")
        return

    message = "📋 **Разрешённые пользователи:**\n\n"

    for uid in allowed:
        # Пытаемся получить имя пользователя
        username = "Unknown"
        if uid in self.user_states:
            username = self.user_states[uid].get('username', 'Unknown')

        is_active = "✅" if uid in self.get_active_user_ids() else "⛔"
        message += f"{is_active} `{uid}` - {username}\n"

    await update.message.reply_text(message, parse_mode='Markdown')

"""Основной класс телеграм-бота с оптимизированной архитектурой"""
class FootballBot:

    def __init__(self):
        self.api = FootballAPI()
        self.notification_manager = NotificationManager()

        # Словарь для хранения состояния каждого пользователя
        # Ключ: user_id, Значение: {is_running, username}
        self.user_states: Dict[int, Dict] = {}

        # Множество для отслеживания уже отправленных уведомлений
        # Ключ: (user_id, fixture_id, minute, player_name)
        self.sent_notifications: Set[tuple] = set()

        # Флаг для тестового режима
        self.test_mode_active = False

        # Файл для сохранения активных пользователей
        self.active_users_file = Path('active_users.json')

        # НОВОЕ: Флаг работы глобального цикла
        self.global_loop_running = False

        # НОВОЕ: Application для доступа из глобального цикла
        self.application = None

        # Загружаем список разрешённых пользователей
        self.allowed_users = self.load_allowed_users()

    def load_active_users(self):
        """Загружает список активных пользователей из файла"""
        if self.active_users_file.exists():
            try:
                with open(self.active_users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"📂 Загружено {len(data)} активных пользователей")
                    return data
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки активных пользователей: {e}")
        return []

    def save_active_users(self):
        """Сохраняет список активных пользователей в файл"""
        try:
            active = [
                {
                    'user_id': uid,
                    'username': info.get('username', 'Unknown'),
                    'saved_at': datetime.now().isoformat()
                }
                for uid, info in self.user_states.items()
                if info.get('is_running', False)
            ]
            with open(self.active_users_file, 'w', encoding='utf-8') as f:
                json.dump(active, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Сохранено {len(active)} активных пользователей")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения активных пользователей: {e}")

    def get_active_user_ids(self) -> list:
        """
        Возвращает список ID всех активных пользователей
        """
        return [
            uid for uid, info in self.user_states.items()
            if info.get('is_running', False)
        ]

    async def auto_restart_users(self, application):
        """Автоматически перезапускает бота для сохранённых пользователей"""
        saved_users = self.load_active_users()

        if not saved_users:
            logger.info("ℹ️ Нет сохранённых пользователей для перезапуска")
            return

        logger.info(f"🔄 Перезапуск для {len(saved_users)} пользователей...")

        restarted_count = 0

        for user_data in saved_users:
            user_id = user_data.get('user_id')
            username = user_data.get('username', 'Unknown')

            if not user_id:
                continue

            try:
                # Инициализируем состояние
                self.user_states[user_id] = {
                    'is_running': True,
                    'username': username
                }

                # Отправляем уведомление
                await application.bot.send_message(
                    chat_id=user_id,
                    text=f"🔄 **Бот обновлён до версии {BOT_VERSION}**\n\n"
                         f"✅ Автоматически перезапущен и продолжает работу.\n"
                         f"📊 Все режимы активны.",
                    parse_mode='Markdown'
                )

                restarted_count += 1
                logger.info(f"✅ Перезапущен для {user_id} ({username})")

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"❌ Ошибка перезапуска для {user_id}: {e}")

        logger.info(f"🎉 Перезапуск завершён: {restarted_count}/{len(saved_users)}")

        # ВАЖНО: Запускаем глобальный цикл если есть активные пользователи
        if restarted_count > 0:
            await self.start_global_loop()

    async def start_global_loop(self):
        """
        Запускает глобальный цикл проверки матчей (если ещё не запущен)
        ОДИН цикл обслуживает ВСЕХ пользователей
        """
        if self.global_loop_running:
            logger.info("ℹ️ Глобальный цикл уже запущен")
            return

        self.global_loop_running = True
        logger.info("🚀 Запуск глобального цикла проверки матчей")

        self.application.create_task(self.global_matches_check_loop())

    async def stop_global_loop(self):
        """Останавливает глобальный цикл"""
        self.global_loop_running = False
        logger.info("⏹ Глобальный цикл остановлен")

    async def global_matches_check_loop(self):
        """
        ГЛАВНЫЙ ЦИКЛ: Проверяет матчи для ВСЕХ активных пользователей
        Делает запросы к API ОДИН РАЗ, рассылает результаты всем
        """
        logger.info("🔄 Глобальный цикл проверки матчей запущен")

        iteration = 0

        while self.global_loop_running:
            # Проверяем есть ли активные пользователи
            active_users = self.get_active_user_ids()

            if not active_users:
                logger.info("⚠️ Нет активных пользователей. Останавливаю глобальный цикл.")
                self.global_loop_running = False
                break

            try:
                iteration += 1
                logger.info(f"[Итерация {iteration}] Проверка матчей для {len(active_users)} пользователей...")

                # ОДИН запрос на всех пользователей!
                matches = await self.api.get_live_matches()

                # Проверка квоты
                if matches and isinstance(matches, list) and len(matches) > 0:
                    if matches[0].get('quota_exceeded'):
                        # Уведомляем ВСЕХ пользователей
                        for user_id in active_users:
                            try:
                                await self.application.bot.send_message(
                                    chat_id=user_id,
                                    text=MESSAGES['quota_exceeded']
                                )
                                self.user_states[user_id]['is_running'] = False
                            except Exception as e:
                                logger.error(f"❌ Ошибка уведомления {user_id}: {e}")

                        self.save_active_users()
                        logger.warning(f"⚠️ Квота исчерпана. Бот остановлен для всех.")
                        self.global_loop_running = False
                        break

                # Очистка кэша
                if matches:
                    active_fixture_ids = [
                        self.api.format_match_info(match).get('fixture_id')
                        for match in matches
                        if isinstance(match, dict) and self.api.format_match_info(match).get('fixture_id')
                    ]
                    self.api.clean_cache(active_fixture_ids)

                # Обрабатываем каждый матч для ВСЕХ пользователей
                for match in matches:
                    if not self.global_loop_running:
                        break

                    await self.process_match_for_all_users(match, active_users)

                logger.info(f"[Итерация {iteration}] Завершена. Следующая через {CHECK_INTERVAL}с")

                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"❌ Ошибка в глобальном цикле: {e}")
                await asyncio.sleep(CHECK_INTERVAL)

        logger.info("⏹ Глобальный цикл проверки завершён")

    async def process_match_for_all_users(self, match: Dict, active_users: list):
        """
        Обрабатывает один матч для ВСЕХ активных пользователей

        Args:
            match: Данные о матче
            active_users: Список ID активных пользователей
        """
        try:
            match_info = self.api.format_match_info(match)
            fixture_id = match_info.get('fixture_id')

            if not fixture_id:
                return

            # ОДИН запрос событий на всех пользователей!
            events = await self.api.get_match_events(fixture_id)

            # Проверка квоты
            if events and isinstance(events, list) and len(events) > 0:
                if events[0].get('quota_exceeded'):
                    for user_id in active_users:
                        try:
                            await self.application.bot.send_message(
                                chat_id=user_id,
                                text=MESSAGES['quota_exceeded']
                            )
                            self.user_states[user_id]['is_running'] = False
                        except Exception as e:
                            logger.error(f"❌ Ошибка уведомления {user_id}: {e}")

                    self.save_active_users()
                    self.global_loop_running = False
                    return

            # Обрабатываем события для каждого пользователя
            for event in events:
                if not self.notification_manager.is_goal_event(event):
                    continue

                minute = event.get('time', {}).get('elapsed', 0)
                player_name = event.get('player', {}).get('name', '')

                # Проверяем для КАЖДОГО пользователя
                for user_id in active_users:
                    # Уникальный ключ для этого пользователя и события
                    event_key = (user_id, fixture_id, minute, player_name)

                    # Уже отправляли этому пользователю?
                    if event_key in self.sent_notifications:
                        continue

                    # Определяем нужно ли уведомление
                    should_notify = False
                    mode_name = ""

                    if self.test_mode_active:
                        should_notify = True
                        mode_name = "🧪 Тестовый режим"

                        # Выключаем тестовый режим после первого
                        self.test_mode_active = False
                        try:
                            await self.application.bot.send_message(
                                chat_id=ADMIN_ID,
                                text=MESSAGES['test_mode_off']
                            )
                        except:
                            pass
                        logger.info("✅ Тестовый режим выключен")

                    elif self.notification_manager.should_notify_70_minute_mode(minute):
                        should_notify = True
                        mode_name = MODE_70_MINUTE['name']

                    # Отправляем уведомление
                    if should_notify:
                        try:
                            notification_text = self.notification_manager.create_goal_notification(
                                match_info, event, mode_name
                            )

                            await self.application.bot.send_message(
                                chat_id=user_id,
                                text=notification_text,
                                parse_mode='Markdown'
                            )

                            self.sent_notifications.add(event_key)

                            logger.info(f"⚽ Уведомление → {user_id}: "
                                        f"{match_info['home_team']} vs {match_info['away_team']}, "
                                        f"мин {minute}")
                        except Exception as e:
                            logger.error(f"❌ Ошибка отправки уведомления {user_id}: {e}")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки матча: {e}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        user_id = user.id

        if user_id not in self.user_states:
            self.user_states[user_id] = {
                'is_running': False,
                'username': user.first_name
            }

        if self.user_states[user_id]['is_running']:
            await update.message.reply_text(MESSAGES['already_running'])
            return

        # Активируем пользователя
        self.user_states[user_id]['is_running'] = True
        self.user_states[user_id]['username'] = user.first_name

        self.save_active_users()

        welcome_message = MESSAGES['welcome'].format(name=user.first_name)
        await update.message.reply_text(welcome_message)

        logger.info(f"🚀 Бот запущен для {user_id} ({user.first_name})")

        # Запускаем глобальный цикл (если ещё не запущен)
        await self.start_global_loop()

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stop"""
        user_id = update.effective_user.id

        if user_id not in self.user_states or not self.user_states[user_id]['is_running']:
            await update.message.reply_text(MESSAGES['not_running'])
            return

        self.user_states[user_id]['is_running'] = False
        self.save_active_users()

        await update.message.reply_text(MESSAGES['stopped'])
        logger.info(f"⛔ Бот остановлен для {user_id}")

        # Останавливаем глобальный цикл если нет активных пользователей
        active_users = self.get_active_user_ids()
        if not active_users:
            await self.stop_global_loop()

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /test (только админ)"""
        user_id = update.effective_user.id

        if user_id != ADMIN_ID:
            await update.message.reply_text(MESSAGES['not_admin'])
            return

        self.test_mode_active = True
        await update.message.reply_text(MESSAGES['test_mode_on'])
        logger.info(f"🧪 Тестовый режим включен админом {user_id}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /status"""
        user_id = update.effective_user.id

        if user_id not in self.user_states:
            await update.message.reply_text(
                "❌ Бот не был запущен.\n\nИспользуй /start"
            )
            return

        is_running = self.user_states[user_id].get('is_running', False)
        test_mode = "🧪 ВКЛ" if self.test_mode_active else "🧪 ВЫКЛ"
        total_active = len(self.get_active_user_ids())

        from config import LEAGUES_TO_TRACK

        status_text = f"""
📊 **Статус бота** (v{BOT_VERSION})

**Твой статус:** {'✅ Работает' if is_running else '⛔ Остановлен'}

**Режимы:**
- Режим "70 минута": {'✅ Активен' if is_running else '⛔ Неактивен'}
- Тестовый режим: {test_mode}

**Настройки:**
- Интервал проверки: {CHECK_INTERVAL} сек
- Отслеживается лиг: {len(LEAGUES_TO_TRACK)}
- Активных пользователей: {total_active}
- Глобальный цикл: {'✅ Работает' if self.global_loop_running else '⛔ Остановлен'}

**Команды:**
/start - запустить
/stop - остановить
/status - статус
"""

        if user_id == ADMIN_ID:
            status_text += "/test - тест (админ)\n"

        await update.message.reply_text(status_text, parse_mode='Markdown')

    async def cleanup(self):
        """Очистка ресурсов"""
        await self.api.close_session()
        logger.info("🧹 Ресурсы очищены")


def run(self):
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    self.application = application

    application.add_handler(CommandHandler("start", self.start_command))
    application.add_handler(CommandHandler("stop", self.stop_command))
    application.add_handler(CommandHandler("test", self.test_command))
    application.add_handler(CommandHandler("status", self.status_command))

    # Команды управления доступом (только для админа)
    application.add_handler(CommandHandler("allow", self.allow_command))
    application.add_handler(CommandHandler("revoke", self.revoke_command))
    application.add_handler(CommandHandler("list", self.list_users_command))

    application.add_error_handler(error_handler)

def main():
    """Главная функция"""
    bot = FootballBot()

    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("⚠️ Получен сигнал остановки")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    finally:
        asyncio.run(bot.cleanup())
        logger.info("👋 Бот завершил работу")


# Методы для разрешенных пользователей
def load_allowed_users(self) -> list:
    """Загружает список разрешённых пользователей из файла"""
    file_path = Path(ALLOWED_USERS_FILE)
    if file_path.exists():
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_allowed_users(self, users: list):
    """Сохраняет список разрешённых пользователей"""
    with open(ALLOWED_USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def is_user_allowed(self, user_id: int) -> bool:
    """Проверяет разрешён ли доступ пользователю"""
    allowed = self.load_allowed_users()
    return user_id in allowed or user_id == ADMIN_ID

if __name__ == '__main__':
    main()