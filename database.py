"""
Модуль для работы с PostgreSQL базой данных
"""
import os
import logging
import asyncpg
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class Database:
    """Класс для работы с базой данных пользователей"""

    def __init__(self):
        # Railway автоматически добавляет DATABASE_URL
        self.database_url = os.getenv('DATABASE_URL')
        self.pool = None

    async def connect(self):
        """Подключение к базе данных"""
        try:
            if not self.database_url:
                logger.warning("⚠️ DATABASE_URL не найден. Используется файловое хранилище.")
                return False

            # Создаём пул подключений
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=10,
                command_timeout=60
            )

            # Создаём таблицу если её нет
            await self.create_tables()

            logger.info("✅ Подключение к PostgreSQL установлено")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
            return False

    async def create_tables(self):
        """Создаёт таблицы в базе данных"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS active_users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT NOT NULL,
                    is_running BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            ''')

            logger.info("✅ Таблицы созданы/проверены")

    async def save_user(self, user_id: int, username: str, is_running: bool = True):
        """
        Сохраняет или обновляет пользователя

        Args:
            user_id: Telegram ID пользователя
            username: Имя пользователя
            is_running: Активен ли бот для пользователя
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO active_users (user_id, username, is_running, updated_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (user_id) 
                    DO UPDATE SET 
                        username = $2,
                        is_running = $3,
                        updated_at = NOW()
                ''', user_id, username, is_running)

            logger.info(f"💾 Пользователь {user_id} ({username}) сохранён в БД")

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения пользователя {user_id}: {e}")

    async def get_active_users(self) -> List[Dict]:
        """
        Получает список активных пользователей

        Returns:
            Список словарей с данными пользователей
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT user_id, username, created_at, updated_at
                    FROM active_users
                    WHERE is_running = TRUE
                    ORDER BY user_id
                ''')

                users = [
                    {
                        'user_id': row['user_id'],
                        'username': row['username'],
                        'saved_at': row['updated_at'].isoformat()
                    }
                    for row in rows
                ]

                logger.info(f"📂 Загружено {len(users)} активных пользователей из БД")
                return users

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки пользователей: {e}")
            return []

    async def deactivate_user(self, user_id: int):
        """
        Деактивирует пользователя (но не удаляет из БД)

        Args:
            user_id: Telegram ID пользователя
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE active_users
                    SET is_running = FALSE, updated_at = NOW()
                    WHERE user_id = $1
                ''', user_id)

            logger.info(f"⛔ Пользователь {user_id} деактивирован в БД")

        except Exception as e:
            logger.error(f"❌ Ошибка деактивации пользователя {user_id}: {e}")

    async def get_user(self, user_id: int) -> Optional[Dict]:
        """
        Получает данные одного пользователя

        Args:
            user_id: Telegram ID пользователя

        Returns:
            Словарь с данными или None
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT user_id, username, is_running, created_at, updated_at
                    FROM active_users
                    WHERE user_id = $1
                ''', user_id)

                if row:
                    return {
                        'user_id': row['user_id'],
                        'username': row['username'],
                        'is_running': row['is_running'],
                        'created_at': row['created_at'].isoformat(),
                        'updated_at': row['updated_at'].isoformat()
                    }

                return None

        except Exception as e:
            logger.error(f"❌ Ошибка получения пользователя {user_id}: {e}")
            return None

    async def close(self):
        """Закрывает подключение к базе данных"""
        if self.pool:
            await self.pool.close()
            logger.info("🔌 Подключение к PostgreSQL закрыто")