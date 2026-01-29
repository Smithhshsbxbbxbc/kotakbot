#!/usr/bin/env python3
"""
КОТАК BOT - симулятор взрослой жизни в Telegram-чатах
Все данные хранятся в SQLite файле kotak_db.sqlite в той же директории
"""

import logging
import sqlite3
import random
import asyncio
import datetime
import yaml
import os
from typing import Dict, List, Tuple, Optional
from enum import Enum
from dataclasses import dataclass
from contextlib import contextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ==================== КОНФИГУРАЦИЯ ====================
TOKEN = "8570375501:AAFabraVld-YR47Q4w-lUq9ziUWX-VzEcCE"  # Твой токен
DB_FILE = "kotak_db.sqlite"
LOG_FILE = "kotak.log"
CONFIG_FILE = "kotak_config.yaml"

# Настройки по умолчанию
DEFAULT_CONFIG = {
    "game": {
        "quiz_interval": 300,  # 5 минут
        "salary_interval": 3600,  # 1 час
        "decay_interval": 1800,  # 30 минут
        "start_balance": 1000,
        "quiz_reward": 50,
        "work_reward": 200,
        "server_income": 10,
        "max_health": 100,
        "max_energy": 100
    },
    "prices": {
        "food": 50,
        "medicine": 100,
        "entertainment": 80,
        "server_upgrade": 500,
        "girlfriend_gift": 300,
        "pet_food": 40,
        "car": 5000,
        "house": 20000,
        "business": 10000
    }
}

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
class Database:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.init_db()
        return cls._instance
    
    def init_db(self):
        """Инициализация базы данных"""
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        
        # Основные таблицы
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 1000,
                health INTEGER DEFAULT 100,
                energy INTEGER DEFAULT 100,
                happiness INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS chat_users (
                chat_id INTEGER,
                user_id INTEGER,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id)
            );
            
            CREATE TABLE IF NOT EXISTS user_properties (
                user_id INTEGER PRIMARY KEY,
                has_girlfriend BOOLEAN DEFAULT 0,
                girlfriend_happiness INTEGER DEFAULT 0,
                has_pet BOOLEAN DEFAULT 0,
                pet_hunger INTEGER DEFAULT 0,
                has_car BOOLEAN DEFAULT 0,
                car_condition INTEGER DEFAULT 0,
                has_house BOOLEAN DEFAULT 0,
                house_comfort INTEGER DEFAULT 0,
                has_business BOOLEAN DEFAULT 0,
                business_level INTEGER DEFAULT 0
            );
            
            CREATE TABLE IF NOT EXISTS servers (
                user_id INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1,
                income INTEGER DEFAULT 10,
                last_collected TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS jobs (
                user_id INTEGER PRIMARY KEY,
                job_type TEXT DEFAULT 'безработный',
                salary INTEGER DEFAULT 0,
                last_worked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                stress_level INTEGER DEFAULT 0
            );
            
            CREATE TABLE IF NOT EXISTS inventory (
                user_id INTEGER,
                item_type TEXT,
                quantity INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, item_type)
            );
            
            CREATE TABLE IF NOT EXISTS events_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                event_type TEXT,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                question TEXT,
                answer TEXT,
                reward INTEGER DEFAULT 50,
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        self.conn.commit()
        logger.info("База данных инициализирована")
    
    def execute(self, query: str, params: tuple = ()):
        """Выполнить SQL-запрос"""
        try:
            self.cursor.execute(query, params)
            self.conn.commit()
            return self.cursor
        except Exception as e:
            logger.error(f"Ошибка БД: {e}")
            self.conn.rollback()
            raise
    
    def fetch_one(self, query: str, params: tuple = ()):
        """Получить одну запись"""
        self.cursor.execute(query, params)
        return self.cursor.fetchone()
    
    def fetch_all(self, query: str, params: tuple = ()):
        """Получить все записи"""
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

