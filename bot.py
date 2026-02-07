"""
Главный файл телеграм-бота
ОПТИМИЗИРОВАННАЯ АРХИТЕКТУРА: один цикл проверки на всех пользователей
"""
import asyncio
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Set
from functools import wraps
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
    CHECK_INTERVAL_ACTIVE,
    CHECK_INTERVAL_IDLE,
    MESSAGES,
    MODE_70_MINUTE,
    MODE_PENALTY_EARLY,
    ALLOWED_USERS,
    ACCESS_DENIED_MESSAGE
)
from football_api import FootballAPI
from notifications import NotificationManager

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


def private_access_required(func):
    """Декоратор для проверки доступа - только разрешённые пользователи"""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            logger.error("❌ update.effective_user is None")
            return
        
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Unknown"
        
        # Проверка по белому списку
        if user_id not in ALLOWED_USERS:
            logger.warning(f"🚫 Неавторизованный доступ: {user_id} ({user_name})")
            
            try:
                await update.message.reply_text(
                    ACCESS_DENIED_MESSAGE.format(user_id=user_id),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"❌ Ошибка отправки сообщения об отказе: {e}")
            
            return
        
        return await func(self, update, context)
    
    return wrapper


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"❌ Ошибка при обработке update: {context.error}")
    
    if "Conflict" in str(context.error):
        logger.error("⚠️ КОНФЛИКТ: Запущено несколько экземпляров бота!")


