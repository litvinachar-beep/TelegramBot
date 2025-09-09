import asyncio
import json
import os
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from os.path import join, dirname
from dotenv import load_dotenv

load_dotenv(join(dirname(__file__), ".env"))
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SA_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# === Google Sheets ===
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_gs_client = None
_ws_workers = None
_ws_employers = None

def _gs_authorize():
    global _gs_client
    if _gs_client:
        return _gs_client
    if not GOOGLE_SA_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    creds_dict = json.loads(GOOGLE_SA_JSON)
    credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    _gs_client = gspread.authorize(credentials)
    return _gs_client

def _get_or_create_ws(sh, title: str, headers: list):
    try:
        ws = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(len(headers), 6))
        ws.append_row(headers)
        return ws
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(headers)
    return ws

def init_sheets():
    global _ws_workers, _ws_employers
    gc = _gs_authorize()
    if not SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID is not set")
    sh = gc.open_by_key(SPREADSHEET_ID)
    _ws_workers = _get_or_create_ws(
        sh,
        "Workers",
        ["ID", "Name", "Phone", "Experience", "City", "Timestamp"],
    )
    _ws_employers = _get_or_create_ws(
        sh,
        "Employers",
        ["ID", "Position", "Candidate Experience", "City", "Phone", "Timestamp"],
    )

def add_worker_sheet(worker: dict):
    if _ws_workers is None:
        init_sheets()
    _ws_workers.append_row(
        [
            worker["id"],
            worker["name"],
            worker["phone"],
            worker["experience"],
            worker["city"],
            datetime.now(timezone.utc).isoformat(),
        ],
        value_input_option="USER_ENTERED",
    )

def add_employer_sheet(employer: dict):
    if _ws_employers is None:
        init_sheets()
    _ws_employers.append_row(
        [
            employer["id"],
            employer["position"],
            employer["candidate_experience"],
            employer["city"],
            employer["phone"],
            datetime.now(timezone.utc).isoformat(),
        ],
        value_input_option="USER_ENTERED",
    )

init_sheets()

# --- СТАНИ АНКЕТИ ---
class Form(StatesGroup):
    # Для працівника
    name = State()
    phone = State()
    experience = State()
    city = State()
    # Для роботодавця
    employer_name = State()
    position = State()
    candidate_experience = State()
    employer_city = State()
    employer_phone = State()

# --- СТАРТ ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Я шукаю роботу 🧑‍🔧", callback_data="find_job")],
            [types.InlineKeyboardButton(text="Я шукаю працівників 👷", callback_data="find_workers")],
        ]
    )
    await message.answer(
        "Привіт! 👋 Я — Worklybot, і я допомагаю знайти роботу або людей для роботи та нові можливості.\n\n"
        "Щоб я міг краще підібрати варіанти, скажи мені, що тебе цікавить?",
        reply_markup=keyboard,
    )

# --- ОБРОБКА КНОПОК ---
@dp.callback_query(lambda call: call.data == "find_job")
async def worker_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Супер! Давай дізнаємось трохи більше про тебе:\n\nЯк тебе звати?")
    await state.set_state(Form.name)
    await call.answer()

@dp.callback_query(lambda call: call.data == "find_workers")
async def employer_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Добре! Давай знайдемо для тебе ідеальних кандидатів:\n\nДля початку, як тебе звати?")
    await state.set_state(Form.employer_name)
    await call.answer()

# --- АНКЕТА ДЛЯ ПРАЦІВНИКА ---
@dp.message(Form.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Твій номер телефону (щоб ми могли з тобою зв'язатися):")
    await state.set_state(Form.phone)

@dp.message(Form.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer(
        "Який у тебе досвід роботи у цій сфері?\n"
        "(наприклад: «без досвіду», «1-3 роки», «більше 3 років»)"
    )
    await state.set_state(Form.experience)

@dp.message(Form.experience)
async def process_experience(message: types.Message, state: FSMContext):
    await state.update_data(experience=message.text)
    await message.answer("Місто або регіон в якому ти проживаєш?")
    await state.set_state(Form.city)

@dp.message(Form.city)
async def process_city(message: types.Message, state: FSMContext):
    data = await state.update_data(city=message.text)

    add_worker_sheet(
        {
            "id": message.from_user.id,
            "name": data["name"],
            "phone": data["phone"],
            "experience": data["experience"],
            "city": data["city"],
        }
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="🔄 На головну", callback_data="main_menu")]]
    )

    result = (
        f"✅ Дякуємо за анкету! Твоя анкета успішно збережена!\n"
        f"Ми скоро з тобою зв’яжемося 📞\n\n"
        f"👤 Ім'я: {data['name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"💼 Досвід: {data['experience']}\n"
        f"📍 Місто: {data['city']}\n\n"
        f"Дякуємо, що приєднався до нашої команди 💪\n"
    )
    await message.answer(result, reply_markup=keyboard)
    await state.clear()

# --- АНКЕТА ДЛЯ РОБОТОДАВЦЯ ---
@dp.message(Form.employer_name)
async def process_employer_name(message: types.Message, state: FSMContext):
    await state.update_data(employer_name=message.text)
    await message.answer("Вкажи потрібну позицію для якої шукаєш людей:")
    await state.set_state(Form.position)

@dp.message(Form.position)
async def process_position(message: types.Message, state: FSMContext):
    await state.update_data(position=message.text)
    await message.answer("Мінімальний досвід кандидата:")
    await state.set_state(Form.candidate_experience)

@dp.message(Form.candidate_experience)
async def process_candidate_experience(message: types.Message, state: FSMContext):
    await state.update_data(candidate_experience=message.text)
    await message.answer("📍 У якому місті/регіоні потрібні працівники?")
    await state.set_state(Form.employer_city)

@dp.message(Form.employer_city)
async def process_employer_city(message: types.Message, state: FSMContext):
    await state.update_data(employer_city=message.text)
    await message.answer("📞 Залиш свій номер телефону для зв'язку:")
    await state.set_state(Form.employer_phone)

@dp.message(Form.employer_phone)
async def process_employer_phone(message: types.Message, state: FSMContext):
    data = await state.update_data(employer_phone=message.text)

    add_employer_sheet(
        {
            "id": message.from_user.id,
            "position": data["position"],
            "candidate_experience": data["candidate_experience"],
            "city": data["employer_city"],
            "phone": data["employer_phone"],
        }
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="🔄 На головну", callback_data="main_menu")]]
    )

    result = (
        f"✅ Дякуємо за анкету! Твоя анкета успішно збережена!\n"
        f"Ми скоро з тобою зв’яжемося 📞\n\n"
        f"👷 Позиція: {data['position']}\n"
        f"📊 Мінімальний досвід: {data['candidate_experience']}\n"
        f"📍 Місто: {data['employer_city']}\n"
        f"📞 Телефон: {data['employer_phone']}\n\n"
        f"Дякуємо, що приєднався до нашої команди 💪\n"
    )
    await message.answer(result, reply_markup=keyboard)
    await state.clear()

# --- ХЕНДЛЕР ПОВЕРНЕННЯ В МЕНЮ ---
@dp.callback_query(lambda call: call.data == "main_menu")
async def back_to_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await start_cmd(call.message, state)
    await call.answer()

# --- RUN ---
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
