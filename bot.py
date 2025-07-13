import logging, sqlite3, json, threading, asyncio, os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, Text
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
from difflib import SequenceMatcher

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DB = "bot.db"
WEB_PORT = 5000

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, telegram_id INTEGER, tone TEXT, subscription_end TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS knowledge (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER, question TEXT, answer TEXT)""")
    conn.commit()
    conn.close()
# --- API для регистрации бизнеса через Tilda ---
@app.route('/api/register_business', methods=['POST'])
def register_business():
    data = request.get_json()
    name = data.get('name')
    telegram_id = data.get('telegram_id')
    tone = data.get('tone', 'friendly')
    days = int(data.get('trial_days', 7))

    if not name or not telegram_id:
        return jsonify(success=False, error="Missing name or telegram_id"), 400

    sub_end = (datetime.today() + timedelta(days=days)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO businesses (name, telegram_id, tone, subscription_end) VALUES (?, ?, ?, ?)",
              (name, telegram_id, tone, sub_end))
    conn.commit()
    conn.close()
    return jsonify(success=True)


# --- API: добавление вопроса и ответа ---
@app.route('/api/add_qa', methods=['POST'])
def add_qa():
    data = request.form
    business_id = int(data.get('business_id'))
    question = data.get('question')
    answer = data.get('answer')

    if not business_id or not question or not answer:
        return jsonify(success=False, error="Missing fields"), 400

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO knowledge (business_id, question, answer) VALUES (?, ?, ?)",
              (business_id, question, answer))
    conn.commit()
    conn.close()
    return jsonify(success=True)


# --- API: установка тона общения ---
@app.route('/api/set_tone', methods=['POST'])
def set_tone():
    data = request.get_json()
    business_id = int(data.get('business_id'))
    tone = data.get('tone')

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE businesses SET tone = ? WHERE id = ?", (tone, business_id))
    conn.commit()
    conn.close()
    return jsonify(success=True)


# --- API: шаблоны ответов ---
@app.route('/api/get_templates', methods=['GET'])
def get_templates():
    with open("templates.json", "r", encoding="utf-8") as f:
        templates = json.load(f)
    return jsonify(templates)
# --- Поиск подходящего ответа по вопросу ---
def find_best_answer(business_id: int, user_question: str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT question, answer FROM knowledge WHERE business_id = ?", (business_id,))
    qa_list = c.fetchall()
    conn.close()

    best_match = None
    highest_ratio = 0

    for question, answer in qa_list:
        ratio = SequenceMatcher(None, user_question.lower(), question.lower()).ratio()
        if ratio > highest_ratio and ratio > 0.6:
            highest_ratio = ratio
            best_match = answer

    return best_match


# --- Получить бизнес по telegram_id клиента ---
def get_business_by_telegram_id(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, tone, subscription_end FROM businesses WHERE telegram_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    business_id, tone, sub_end = row
    if datetime.strptime(sub_end, "%Y-%m-%d") < datetime.today():
        return None
    return {"id": business_id, "tone": tone}


# --- Команда /start ---
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("🤖 Привет! Я бот-помощник. Напиши мне свой вопрос.")


# --- Обработка всех сообщений ---
@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    business = get_business_by_telegram_id(user_id)

    if not business:
        await message.answer("🚫 Вы не зарегистрированы. Обратитесь к администратору.")
        return

    answer = find_best_answer(business["id"], message.text)
    if answer:
        tone = business["tone"]
        if tone == "friendly":
            answer += " 😊"
        await message.answer(answer)
    else:
        await message.answer("🤖 Пока не знаю ответа. Пожалуйста, обучите меня через сайт!")


# --- Запуск ---
async def run_bot():
    await dp.start_polling(bot)

def run_web():
    app.run(host="0.0.0.0", port=WEB_PORT)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_web).start()
    asyncio.run(run_bot())