class FootballBot:
    """Основной класс телеграм-бота с оптимизированной архитектурой"""
    
    def __init__(self):
        self.api = FootballAPI()
        self.notification_manager = NotificationManager()
        
        # JSON файл для сохранения активных пользователей
        self.active_users_file = Path('active_users.json')
        
        # Планировщик матчей (инициализируется позже)
        self.scheduler = None
        
        # Словарь для хранения состояния каждого пользователя
        self.user_states: Dict[int, Dict] = {}
        
        # Множество для отслеживания уже отправленных уведомлений
        self.sent_notifications: Set[tuple] = set()
        
        # Флаг работы глобального цикла
        self.global_loop_running = False
        
        # Application для доступа из глобального цикла
        self.application = None
    
    def load_active_users(self):
        """Загружает список активных пользователей из JSON файла"""
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
        """Сохраняет список активных пользователей в JSON файл"""
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
        """Возвращает список ID всех активных пользователей"""
        return [
            uid for uid, info in self.user_states.items()
            if info.get('is_running', False)
        ]
    
    async def start_global_loop(self):
        """Запускает глобальный цикл проверки матчей (если ещё не запущен)"""
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
        """ГЛАВНЫЙ ЦИКЛ с умным расписанием - НЕ делает запросов когда матчей нет!"""
        logger.info("🔄 Глобальный цикл проверки матчей запущен")
        
        # Загружаем расписание при старте
        await self.scheduler.update_daily_schedule()
        
        # Запускаем автообновление расписания в 00:00
        self.application.create_task(self.scheduler.schedule_daily_update())
        
        iteration = 0
        
        while self.global_loop_running:
            # Проверяем есть ли активные пользователи
            active_users = self.get_active_user_ids()
            
            if not active_users:
                logger.info("⚠️ Нет активных пользователей. Останавливаю глобальный цикл.")
                self.global_loop_running = False
                break
            
            try:
                # УМНАЯ ОПТИМИЗАЦИЯ: Проверяем нужно ли делать запросы СЕЙЧАС
                if not self.scheduler.should_check_now():
                    # НЕТ матчей сейчас - СПИМ до следующего окна
                    sleep_seconds = self.scheduler.get_time_until_next_check()
                    
                    if sleep_seconds and sleep_seconds > 0:
                        sleep_hours = sleep_seconds / 3600
                        sleep_minutes = (sleep_seconds % 3600) / 60
                        
                        now_moscow = datetime.now(self.scheduler.moscow_tz)
                        wake_time = now_moscow + timedelta(seconds=sleep_seconds)
                        
                        logger.info(
                            f"😴 НЕТ матчей для проверки. "
                            f"СПИМ {int(sleep_hours)}ч {int(sleep_minutes)}мин до {wake_time.strftime('%H:%M')} МСК"
                        )
                        
                        # СПИМ до начала следующего матча (БЕЗ ЗАПРОСОВ!)
                        await asyncio.sleep(sleep_seconds)
                        
                        logger.info(f"⏰ ПРОСНУЛИСЬ! Начинаем проверку матчей...")
                        continue
                    else:
                        # Нет матчей вообще - короткий сон
                        logger.info("💤 Нет запланированных матчей. Сон 5 минут...")
                        await asyncio.sleep(300)
                        continue
                
                # Если дошли сюда - ЕСТЬ матчи для проверки прямо СЕЙЧАС
                iteration += 1
                
                active_count = self.scheduler.get_active_matches_count()
                logger.info(
                    f"[Итерация {iteration}] ⚽ Проверка матчей для {len(active_users)} пользователей. "
                    f"Активных матчей: {active_count}"
                )
                
                # Делаем запрос live матчей
                matches = await self.api.get_live_matches()
                
                # Проверка квоты
                if matches and isinstance(matches, list) and len(matches) > 0:
                    if matches[0].get('quota_exceeded'):
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
                
                # Короткий интервал во время матчей
                wait_time = CHECK_INTERVAL_ACTIVE
                logger.info(f"[Итерация {iteration}] ✅ Следующая проверка через {wait_time}с")
                
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в глобальном цикле: {e}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(CHECK_INTERVAL_ACTIVE)
        
        logger.info("⏹ Глобальный цикл проверки завершён")
    
    async def process_match_for_all_users(self, match: Dict, active_users: list):
        """Обрабатывает один матч для ВСЕХ активных пользователей"""
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
                # Проверяем что это гол
                if not self.notification_manager.is_goal_event(event):
                    continue
                
                minute = event.get('time', {}).get('elapsed', 0)
                player_name = event.get('player', {}).get('name', '')
                
                # Проверяем для КАЖДОГО пользователя
                for user_id in active_users:
                    # Уникальный ключ для этого пользователя и события
                    team_name = event.get('team', {}).get('name', '')
                    event_type = event.get('type', '')
                    detail = event.get('detail', '')
                    
                    event_key = (user_id, fixture_id, minute, player_name, team_name, event_type, detail)
                    
                    # Уже отправляли этому пользователю?
                    if event_key in self.sent_notifications:
                        continue
                    
                    # Определяем нужно ли уведомление
                    should_notify = False
                    mode_name = ""
                    
                    # Режим "70 минута" - только первый гол на 69-70 минуте
                    if self.notification_manager.should_notify_70_minute_mode(minute, match_info, event):
                        should_notify = True
                        mode_name = MODE_70_MINUTE['name']
                    
                    # Режим "Пенальти 2-10 мин" - пенальти на 2-10 минуте
                    elif self.notification_manager.should_notify_penalty_early_mode(minute, event):
                        should_notify = True
                        mode_name = MODE_PENALTY_EARLY['name']
                    
                    # Отправляем уведомление
                    if should_notify:
                        try:
                            notification_text = self.notification_manager.create_goal_notification(
                                match_info, 
                                event, 
                                mode_name
                            )
                            
                            await self.application.bot.send_message(
                                chat_id=user_id,
                                text=notification_text,
                                parse_mode='Markdown',
                                disable_web_page_preview=True
                            )
                            
                            self.sent_notifications.add(event_key)
                            
                            logger.info(
                                f"⚽ Уведомление → {user_id}: "
                                f"{match_info.get('home_team', '?')} vs {match_info.get('away_team', '?')}, "
                                f"мин {minute}, режим: {mode_name}"
                            )
                        except Exception as e:
                            logger.error(f"❌ Ошибка отправки уведомления {user_id}: {e}")
                            import traceback
                            logger.error(traceback.format_exc())
        
        except Exception as e:
            logger.error(f"❌ Ошибка обработки матча: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    @private_access_required
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
        
        # Отправляем приветственное сообщение
        welcome_message = MESSAGES['welcome'].format(name=user.first_name)
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        
        logger.info(f"🚀 Бот запущен для {user_id} ({user.first_name})")
        
        # Запускаем глобальный цикл (если ещё не запущен)
        await self.start_global_loop()
    
    @private_access_required
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
    
    @private_access_required
    async def games_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /games - показывает матчи на сегодня"""
        try:
            import pytz
            
            if not self.scheduler or not self.scheduler.today_fixtures:
                await update.message.reply_text("⚠️ Расписание матчей ещё не загружено. Попробуйте позже.")
                return
            
            fixtures = self.scheduler.today_fixtures
            
            # Фильтруем только активные (не завершённые)
            active_fixtures = [
                f for f in fixtures
                if f.get('fixture', {}).get('status', {}).get('short') not in ['FT', 'AET', 'PEN', 'CANC', 'ABD', 'AWD', 'WO']
            ]
            
            total_count = len(active_fixtures)
            
            if total_count == 0:
                await update.message.reply_text("📅 На сегодня матчей не запланировано или все завершены.")
                return
            
            # Берём только первые 5
            display_fixtures = active_fixtures[:5]
            
            # Формируем сообщение
            today_date = datetime.now().strftime('%d.%m.%Y')
            message = f"📅 **Матчи на {today_date}**\n\n"
            message += f"📊 **Всего матчей:** {total_count}\n\n"
            
            try:
                from translations import translate_team, translate_league
            except:
                def translate_team(name):
                    return name
                def translate_league(name, country=None):
                    return name
            
            for idx, fixture in enumerate(display_fixtures, 1):
                try:
                    home = fixture.get('teams', {}).get('home', {}).get('name', '?')
                    away = fixture.get('teams', {}).get('away', {}).get('name', '?')
                    league = fixture.get('league', {}).get('name', '?')
                    league_country = fixture.get('league', {}).get('country', '')
                    
                    # Переводим
                    home_ru = translate_team(home)
                    away_ru = translate_team(away)
                    league_ru = translate_league(league, league_country)
                    
                    # Время матча
                    fixture_date_str = fixture.get('fixture', {}).get('date')
                    
                    if fixture_date_str:
                        try:
                            utc_time = datetime.fromisoformat(fixture_date_str.replace('Z', '+00:00'))
                            moscow_tz = pytz.timezone('Europe/Moscow')
                            moscow_time = utc_time.astimezone(moscow_tz)
                            time_str = moscow_time.strftime('%H:%M')
                        except:
                            time_str = "TBD"
                    else:
                        time_str = "TBD"
                    
                    # Статус
                    status = fixture.get('fixture', {}).get('status', {}).get('short', 'NS')
                    
                    if status in ['1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE']:
                        status_emoji = "🔴"
                        elapsed = fixture.get('fixture', {}).get('status', {}).get('elapsed', '')
                        if elapsed:
                            time_str = f"{elapsed}'"
                    else:
                        status_emoji = "🕐"
                    
                    message += f"{status_emoji} **{home_ru}** — **{away_ru}**\n"
                    message += f"   _{league_ru}_ | {time_str}\n\n"
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка форматирования матча: {e}")
                    continue
            
            if total_count > 5:
                message += f"_... и ещё {total_count - 5} матчей_"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"❌ Ошибка в команде /games: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await update.message.reply_text("❌ Ошибка при получении списка матчей")
    
    async def cleanup(self):
        """Очистка ресурсов"""
        await self.api.close_session()
        logger.info("🧹 Ресурсы очищены")
    
    def start(self):
        """Запуск бота"""
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Сохраняем ссылку на application
        self.application = application
        
        # Инициализируем планировщик
        from scheduler import MatchScheduler
        self.scheduler = MatchScheduler(self.api)
        
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("stop", self.stop_command))
        application.add_handler(CommandHandler("games", self.games_command))
        application.add_error_handler(error_handler)
        
        logger.info(f"🤖 Бот запущен!")
        logger.info(f"⚡ Интервал проверки: {CHECK_INTERVAL_ACTIVE}с (активные) / {CHECK_INTERVAL_IDLE}с (неактивные)")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )


def main():
    """Главная функция"""
    bot = FootballBot()
    
    try:
        bot.start()
    except KeyboardInterrupt:
        logger.info("⚠️ Получен сигнал остановки")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    finally:
        asyncio.run(bot.cleanup())
        logger.info("👋 Бот завершил работу")


if __name__ == '__main__':
    main()