# ==================== ИГРОВЫЕ КЛАССЫ ====================
class GameState:
    """Состояние игрока"""
    
    def __init__(self, user_id: int):
        self.db = Database()
        self.user_id = user_id
        
    def get_user(self):
        row = self.db.fetch_one("SELECT * FROM users WHERE user_id = ?", (self.user_id,))
        if not row:
            self.db.execute(
                "INSERT INTO users (user_id, balance, health, energy, happiness) VALUES (?, 1000, 100, 100, 100)",
                (self.user_id,)
            )
            row = self.db.fetch_one("SELECT * FROM users WHERE user_id = ?", (self.user_id,))
        return dict(row)
    
    def get_properties(self):
        row = self.db.fetch_one("SELECT * FROM user_properties WHERE user_id = ?", (self.user_id,))
        if not row:
            self.db.execute(
                "INSERT INTO user_properties (user_id) VALUES (?)",
                (self.user_id,)
            )
            row = self.db.fetch_one("SELECT * FROM user_properties WHERE user_id = ?", (self.user_id,))
        return dict(row)
    
    def get_server(self):
        row = self.db.fetch_one("SELECT * FROM servers WHERE user_id = ?", (self.user_id,))
        if not row:
            self.db.execute(
                "INSERT INTO servers (user_id, level, income) VALUES (?, 1, 10)",
                (self.user_id,)
            )
            row = self.db.fetch_one("SELECT * FROM servers WHERE user_id = ?", (self.user_id,))
        return dict(row)
    
    def get_job(self):
        row = self.db.fetch_one("SELECT * FROM jobs WHERE user_id = ?", (self.user_id,))
        if not row:
            self.db.execute(
                "INSERT INTO jobs (user_id, job_type, salary) VALUES (?, 'безработный', 0)",
                (self.user_id,)
            )
            row = self.db.fetch_one("SELECT * FROM jobs WHERE user_id = ?", (self.user_id,))
        return dict(row)
    
    def update_balance(self, amount: int):
        user = self.get_user()
        new_balance = user['balance'] + amount
        self.db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, self.user_id))
        return new_balance
    
    def update_stat(self, stat: str, amount: int):
        """Обновить здоровье, энергию или счастье"""
        user = self.get_user()
        current = user.get(stat, 100)
        new_value = max(0, min(100, current + amount))
        self.db.execute(f"UPDATE users SET {stat} = ? WHERE user_id = ?", (new_value, self.user_id))
        return new_value
    
    def add_to_inventory(self, item_type: str, quantity: int = 1):
        self.db.execute('''
            INSERT OR REPLACE INTO inventory (user_id, item_type, quantity)
            VALUES (?, ?, COALESCE((SELECT quantity FROM inventory WHERE user_id = ? AND item_type = ?), 0) + ?)
        ''', (self.user_id, item_type, self.user_id, item_type, quantity))
    
    def log_event(self, chat_id: int, event_type: str, message: str):
        self.db.execute(
            "INSERT INTO events_log (chat_id, user_id, event_type, message) VALUES (?, ?, ?, ?)",
            (chat_id, self.user_id, event_type, message)
        )

# ==================== ИГРОВАЯ ЛОГИКА ====================
class GameEngine:
    """Движок игры"""
    
    QUIZ_QUESTIONS = [
        ("5 - 2 = ?", "3"),
        ("10 + 7 = ?", "17"),
        ("3 × 4 = ?", "12"),
        ("15 ÷ 3 = ?", "5"),
        ("2² = ?", "4"),
        ("√9 = ?", "3"),
        ("7 + 8 = ?", "15"),
        ("20 - 11 = ?", "9"),
        ("6 × 3 = ?", "18"),
        ("100 ÷ 10 = ?", "10")
    ]
    
    JOBS = [
        ("грузчик", 150, 5),
        ("официант", 200, 10),
        ("программист", 500, 15),
        ("менеджер", 400, 20),
        ("дизайнер", 350, 10),
        ("водій", 300, 15),
        ("строитель", 250, 20),
        ("учитель", 280, 10)
    ]
    
    @staticmethod
    def create_quiz(chat_id: int) -> dict:
        """Создать новую викторину"""
        db = Database()
        question, answer = random.choice(GameEngine.QUIZ_QUESTIONS)
        reward = random.randint(30, 70)
        
        db.execute(
            "INSERT INTO quizzes (chat_id, question, answer, reward) VALUES (?, ?, ?, ?)",
            (chat_id, question, answer, reward)
        )
        
        return {
            "question": question,
            "answer": answer,
            "reward": reward,
            "quiz_id": db.cursor.lastrowid
        }
    
    @staticmethod
    def check_quiz_answer(quiz_id: int, user_answer: str) -> Tuple[bool, int]:
        """Проверить ответ на викторину"""
        db = Database()
        quiz = db.fetch_one("SELECT * FROM quizzes WHERE id = ? AND active = 1", (quiz_id,))
        
        if not quiz:
            return False, 0
        
        is_correct = user_answer.strip() == quiz['answer']
        if is_correct:
            db.execute("UPDATE quizzes SET active = 0 WHERE id = ?", (quiz_id,))
            
        return is_correct, quiz['reward'] if is_correct else 0
    
    @staticmethod
    def get_random_event() -> Tuple[str, str, Dict]:
        """Случайное жизненное событие"""
        events = [
            ("удача", "Вы нашли деньги на улице!", {"balance": random.randint(50, 200)}),
            ("болезнь", "Вы простудились...", {"health": -random.randint(10, 30)}),
            ("усталость", "Переработали...", {"energy": -random.randint(20, 40)}),
            ("радость", "Встретили старого друга!", {"happiness": random.randint(10, 30)}),
            ("проблема", "Сломалась машина", {"balance": -random.randint(100, 300)}),
            ("доход", "Сервер принес прибыль", {"balance": random.randint(20, 100)}),
            ("скандал", "Девушка обиделась...", {"happiness": -random.randint(20, 40)}),
            ("питомец", "Питомец голоден!", {"happiness": -random.randint(10, 20)}),
            ("работа", "Получили премию!", {"balance": random.randint(200, 500)}),
            ("отдых", "Хорошо отдохнули", {"energy": random.randint(20, 40)})
        ]
        return random.choice(events)
    
    @staticmethod
    def decay_stats(user_id: int):
        """Естественная деградация показателей"""
        state = GameState(user_id)
        
        # Шанс ухудшения каждого показателя
        if random.random() < 0.3:
            state.update_stat("health", -random.randint(1, 5))
        if random.random() < 0.4:
            state.update_stat("energy", -random.randint(2, 8))
        if random.random() < 0.3:
            state.update_stat("happiness", -random.randint(1, 6))
        
        # Если есть девушка - может обидеться
        props = state.get_properties()
        if props['has_girlfriend'] and random.random() < 0.2:
            new_happiness = max(0, props['girlfriend_happiness'] - random.randint(5, 15))
            db = Database()
            db.execute(
                "UPDATE user_properties SET girlfriend_happiness = ? WHERE user_id = ?",
                (new_happiness, user_id)
            )
            return "👫 Девушка скучает без внимания..."
        
        # Если есть питомец - хочет есть
        if props['has_pet'] and random.random() < 0.3:
            new_hunger = min(100, props['pet_hunger'] + random.randint(10, 30))
            db = Database()
            db.execute(
                "UPDATE user_properties SET pet_hunger = ? WHERE user_id = ?",
                (new_hunger, user_id)
            )
            return "🐶 Питомец голоден!"
        
        return None

# ==================== КЛАВИАТУРЫ ====================
class Keyboards:
    """Клавиатуры для бота"""
    
    @staticmethod
    def main_menu():
        keyboard = [
            [
                InlineKeyboardButton("💰 Профиль", callback_data="profile"),
                InlineKeyboardButton("💼 Работа", callback_data="work")
            ],
            [
                InlineKeyboardButton("🛒 Магазин", callback_data="shop"),
                InlineKeyboardButton("🏠 Дом", callback_data="house")
            ],
            [
                InlineKeyboardButton("👫 Отношения", callback_data="relationships"),
                InlineKeyboardButton("🐶 Питомцы", callback_data="pets")
            ],
            [
                InlineKeyboardButton("💻 Сервер", callback_data="server"),
                InlineKeyboardButton("📊 Бизнес", callback_data="business")
            ],
            [
                InlineKeyboardButton("📈 Топ игроков", callback_data="top"),
                InlineKeyboardButton("❓ Помощь", callback_data="help")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def shop_menu():
        keyboard = [
            [
                InlineKeyboardButton("🍔 Еда (-50₽)", callback_data="buy_food"),
                InlineKeyboardButton("💊 Лекарство (-100₽)", callback_data="buy_medicine")
            ],
            [
                InlineKeyboardButton("🎮 Развлечения (-80₽)", callback_data="buy_entertainment"),
                InlineKeyboardButton("🎁 Подарок девушке (-300₽)", callback_data="buy_gift")
            ],
            [
                InlineKeyboardButton("🖥️ Апгрейд сервера (-500₽)", callback_data="upgrade_server"),
                InlineKeyboardButton("🚗 Купить машину (-5000₽)", callback_data="buy_car")
            ],
            [
                InlineKeyboardButton("🏡 Купить дом (-20000₽)", callback_data="buy_house"),
                InlineKeyboardButton("💼 Открыть бизнес (-10000₽)", callback_data="buy_business")
            ],
            [
                InlineKeyboardButton("🔙 Назад", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def work_menu():
        keyboard = []
        db = Database()
        jobs = db.fetch_all("SELECT * FROM jobs WHERE user_id = ?", (0,))  # Заглушка
        
        for job_name, salary, stress in GameEngine.JOBS:
            keyboard.append([
                InlineKeyboardButton(f"{job_name} ({salary}₽)", callback_data=f"job_{job_name}")
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def confirm_keyboard(action: str):
        keyboard = [
            [
                InlineKeyboardButton("✅ Да", callback_data=f"confirm_{action}"),
                InlineKeyboardButton("❌ Нет", callback_data="cancel")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

# ==================== ОСНОВНОЙ БОТ ====================
class KotakBot:
    """Главный класс бота"""
    
    def __init__(self):
        self.db = Database()
        self.active_quizzes = {}
        self.config = self.load_config()
        
    def load_config(self):
        """Загрузить или создать конфиг"""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        else:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True)
            return DEFAULT_CONFIG
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        if update.effective_chat.type == "private":
            await update.message.reply_text(
                "🚫 КОТАК BOT работает только в групповых чатах!\n"
                "Добавьте меня в группу и используйте /help для инструкций."
            )
            return
            
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.full_name
        
        # Регистрация пользователя в чате
        self.db.execute(
            "INSERT OR REPLACE INTO chat_users (chat_id, user_id, last_active) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (update.effective_chat.id, user_id)
        )
        
        # Создание профиля если нет
        state = GameState(user_id)
        state.get_user()  # Создаст если нет
        
        welcome_text = (
            f"🐱 *Добро пожаловать в КОТАК BOT!*\n\n"
            f"Привет, {username}! Это симулятор взрослой жизни.\n"
            f"Зарабатывай деньги, заводи отношения, покупай имущество.\n"
            f"Но помни: за всем нужно ухаживать!\n\n"
            f"*Основные команды:*\n"
            f"/menu - Основное меню\n"
            f"/work - Работать\n"
            f"/shop - Магазин\n"
            f"/profile - Твой профиль\n"
            f"/server - Твой сервер\n\n"
            f"*Каждые 5 минут:* викторина с деньгами!\n"
            f"*Каждый час:* зарплата с работы\n"
            f"*Каждые 30 мин:* показатели падают\n\n"
            f"*Важно:* не следишь за делами → будут проблемы!"
        )
        
        await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=Keyboards.main_menu())
    
    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать главное меню"""
        if update.effective_chat.type == "private":
            await update.message.reply_text("🚫 Бот работает только в чатах!")
            return
            
        await update.message.reply_text(
            "🐱 *КОТАК BOT - Главное меню*\nВыберите раздел:",
            parse_mode='Markdown',
            reply_markup=Keyboards.main_menu()
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        data = query.data
        
        state = GameState(user_id)
        user = state.get_user()
        props = state.get_properties()
        
        if data == "main_menu":
            await query.edit_message_text(
                "🐱 *КОТАК BOT - Главное меню*",
                parse_mode='Markdown',
                reply_markup=Keyboards.main_menu()
            )
            
        elif data == "profile":
            server = state.get_server()
            job = state.get_job()
            
            profile_text = (
                f"👤 *Профиль {query.from_user.username or query.from_user.full_name}*\n\n"
                f"💰 Баланс: *{user['balance']}₽*\n"
                f"❤️ Здоровье: {user['health']}/100\n"
                f"⚡ Энергия: {user['energy']}/100\n"
                f"😊 Счастье: {user['happiness']}/100\n\n"
                f"💼 Работа: *{job['job_type']}* ({job['salary']}₽/час)\n"
                f"💻 Сервер: уровень {server['level']} (+{server['income']}₽/час)\n\n"
                f"🏠 Недвижимость: {'Есть' if props['has_house'] else 'Нет'}\n"
                f"🚗 Машина: {'Есть' if props['has_car'] else 'Нет'}\n"
                f"👫 Девушка: {'Есть' if props['has_girlfriend'] else 'Нет'}\n"
                f"🐶 Питомец: {'Есть' if props['has_pet'] else 'Нет'}\n"
                f"💼 Бизнес: {'Есть' if props['has_business'] else 'Нет'}"
            )
            
            await query.edit_message_text(profile_text, parse_mode='Markdown', reply_markup=Keyboards.main_menu())
            
        elif data == "shop":
            await query.edit_message_text(
                "🛒 *Магазин КОТАК*\nВыберите что купить:",
                parse_mode='Markdown',
                reply_markup=Keyboards.shop_menu()
            )
            
        elif data == "work":
            await query.edit_message_text(
                "💼 *Поиск работы*\nВыберите профессию:",
                parse_mode='Markdown',
                reply_markup=Keyboards.work_menu()
            )
            
        elif data.startswith("job_"):
            job_name = data[4:]
            for job, salary, stress in GameEngine.JOBS:
                if job == job_name:
                    self.db.execute(
                        "UPDATE jobs SET job_type = ?, salary = ?, stress_level = ? WHERE user_id = ?",
                        (job_name, salary, stress, user_id)
                    )
                    
                    await query.edit_message_text(
                        f"✅ Вы устроились на работу *{job_name}*!\n"
                        f"Зарплата: *{salary}₽* в час\n"
                        f"Стресс: +{stress}% при работе\n\n"
                        f"Используйте /work чтобы поработать сейчас.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.main_menu()
                    )
                    break
                    
        elif data == "buy_food":
            if user['balance'] >= 50:
                state.update_balance(-50)
                state.update_stat("health", 10)
                state.update_stat("energy", 15)
                await query.edit_message_text(
                    "🍔 Вы поели! (+10❤️, +15⚡)\nБаланс: -50₽",
                    reply_markup=Keyboards.main_menu()
                )
            else:
                await query.edit_message_text(
                    "❌ Недостаточно денег!",
                    reply_markup=Keyboards.main_menu()
                )
                
        elif data == "buy_medicine":
            if user['balance'] >= 100:
                state.update_balance(-100)
                state.update_stat("health", 30)
                await query.edit_message_text(
                    "💊 Вы полечились! (+30❤️)\nБаланс: -100₽",
                    reply_markup=Keyboards.main_menu()
                )
            else:
                await query.edit_message_text("❌ Недостаточно денег!", reply_markup=Keyboards.main_menu())
                
        elif data == "upgrade_server":
            if user['balance'] >= 500:
                server = state.get_server()
                new_level = server['level'] + 1
                new_income = server['income'] + 15
                
                state.update_balance(-500)
                self.db.execute(
                    "UPDATE servers SET level = ?, income = ? WHERE user_id = ?",
                    (new_level, new_income, user_id)
                )
                
                await query.edit_message_text(
                    f"🖥️ Сервер улучшен до уровня {new_level}!\n"
                    f"Доход: +{new_income}₽ в час\n"
                    f"Баланс: -500₽",
                    reply_markup=Keyboards.main_menu()
                )
            else:
                await query.edit_message_text("❌ Недостаточно денег!", reply_markup=Keyboards.main_menu())
                
        elif data == "buy_gift":
            if not props['has_girlfriend']:
                await query.edit_message_text("❌ У вас нет девушки!", reply_markup=Keyboards.main_menu())
                return
                
            if user['balance'] >= 300:
                state.update_balance(-300)
                new_happiness = min(100, props['girlfriend_happiness'] + 40)
                self.db.execute(
                    "UPDATE user_properties SET girlfriend_happiness = ? WHERE user_id = ?",
                    (new_happiness, user_id)
                )
                
                await query.edit_message_text(
                    f"🎁 Вы подарили подарок девушке!\n"
                    f"Ее настроение: {new_happiness}/100\n"
                    f"Баланс: -300₽",
                    reply_markup=Keyboards.main_menu()
                )
            else:
                await query.edit_message_text("❌ Недостаточно денег!", reply_markup=Keyboards.main_menu())
                
        elif data == "buy_car":
            if props['has_car']:
                await query.edit_message_text("❌ У вас уже есть машина!", reply_markup=Keyboards.main_menu())
                return
                
            if user['balance'] >= 5000:
                state.update_balance(-5000)
                self.db.execute(
                    "UPDATE user_properties SET has_car = 1, car_condition = 100 WHERE user_id = ?",
                    (user_id,)
                )
                
                await query.edit_message_text(
                    "🚗 Поздравляем с покупкой машины!\n"
                    "Теперь вы можете быстрее добираться на работу.\n"
                    "Баланс: -5000₽",
                    reply_markup=Keyboards.main_menu()
                )
            else:
                await query.edit_message_text("❌ Недостаточно денег!", reply_markup=Keyboards.main_menu())
                
        elif data == "relationships":
            if not props['has_girlfriend']:
                if user['balance'] >= 1000:
                    await query.edit_message_text(
                        "👫 *Знакомство с девушкой*\nСтоимость: 1000₽\n"
                        "Вы хотите познакомиться с девушкой?",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.confirm_keyboard("girlfriend")
                    )
                else:
                    await query.edit_message_text(
                        "❌ Для знакомства нужно 1000₽!",
                        reply_markup=Keyboards.main_menu()
                    )
            else:
                rel_text = (
                    f"👫 *Ваши отношения*\n\n"
                    f"Настроение девушки: {props['girlfriend_happiness']}/100\n\n"
                    f"*Советы:*\n"
                    f"• Дарите подарки (+40 настроения)\n"
                    f"• Игнорирование: -5/час\n"
                    f"• При 0 настроении: она уйдет!"
                )
                await query.edit_message_text(rel_text, parse_mode='Markdown', reply_markup=Keyboards.main_menu())
                
        elif data == "confirm_girlfriend":
            if user['balance'] >= 1000:
                state.update_balance(-1000)
                self.db.execute(
                    "UPDATE user_properties SET has_girlfriend = 1, girlfriend_happiness = 80 WHERE user_id = ?",
                    (user_id,)
                )
                
                await query.edit_message_text(
                    "👫 Поздравляем! У вас теперь есть девушка!\n"
                    "Начальное настроение: 80/100\n"
                    "Не забывайте уделять ей внимание!\n"
                    "Баланс: -1000₽",
                    reply_markup=Keyboards.main_menu()
                )
            else:
                await query.edit_message_text("❌ Недостаточно денег!", reply_markup=Keyboards.main_menu())
                
        elif data == "server":
            server = state.get_server()
            server_text = (
                f"💻 *Ваш сервер*\n\n"
                f"Уровень: *{server['level']}*\n"
                f"Доход: *+{server['income']}₽* в час\n"
                f"Всего заработано: {server['income'] * 24 * server['level']}₽\n\n"
                f"*Улучшение:*\n"
                f"Стоимость: 500₽ за уровень\n"
                f"+15₽/час за каждый уровень\n\n"
                f"Сервер приносит деньги даже когда вы offline!"
            )
            await query.edit_message_text(server_text, parse_mode='Markdown', reply_markup=Keyboards.main_menu())
            
        elif data == "top":
            top_users = self.db.fetch_all('''
                SELECT u.user_id, u.balance, u.health, u.happiness 
                FROM users u
                JOIN chat_users cu ON u.user_id = cu.user_id AND cu.chat_id = ?
                ORDER BY u.balance DESC 
                LIMIT 10
            ''', (chat_id,))
            
            top_text = "🏆 *Топ-10 игроков чата*\n\n"
            for i, row in enumerate(top_users, 1):
                top_text += f"{i}. ID{row['user_id']}: {row['balance']}₽ (❤️{row['health']} 😊{row['happiness']})\n"
                
            await query.edit_message_text(top_text, parse_mode='Markdown', reply_markup=Keyboards.main_menu())
            
        elif data == "help":
            help_text = (
                "🐱 *КОТАК BOT - Помощь*\n\n"
                "*Основные принципы:*\n"
                "1. Зарабатывайте деньги (работа, сервер, викторины)\n"
                "2. Тратьте на улучшение жизни\n"
                "3. Следите за показателями\n"
                "4. Не забывайте про отношения\n\n"
                "*Показатели:*\n"
                "❤️ Здоровье: еда, лекарства\n"
                "⚡ Энергия: отдых, сон\n"
                "😊 Счастье: развлечения, отношения\n\n"
                "*Автоматические события:*\n"
                "• Викторина: каждые 5 минут\n"
                "• Зарплата: каждый час\n"
                "• Ухудшение показателей: каждые 30 мин\n"
                "• События: случайные\n\n"
                "*Важно:* Все взаимосвязано!\n"
                "Игнорируете что-то → будут проблемы!"
            )
            await query.edit_message_text(help_text, parse_mode='Markdown', reply_markup=Keyboards.main_menu())
            
        elif data == "cancel":
            await query.edit_message_text(
                "❌ Действие отменено",
                reply_markup=Keyboards.main_menu()
            )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщений (для викторин)"""
        if update.effective_chat.type == "private":
            return
            
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text.strip()
        
        # Проверка активных викторин
        active_quiz = self.db.fetch_one(
            "SELECT * FROM quizzes WHERE chat_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
            (chat_id,)
        )
        
        if active_quiz:
            is_correct, reward = GameEngine.check_quiz_answer(active_quiz['id'], text)
            if is_correct:
                state = GameState(user_id)
                new_balance = state.update_balance(reward)
                
                await update.message.reply_text(
                    f"✅ {update.effective_user.full_name} ответил правильно!\n"
                    f"🎁 Награда: +{reward}₽\n"
                    f"💰 Новый баланс: {new_balance}₽"
                )
                
                # Создаем новую викторину через 5 минут
                context.job_queue.run_once(
                    self.create_new_quiz,
                    300,  # 5 минут
                    chat_id=chat_id,
                    data={"chat_id": chat_id}
                )
    
    async def create_new_quiz(self, context: ContextTypes.DEFAULT_TYPE):
        """Создать новую викторину"""
        chat_id = context.job.data["chat_id"]
        quiz = GameEngine.create_quiz(chat_id)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🧠 *ВИКТОРИНА КОТАК!*\n\n{quiz['question']}\n\nПервый правильный ответ: *+{quiz['reward']}₽*",
            parse_mode='Markdown'
        )
    
    async def hourly_salary(self, context: ContextTypes.DEFAULT_TYPE):
        """Выдача зарплаты каждый час"""
        db = Database()
        chat_id = context.job.data["chat_id"]
        
        # Найти всех пользователей чата с работой
        users = db.fetch_all('''
            SELECT u.user_id, j.salary, j.stress_level 
            FROM users u
            JOIN jobs j ON u.user_id = j.user_id
            JOIN chat_users cu ON u.user_id = cu.user_id AND cu.chat_id = ?
            WHERE j.salary > 0
        ''', (chat_id,))
        
        for user in users:
            state = GameState(user['user_id'])
            salary = user['salary']
            
            # Добавляем деньги
            new_balance = state.update_balance(salary)
            
            # Добавляем стресс
            user_data = state.get_user()
            new_energy = max(0, user_data['energy'] - user['stress_level'] // 10)
            state.update_stat("energy", new_energy - user_data['energy'])
            
            # Логируем
            state.log_event(chat_id, "salary", f"Получена зарплата {salary}₽")
        
        if users:
            await context.bot.send_message(
                chat_id=chat_id,
                text="💼 *ЧАСОВАЯ ЗАРПЛАТА!*\n\nВсе работяги получили зарплату!\nНе забывайте про отдых! ⚡"
            )
    
    async def decay_stats_job(self, context: ContextTypes.DEFAULT_TYPE):
        """Периодическое ухудшение показателей"""
        db = Database()
        chat_id = context.job.data["chat_id"]
        
        # Получаем активных пользователей чата
        users = db.fetch_all('''
            SELECT user_id FROM chat_users 
            WHERE chat_id = ? AND last_active > datetime('now', '-1 day')
        ''', (chat_id,))
        
        messages = []
        for user_row in users:
            user_id = user_row['user_id']
            event_msg = GameEngine.decay_stats(user_id)
            if event_msg:
                messages.append(event_msg)
        
        # Если есть сообщения - отправляем не чаще 1 каждые 30 мин
        if messages and random.random() < 0.3:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ *СОБЫТИЕ КОТАК!*\n\n{random.choice(messages)}\n\nНе забывайте ухаживать за своими делами!"
            )
    
    async def random_events_job(self, context: ContextTypes.DEFAULT_TYPE):
        """Случайные события"""
        chat_id = context.job.data["chat_id"]
        
        if random.random() < 0.2:  # 20% шанс
            event_type, event_msg, effects = GameEngine.get_random_event()
            
            # Выбираем случайного пользователя из чата
            db = Database()
            user = db.fetch_one('''
                SELECT user_id FROM chat_users 
                WHERE chat_id = ? 
                ORDER BY RANDOM() LIMIT 1
            ''', (chat_id,))
            
            if user:
                state = GameState(user['user_id'])
                username = db.fetch_one("SELECT username FROM users WHERE user_id = ?", (user['user_id'],))
                name = username['username'] if username else f"ID{user['user_id']}"
                
                # Применяем эффекты
                result_msg = ""
                if 'balance' in effects:
                    new_bal = state.update_balance(effects['balance'])
                    result_msg += f"💰 Баланс: {effects['balance']}₽\n"
                if 'health' in effects:
                    new_health = state.update_stat("health", effects['health'])
                    result_msg += f"❤️ Здоровье: {effects['health']}\n"
                if 'energy' in effects:
                    new_energy = state.update_stat("energy", effects['energy'])
                    result_msg += f"⚡ Энергия: {effects['energy']}\n"
                if 'happiness' in effects:
                    new_happy = state.update_stat("happiness", effects['happiness'])
                    result_msg += f"😊 Счастье: {effects['happiness']}\n"
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🎲 *СЛУЧАЙНОЕ СОБЫТИЕ!*\n\n{name}:\n{event_msg}\n\n{result_msg}"
                )
    
    async def collect_server_income(self, context: ContextTypes.DEFAULT_TYPE):
        """Сбор дохода с серверов"""
        db = Database()
        chat_id = context.job.data["chat_id"]
        
        servers = db.fetch_all('''
            SELECT s.user_id, s.income, u.username
            FROM servers s
            JOIN users u ON s.user_id = u.user_id
            JOIN chat_users cu ON s.user_id = cu.user_id AND cu.chat_id = ?
            WHERE s.income > 0
        ''', (chat_id,))
        
        if servers:
            total = 0
            for server in servers:
                state = GameState(server['user_id'])
                state.update_balance(server['income'])
                total += server['income']
            
            if random.random() < 0.1:  # 10% шанс уведомления
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"💻 *СЕРВЕРА РАБОТАЮТ!*\n\n"
                    f"Все сервера принесли доход: +{total}₽\n"
                    f"Улучшайте сервера для большего заработка!"
                )
    
    async def work_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /work - разовая работа"""
        if update.effective_chat.type == "private":
            return
            
        user_id = update.effective_user.id
        state = GameState(user_id)
        user = state.get_user()
        job = state.get_job()
        
        if job['job_type'] == 'безработный':
            await update.message.reply_text(
                "❌ Сначала устройтесь на работу через меню!"
            )
            return
            
        if user['energy'] < 20:
            await update.message.reply_text(
                f"😴 Слишком устали! Энергия: {user['energy']}/100\n"
                f"Отдохните или купите еду."
            )
            return
            
        # Заработок
        salary = job['salary'] // 4  # 15 минут работы
        stress = job['stress_level']
        
        new_balance = state.update_balance(salary)
        new_energy = state.update_stat("energy", -20)
        new_happy = state.update_stat("happiness", -stress // 20)
        
        await update.message.reply_text(
            f"💼 Вы поработали 15 минут!\n\n"
            f"💰 Заработано: +{salary}₽\n"
            f"⚡ Энергия: -20 (осталось: {new_energy})\n"
            f"😊 Настроение: -{stress // 20}\n"
            f"💰 Баланс: {new_balance}₽\n\n"
            f"Следующая работа через 15 мин."
        )
    
    async def server_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /server"""
        if update.effective_chat.type == "private":
            return
            
        user_id = update.effective_user.id
        state = GameState(user_id)
        server = state.get_server()
        
        await update.message.reply_text(
            f"💻 *Ваш сервер*\n\n"
            f"Уровень: {server['level']}\n"
            f"Доход: +{server['income']}₽ в час\n"
            f"Всего принес: {server['income'] * 24 * server['level']}₽\n\n"
            f"Улучшить: /menu → Сервер",
            parse_mode='Markdown'
        )
    
    async def shop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /shop"""
        if update.effective_chat.type == "private":
            return
            
        await update.message.reply_text(
            "🛒 *Магазин КОТАК*\nВыберите что купить:",
            parse_mode='Markdown',
            reply_markup=Keyboards.shop_menu()
        )
    
    async def profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /profile"""
        if update.effective_chat.type == "private":
            return
            
        user_id = update.effective_user.id
        state = GameState(user_id)
        user = state.get_user()
        
        await update.message.reply_text(
            f"👤 *Профиль {update.effective_user.full_name}*\n\n"
            f"💰 Баланс: {user['balance']}₽\n"
            f"❤️ Здоровье: {user['health']}/100\n"
            f"⚡ Энергия: {user['energy']}/100\n"
            f"😊 Счастье: {user['happiness']}/100\n\n"
            f"Для полной информации: /menu",
            parse_mode='Markdown'
        )
    
    def setup_jobs(self, application):
        """Настройка периодических задач для чата"""
        # Получаем все активные чаты
        db = Database()
        chats = db.fetch_all("SELECT DISTINCT chat_id FROM chat_users")
        
        for chat in chats:
            chat_id = chat['chat_id']
            
            # Викторина каждые 5 минут
            application.job_queue.run_repeating(
                self.create_new_quiz,
                interval=300,
                first=10,
                chat_id=chat_id,
                data={"chat_id": chat_id}
            )
            
            # Зарплата каждый час
            application.job_queue.run_repeating(
                self.hourly_salary,
                interval=3600,
                first=60,
                chat_id=chat_id,
                data={"chat_id": chat_id}
            )
            
            # Ухудшение показателей каждые 30 минут
            application.job_queue.run_repeating(
                self.decay_stats_job,
                interval=1800,
                first=900,
                chat_id=chat_id,
                data={"chat_id": chat_id}
            )
            
            # Случайные события каждые 20-40 минут
            application.job_queue.run_repeating(
                self.random_events_job,
                interval=2400,
                first=1200,
                chat_id=chat_id,
                data={"chat_id": chat_id}
            )
            
            # Доход с серверов каждые 15 минут
            application.job_queue.run_repeating(
                self.collect_server_income,
                interval=900,
                first=300,
                chat_id=chat_id,
                data={"chat_id": chat_id}
            )
    
    def run(self):
        """Запуск бота"""
        # Создаем Application
        application = Application.builder().token(TOKEN).build()
        
        # Команды
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("menu", self.menu))
        application.add_handler(CommandHandler("work", self.work_command))
        application.add_handler(CommandHandler("shop", self.shop_command))
        application.add_handler(CommandHandler("profile", self.profile_command))
        application.add_handler(CommandHandler("server", self.server_command))
        application.add_handler(CommandHandler("help", self.menu))
        
        # Обработчики кнопок
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Обработчики сообщений (для викторин)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Настройка периодических задач
        self.setup_jobs(application)
        
        # Запуск
        logger.info("Котак бот запускается...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    bot = KotakBot()
    bot.run()
