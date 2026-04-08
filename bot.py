import logging
import sqlite3
import random
import asyncio
import os
import traceback
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils import executor
from aiogram.utils.executor import start_webhook
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from openpyxl import Workbook
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()  # .env faylni o'qiydi
API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# ==============================    WEBHOOK UCHUN =================
# WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
# WEBHOOK_PATH = os.getenv("WEBHOOK_PATH")
# WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
# WEBAPP_PORT = int(os.getenv("PORT", 5000))

# ================= BOT & DISPATCHER =================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ================= DATABASE =================
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    full_name TEXT,
    phone TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER,
    question TEXT,
    image TEXT,
    options TEXT,
    correct INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    score INTEGER,
    total INTEGER,
    date TEXT
)
""")

conn.commit()

# ================= FSM =================
class Register(StatesGroup):
    full_name = State()
    phone = State()

class AddTopic(StatesGroup):
    name = State()

class AddQuestion(StatesGroup):
    question = State()
    image = State()
    options = State()
    correct = State()

class TakeTest(StatesGroup):
    selecting_mode = State()
    answering = State()

class MixedTest(StatesGroup):
    selecting_topics = State()
    entering_count = State()
    answering = State()

class UsersResults(StatesGroup):
    enter_ids = State()

class Broadcast(StatesGroup):
    enter_message = State()

# ================= MENUS =================
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📚 Mavzulashtirilgan testlar")
    kb.add("🔀 Aralash testlar")
    kb.add("👤 Profil")
    kb.add("🏆 Reyting")
    return kb
#====================== ADMIN PANEL ===========================
def admin_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📚 Mavzular")
    kb.add("👥 Foydalanuvchilar")
    kb.add("📤 Xabar yuborish")
    return kb

# ================= START =================
@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message, state: FSMContext):
    user = cursor.execute(
        "SELECT * FROM users WHERE user_id=?",
        (message.from_user.id,)
    ).fetchone()

    if user:
        await state.finish()
        return await message.answer(
            f"Xush kelibsiz, {user[1]} 👋",
            reply_markup=main_menu()
        )

    await message.answer("Ism familiyangizni kiriting:")
    await Register.full_name.set()

@dp.message_handler(state=Register.full_name)
async def get_full_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📞 Telefon yuborish", request_contact=True))

    await message.answer("📞 Telefon raqamingizni yuboring:", reply_markup=kb)
    await Register.phone.set()

@dp.message_handler(state=Register.phone)
async def phone_error(message: types.Message):
    await message.answer("❌ Iltimos, tugma orqali telefon yuboring.")

@dp.message_handler(content_types=types.ContentType.CONTACT, state=Register.phone)
async def get_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)",
                   (message.from_user.id, data['full_name'], message.contact.phone_number))
    conn.commit()
    await state.finish()
    await message.answer(f"🎉 Tabriklaymiz {data['full_name']}, botdan foydalanishinggiz mumkin!", reply_markup=main_menu())

# ================= ADMIN =================
@dp.message_handler(commands=['admin'])
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("❌ Ruxsat yo‘q")
    await message.answer("⚙️ Admin panel", reply_markup=admin_menu())

# ================= MAVZULAR =================
@dp.message_handler(lambda m: m.text == "📚 Mavzular")
async def show_topics(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    topics = cursor.execute("SELECT * FROM topics").fetchall()
    kb = InlineKeyboardMarkup()

    for t in topics:
        count = cursor.execute(
            "SELECT COUNT(*) FROM questions WHERE topic_id=?",
            (t[0],)
        ).fetchone()[0]

        kb.add(
            InlineKeyboardButton(
                f"{t[1]} ({count} ta)",
                callback_data=f"topic_{t[0]}"
            )
        )

    kb.add(InlineKeyboardButton("➕ Mavzu qo‘shish", callback_data="add_topic"))

    await message.answer("📚 Mavzular:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "add_topic")
async def add_topic_start(call: types.CallbackQuery):
    await call.message.answer("📌 Mavzu nomini yuboring:")
    await AddTopic.name.set()

@dp.message_handler(state=AddTopic.name)
async def save_topic(message: types.Message, state: FSMContext):
    cursor.execute("INSERT INTO topics (name) VALUES (?)", (message.text,))
    conn.commit()
    await state.finish()
    await message.answer("✅ Mavzu qo‘shildi!")

# ================= OPEN TOPIC =================
@dp.callback_query_handler(lambda c: c.data.startswith("topic_"))
async def open_topic(call: types.CallbackQuery):
    topic_id = int(call.data.split("_")[1])
    questions = cursor.execute(
        "SELECT * FROM questions WHERE topic_id=?", (topic_id,)
    ).fetchall()
    kb = InlineKeyboardMarkup()
    for q in questions:
        kb.add(InlineKeyboardButton(q[2][:30], callback_data=f"q_{q[0]}"))
    kb.add(InlineKeyboardButton("➕ Savol qo‘shish", callback_data=f"addq_{topic_id}"))
    kb.add(InlineKeyboardButton("❌ Mavzuni o‘chirish", callback_data=f"del_{topic_id}"))
    kb.add(InlineKeyboardButton("⬅️ Ortga", callback_data="back_topics"))
    await call.message.edit_text("📋 Savollar:", reply_markup=kb)

# ================= DELETE THEME =================
@dp.callback_query_handler(lambda c: c.data.startswith("del_"))
async def delete_topic(call: types.CallbackQuery):
    topic_id = int(call.data.split("_")[1])

    # Mavzu va unga tegishli savollarni o'chirish
    cursor.execute("DELETE FROM questions WHERE topic_id=?", (topic_id,))
    cursor.execute("DELETE FROM topics WHERE id=?", (topic_id,))
    conn.commit()

    await call.answer("❌ Mavzu o‘chirildi", show_alert=True)

    # Mavzular ro'yxatini yangilash
    topics = cursor.execute("SELECT * FROM topics").fetchall()
    kb = InlineKeyboardMarkup()
    for t in topics:
        kb.add(InlineKeyboardButton(t[1], callback_data=f"topic_{t[0]}"))
    kb.add(InlineKeyboardButton("➕ Mavzu qo‘shish", callback_data="add_topic"))

    await call.message.edit_text("📚 Mavzular:", reply_markup=kb)

# ================= ADD QUESTION =================
@dp.callback_query_handler(lambda c: c.data.startswith("addq_"))
async def add_question_start(call: types.CallbackQuery, state: FSMContext):
    topic_id = int(call.data.split("_")[1])
    await state.update_data(topic_id=topic_id)
    await call.message.answer("📝 Savol matnini yuboring:")
    await AddQuestion.question.set()

@dp.message_handler(state=AddQuestion.question, content_types=types.ContentType.ANY)
async def get_question(message: types.Message, state: FSMContext):

    if message.content_type != "text":
        return await message.answer("❌ Iltimos, savol matnini text ko‘rinishida yuboring.")

    if len(message.text.strip()) < 5:
        return await message.answer("❌ Savol juda qisqa. To‘liqroq yozing.")

    await state.update_data(question=message.text.strip())
    await message.answer("🖼 Rasm yuboring yoki '0' yuboring:")
    await AddQuestion.image.set()

@dp.message_handler(state=AddQuestion.image, content_types=['photo', 'text'])
async def get_image(message: types.Message, state: FSMContext):
    if message.content_type == 'text':
        if message.text == "0":
            await state.update_data(image=None)
        else:
            return await message.answer("❌ Rasm yuboring yoki '0' yuboring")
    
    elif message.content_type == 'photo':
        await state.update_data(image=message.photo[-1].file_id)

    await message.answer("Variantlarni yuboring (har biri yangi qatordan):")
    await AddQuestion.options.set()

@dp.message_handler(state=AddQuestion.options, content_types=types.ContentType.ANY)
async def get_options(message: types.Message, state: FSMContext):

    if message.content_type != "text":
        return await message.answer("❌ Variantlarni faqat text ko‘rinishida yuboring.")

    options = [opt.strip() for opt in message.text.split("\n") if opt.strip()]

    if len(options) < 2:
        return await message.answer("❌ Kamida 2 ta variant bo‘lishi kerak.")

    if len(options) > 6:
        return await message.answer("❌ Maksimum 6 ta variant bo‘lishi mumkin.")

    await state.update_data(options=options)

    text = "📋 Variantlar:\n\n"
    for i, opt in enumerate(options, 1):
        text += f"{i}. {opt}\n"

    await message.answer(text)
    await message.answer(f"✅ To‘g‘ri javob raqamini kiriting (1-{len(options)}):")

    await AddQuestion.correct.set()

@dp.message_handler(state=AddQuestion.correct, content_types=types.ContentType.ANY)
async def save_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    options = data.get('options', [])

    # ❗ Faqat text qabul qilamiz
    if message.content_type != "text":
        return await message.answer(f"❌ Iltimos, faqat raqam yuboring (1-{len(options)}).")

    # ❗ Raqamga o‘tkazish
    try:
        correct = int(message.text)
    except:
        return await message.answer(f"❌ Iltimos, faqat raqam kiriting (1-{len(options)}).")

    # ❗ Chegarani tekshirish
    if correct < 1 or correct > len(options):
        return await message.answer(f"❌ Raqam 1 dan {len(options)} gacha bo‘lishi kerak. Qayta kiriting:")

    # ✅ Saqlash
    cursor.execute("""
    INSERT INTO questions (topic_id, question, image, options, correct)
    VALUES (?, ?, ?, ?, ?)
    """, (
        data['topic_id'],
        data['question'],
        data['image'],
        "\n".join(options),
        correct
    ))
    conn.commit()

    await state.finish()

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Yangi savol", callback_data=f"addq_{data['topic_id']}"))
    kb.add(InlineKeyboardButton("⬅️ Ortga", callback_data=f"topic_{data['topic_id']}"))

    await message.answer("✅ Savol qo‘shildi!", reply_markup=kb)


# ================= SHOW QUESTION =================
@dp.callback_query_handler(lambda c: c.data.startswith("q_"))
async def show_question(call: types.CallbackQuery):
    q_id = int(call.data.split("_")[1])
    q = cursor.execute("SELECT * FROM questions WHERE id=?", (q_id,)).fetchone()
    text = f"❓ {q[2]}\n\n"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ O‘chirish", callback_data=f"delq_{q_id}"))
    if q[3]:
        await call.message.answer_photo(q[3], caption=text, reply_markup=kb)
    else:
        await call.message.answer(text, reply_markup=kb)

# ================= DELETE QUESTION =================
@dp.callback_query_handler(lambda c: c.data.startswith("delq_"))
async def delete_question(call: types.CallbackQuery):
    q_id = int(call.data.split("_")[1])
    cursor.execute("DELETE FROM questions WHERE id=?", (q_id,))
    conn.commit()
    await call.answer("❌ O‘chirildi", show_alert=True)

# ================= BACK =================
@dp.callback_query_handler(lambda c: c.data == "back_topics")
async def back_topics(call: types.CallbackQuery):
    topics = cursor.execute("SELECT * FROM topics").fetchall()
    kb = InlineKeyboardMarkup()
    for t in topics:
        kb.add(InlineKeyboardButton(t[1], callback_data=f"topic_{t[0]}"))
    kb.add(InlineKeyboardButton("➕ Mavzu qo‘shish", callback_data="add_topic"))
    await call.message.edit_text("📚 Mavzular:", reply_markup=kb)


#============================ SEND MESSAGE =======================
@dp.message_handler(lambda m: m.text == "📤 Xabar yuborish")
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("❌ Ruxsat yo‘q")
    
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Ortga")
    
    await message.answer(
        "📌 Yuboriladigan xabar matnini kiriting:",
        reply_markup=kb
    )
    await Broadcast.enter_message.set()


@dp.message_handler(lambda m: m.text == "⬅️ Ortga", state=Broadcast.enter_message)
async def cancel_broadcast(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Bekor qilindi", reply_markup=admin_menu())


@dp.message_handler(state=Broadcast.enter_message)
async def send_broadcast(message: types.Message, state: FSMContext):
    users = cursor.execute("SELECT user_id FROM users").fetchall()
#============================= AGARDA QACHONDIR BOT SOTILADIGAN BO'LSA O'CHIRILISHI KERAK BO'LGAN QISM (10 qator) =======
    success = 0
    failed = 0
    for u in users:
        try:
            await bot.send_message(u[0], message.text)
            success += 1
        except:
            failed += 1
    
    await message.answer(f"📤 Xabar yuborildi!\n✅ Muvaffaqiyatli: {success}\n❌ Muammoli: {failed}")
    await state.finish()
    await message.answer("⚙️ Admin panel", reply_markup=admin_menu())

# ================= USERS BUTTON <ADMIN PANEL> =================
@dp.message_handler(lambda m: m.text == "👥 Foydalanuvchilar")
async def admin_users_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("❌ Ruxsat yo‘q")
    
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📋 Foydalanuvchilar ro’yxati", callback_data="users_list_0"),
        InlineKeyboardButton("🔍 Foydalanuvchini qidirish", callback_data="users_search"),
        InlineKeyboardButton("📊 Natijalar", callback_data="users_results")
    )
    await message.answer("👥 Foydalanuvchilar bo‘limi:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("users_list_"))
async def users_list(call: types.CallbackQuery):
    page = int(call.data.split("_")[-1])
    limit = 10
    offset = page * limit
    
    users = cursor.execute("SELECT user_id, full_name FROM users ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    if not users:
        return await call.answer("❌ Foydalanuvchilar topilmadi!", show_alert=True)
    
    kb = InlineKeyboardMarkup(row_width=1)
    for u in users:
        kb.add(InlineKeyboardButton(f"{u[1]} ({u[0]})", callback_data=f"user_info_{u[0]}"))
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"users_list_{page-1}"))
    if len(users) == limit:
        nav_buttons.append(InlineKeyboardButton("➡️ Keyingi", callback_data=f"users_list_{page+1}"))
    
    if nav_buttons:
        kb.row(*nav_buttons)
    
    await call.message.edit_text("📋 Foydalanuvchilar ro’yxati:", reply_markup=kb)



#====================== RESULTS ================================
@dp.callback_query_handler(lambda c: c.data == "users_results")
async def users_results_start(call: types.CallbackQuery):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Ortga")

    await call.message.answer(
        "📌 Telegram ID larini bo‘sh joy bilan yuboring:",
        reply_markup=kb
    )
    await UsersResults.enter_ids.set()

async def generate_results_file(user_ids):
    wb = Workbook()
    ws = wb.active
    ws.append(["User ID", "Ism", "Telefon", "Natija", "Sana"])

    single_user = len(user_ids) == 1
    users_info = []

    for uid in user_ids:
        user = cursor.execute(
            "SELECT * FROM users WHERE user_id=?", (uid,)
        ).fetchone()

        if not user:
            continue

        users_info.append(f"{user[1]} ({user[2]})")

        if single_user:
            results = cursor.execute(
                "SELECT score, total, date FROM results WHERE user_id=? ORDER BY id ASC", (uid,)
            ).fetchall()
        else:
            results = cursor.execute(
                "SELECT score, total, date FROM results WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)
            ).fetchall()

        if not results:
            ws.append([user[0], user[1], user[2], "", ""])
            continue

        for r in results:
            score_text = f"{r[0]}/{r[1]}"
            ws.append([user[0], user[1], user[2], score_text, r[2]])

    # Faylni saqlash
    folder = "results/"
    os.makedirs(folder, exist_ok=True)

    file_path = os.path.join(
        folder,
        f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    wb.save(file_path)

    return file_path, users_info

@dp.callback_query_handler(lambda c: c.data.startswith("user_info_"))
async def user_info(call: types.CallbackQuery):
    user_id = int(call.data.split("_")[-1])  # 🔥 MUHIM

    file_path, users_info = await generate_results_file([user_id])

    await call.message.answer_document(
        open(file_path, "rb"),
        caption=users_info[0] if users_info else "Foydalanuvchi topilmadi"
    )

# ================= USERS SEARCH =================
@dp.callback_query_handler(lambda c: c.data == "users_search")
async def users_search_start(call: types.CallbackQuery):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Ortga")

    await call.message.answer(
        "📌 Foydalanuvchi Telegram ID sini kiriting:",
        reply_markup=kb
    )
    await UsersResults.enter_ids.set()

#===================== BACK BUTTON FOR USERS MENU ========================
@dp.message_handler(state=UsersResults.enter_ids)
async def show_users_results(message: types.Message, state: FSMContext):

    # 🔙 ORTGA BOSILSA
    if message.text == "⬅️ Ortga":
        await state.finish()

        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("📋 Foydalanuvchilar ro’yxati", callback_data="users_list_0"),
            InlineKeyboardButton("🔍 Foydalanuvchini qidirish", callback_data="users_search"),
            InlineKeyboardButton("📊 Natijalar", callback_data="users_results")
        )

        return await message.answer("👥 Foydalanuvchilar bo‘limi:", reply_markup=kb)

    # 🔢 ID larni olish
    ids = [int(i) for i in message.text.split() if i.isdigit()]

    if not ids:
        return await message.answer("❌ Iltimos, to‘g‘ri ID kiriting:")

    found_ids = []
    not_found_ids = []

    for uid in ids:
        user = cursor.execute(
            "SELECT * FROM users WHERE user_id=?", (uid,)
        ).fetchone()

        if user:
            found_ids.append(uid)
        else:
            not_found_ids.append(uid)

    # Hech bir foydalanuvchi topilmasa
    if not found_ids:
        return await message.answer(
            "❌ Hech bir foydalanuvchi topilmadi!\n\nQaytadan ID kiriting:"
        )

    # Fayl yaratish
    file_path, users_info = await generate_results_file(found_ids)

    caption_text = "📋 Foydalanuvchilar:\n"
    for i, u in enumerate(users_info, 1):
        caption_text += f"{i}. {u}\n"

    if not_found_ids:
        caption_text += "\n❌ Topilmadi:\n"
        for uid in not_found_ids:
            caption_text += f"- {uid}\n"

    # Fayl yuborish
    await message.answer_document(open(file_path, "rb"), caption=caption_text)

    # Keyingi ID kiritish yoki to‘xtatish uchun xabar
    await message.answer("📌 Yana ID kiriting yoki to‘xtatish uchun '⬅️ Ortga' tugmasini bosing:")

#================== PROFILE ================================
@dp.message_handler(lambda m: m.text == "👤 Profil")
async def profil(message: types.Message, state: FSMContext):
    user = cursor.execute("SELECT * FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    if not user:
        return await message.answer("❌ Siz ro'yxatdan o'tmagansiz.")

    # Foydalanuvchining barcha test natijalari
    total_tests = cursor.execute("SELECT COUNT(*) FROM results WHERE user_id=?", (message.from_user.id,)).fetchone()[0]

    await message.answer(
        f"👤 Ism Familiya: {user[1]}\n"
        f"📞 Telefon: {user[2]}\n"
        f"🆔 Telegram ID: {message.from_user.id}\n"
        f"📝 Ishlagan testlar soni: {total_tests}",
        reply_markup=profile_tests_keyboard_paginated(message.from_user.id, page=0)  # 1-sahifa
    )

# ========================= INLINE TUGMA FUNKSIYASI =========================
def profile_tests_keyboard_paginated(user_id, page=0):
    limit = 10

    # Foydalanuvchining barcha test natijalari oxiridan boshlab
    all_results = cursor.execute(
        "SELECT id, score, total, date FROM results WHERE user_id=? ORDER BY id DESC",
        (user_id,)
    ).fetchall()

    total = len(all_results)
    if total == 0:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("❌ Test natijalari yo'q", callback_data="no_result"))
        return kb

    # Sahifa kesimi
    start = page * limit
    end = start + limit
    page_results = all_results[start:end]

    kb = InlineKeyboardMarkup(row_width=2)

    # Teskarisida sanoq: oxirgi test – 1, undan oldingi – 2 va hokazo
    for idx, r in enumerate(page_results, start=start):
        test_number = total - idx  # Oxirgi test 1, undan oldingi 2
        kb.add(
            InlineKeyboardButton(
                f"{test_number}-test: {r[1]}/{r[2]}",  # score/total
                callback_data=f"view_test_{r[0]}"
            )
        )

    # Oldingi / Keyingi tugmalar (bir qatorda)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("➡️ Keyingi", callback_data=f"profile_page_{page-1}"))
    if end < total:
        nav_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"profile_page_{page+1}"))

    if nav_buttons:
        kb.row(*nav_buttons)

    return kb

# ========================= SAHIFA O'ZGARTIRISH =========================
@dp.callback_query_handler(lambda c: c.data.startswith("profile_page_"))
async def profile_change_page(call: types.CallbackQuery):
    page = int(call.data.split("_")[-1])
    kb = profile_tests_keyboard_paginated(call.from_user.id, page)
    await call.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("view_test_"))
async def view_test(call: types.CallbackQuery):
    test_id = int(call.data.split("_")[-1])
    
    # Test natijasini olish
    result = cursor.execute(
        "SELECT r.score, r.total, r.date, u.full_name FROM results r "
        "JOIN users u ON r.user_id = u.user_id "
        "WHERE r.id=?", (test_id,)
    ).fetchone()
    
    if not result:
        return await call.answer("❌ Natija topilmadi!", show_alert=True)
    
    score, total, date, full_name = result
    text = (
        f"👤 Foydalanuvchi: {full_name}\n"
        f"📝 Natija: {score}/{total}\n"
        f"📅 Sana: {date}"
    )
    
    await call.message.answer(text)
    await call.answer()  # Callback tugmani "bosildi" deb belgilash

@dp.message_handler(lambda m: m.text == "⬅️ Ortga", state="*")
async def universal_back(message: types.Message, state: FSMContext):
    await state.finish()

    # Adminmi yoki oddiymi aniqlaymiz
    if message.from_user.id == ADMIN_ID:
        await message.answer("⚙️ Admin panel", reply_markup=admin_menu())
    else:
        await message.answer("🏠 Asosiy menyu", reply_markup=main_menu())

#====================== RATING ==================================
@dp.message_handler(lambda m: m.text == "🏆 Reyting")
async def leaderboard(message: types.Message):
    top_users = cursor.execute("""
        SELECT u.full_name, SUM(r.score) as total_score
        FROM results r
        JOIN users u ON r.user_id = u.user_id
        GROUP BY r.user_id
        ORDER BY total_score DESC
        LIMIT 10
    """).fetchall()

    if not top_users:
        return await message.answer("❌ Hali natijalar yo‘q.")

    text = "🏆 TOP 10 foydalanuvchilar:\n\n"

    medals = ["🥇", "🥈", "🥉"]

    for i, user in enumerate(top_users):
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} {user[0]} — {user[1]} ball\n"

    await message.answer(text)

# ================= MAVZULASHTIRILGAN TEST =================
@dp.message_handler(lambda m: m.text == "📚 Mavzulashtirilgan testlar")
async def take_test_start(message: types.Message, state: FSMContext):
    topics = cursor.execute("SELECT * FROM topics").fetchall()
    kb = InlineKeyboardMarkup()

    for t in topics:
        count = cursor.execute(
            "SELECT COUNT(*) FROM questions WHERE topic_id=?",
            (t[0],)
        ).fetchone()[0]

        kb.add(
            InlineKeyboardButton(
                f"{t[1]} ({count} ta)",
                callback_data=f"test_topic_{t[0]}"
            )
        )

    await message.answer("📚 Mavzuni tanlang:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("test_topic_"))
async def select_test_mode(call: types.CallbackQuery, state: FSMContext):
    topic_id = int(call.data.split("_")[-1])
    await state.update_data(topic_id=topic_id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("20ta savol", callback_data="mode_20"))
    kb.add(InlineKeyboardButton("Barchasi", callback_data="mode_all"))
    await call.message.answer("❓ Nechta savol ishlaysiz?", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("mode_"))
async def start_test(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    topic_id = data.get('topic_id')

    if not topic_id:
        await call.message.answer("❌ Xatolik: mavzu topilmadi. Qaytadan boshlang.")
        await state.finish()
        return

    mode = call.data.split("_")[1]

    questions = cursor.execute(
        "SELECT * FROM questions WHERE topic_id=?", (topic_id,)
    ).fetchall()

    if not questions:
        await call.message.answer("❌ Bu mavzuda savollar yo‘q.")
        await state.finish()
        return

    await state.update_data(
        questions=questions,
        current=0,
        score=0,
        wrong=0,
        user_id=call.from_user.id
    )

    # ⏳ TIMER faqat 20talik testda
    if mode == "20":
        questions = random.sample(questions, min(20, len(questions)))
        end_time = datetime.now() + timedelta(minutes=25)
        await state.update_data(end_time=end_time)

        # 🔥 BACKGROUND TIMER
        asyncio.create_task(test_timer(call.from_user.id, state))
    else:
        await state.update_data(end_time=None)

    await send_next_question(call.message, state)

async def finish_test_by_user_id(user_id, state: FSMContext):
    data = await state.get_data()

    if not data:
        return

    score = data.get('score', 0)
    questions = data.get('questions', [])
    total = len(questions)

    percent = int((score / total) * 100) if total > 0 else 0

    cursor.execute(
        "INSERT INTO results (user_id, score, total, date) VALUES (?, ?, ?, ?)",
        (user_id, score, total, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()

    await state.finish()

    await bot.send_message(
        user_id,
        f"✅ Test tugadi!\n\n📊 {score}/{total}\n📈 {percent}%"
    )

async def test_timer(user_id, state: FSMContext):
    await asyncio.sleep(25 * 60)  # 25 minut kutadi

    data = await state.get_data()

    # Agar test hali tugamagan bo‘lsa
    if data and data.get("user_id") == user_id:
        try:
            await bot.send_message(user_id, "⏳ Vaqt tugadi! Test yakunlandi.")
            await finish_test_by_user_id(user_id, state)
        except:
            pass

async def send_next_question(message, state: FSMContext):
    data = await state.get_data()
    questions = data['questions']
    current = data['current']

    if current >= len(questions):
        await finish_test(message, state)
        return

    q = questions[current]
    total = len(questions)

    # ⏳ TIMER
    timer_text = ""
    if data.get('end_time'):
        remaining = int((data['end_time'] - datetime.now()).total_seconds())

        if remaining <= 0:
            await message.answer("⏳ Vaqt tugadi!")
            await finish_test(message, state)
            return

        minutes = remaining // 60
        seconds = remaining % 60
        timer_text = f"⏳ {minutes:02}:{seconds:02}\n"

    # 📊 PROGRESS
    progress = f"📊 {current + 1}/{total}\n"

    text = f"{timer_text}{progress}\n❓ {q[2]}\n\n"

    options = q[4].split("\n")
    kb = InlineKeyboardMarkup()

    for i, opt in enumerate(options, 1):
        kb.add(InlineKeyboardButton(opt, callback_data=f"answer_{i}_{q[0]}"))

    if q[3]:
        await message.answer_photo(q[3], caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)

    await TakeTest.answering.set()

@dp.callback_query_handler(lambda c: c.data.startswith("answer_"), state=TakeTest.answering)
async def answer_question(call: types.CallbackQuery, state: FSMContext):
    _, selected, q_id = call.data.split("_")
    selected = int(selected)
    q_id = int(q_id)

    data = await state.get_data()
    questions = data['questions']
    current = data['current']
    score = data['score']
    wrong = data.get('wrong', 0)

    q = questions[current]
    correct = q[5]
    options = q[4].split("\n")

    # 🔒 Tugmalarni o‘zgartiramiz (ko‘rsatish uchun)
    kb = InlineKeyboardMarkup()

    for i, opt in enumerate(options, 1):
        text = opt

        if i == correct:
            text = f"✅ {opt}"
        if i == selected and selected != correct:
            text = f"❌ {opt}"

        kb.add(InlineKeyboardButton(text, callback_data="no_action"))

    # Eski xabarni edit qilamiz
    try:
        await call.message.edit_reply_markup(reply_markup=kb)
    except:
        pass

    if selected == correct:
        score += 1
    else:
        wrong += 1
    current += 1
    await state.update_data(current=current, score=score, wrong=wrong)

    # ❗ 3 ta xato
    if wrong >= 3:
        await call.message.answer("❌ Siz 3 ta xato qildingiz! Test yakunlandi.")
        await finish_test(call.message, state)
        return

    # ⏱ timer
    if data.get('end_time') and datetime.now() > data['end_time']:
        await finish_test(call.message, state)
        return

    await send_next_question(call.message, state)

async def finish_test(message, state: FSMContext):
    data = await state.get_data()
    score = data.get('score', 0)
    questions = data.get('questions', [])
    total = len(questions)
    user_id = data.get('user_id')

    percent = int((score / total) * 100) if total > 0 else 0

    cursor.execute(
        "INSERT INTO results (user_id, score, total, date) VALUES (?, ?, ?, ?)",
        (user_id, score, total, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🏠 Asosiy menyuga qaytish")

    await state.finish()
    await message.answer(
        f"✅ Test tugadi!\n\n"
        f"📊 Natija: {score}/{total}\n"
        f"📈 Foiz: {percent}%",
        reply_markup=kb
    )
    
# ================= ARALASH TEST =================
@dp.message_handler(lambda m: m.text == "🔀 Aralash testlar")
async def mixed_test_start(message: types.Message, state: FSMContext):

    # 🔥 tanlangan mavzularni boshlanishda bo‘sh qilib qo‘yamiz
    selected_topics = set()
    await state.update_data(selected_topics=selected_topics)

    topics = cursor.execute("SELECT * FROM topics").fetchall()
    kb = InlineKeyboardMarkup()

    for t in topics:
        count = cursor.execute(
            "SELECT COUNT(*) FROM questions WHERE topic_id=?",
            (t[0],)
        ).fetchone()[0]

        # ✔️ BELGI (hozircha hech biri tanlanmagan)
        kb.add(
            InlineKeyboardButton(
                f"{t[1]} ({count} ta)",
                callback_data=f"mix_topic_{t[0]}"
            )
        )

    # 🔥 MARAFON
    kb.add(InlineKeyboardButton("🏃‍♂️ Marafon rejimi", callback_data="marathon"))

    # 🔙 NAVIGATION
    kb.row(
        InlineKeyboardButton("⬅️ Ortga", callback_data="back_main"),
        InlineKeyboardButton("➡️ Keyingi", callback_data="mix_next")
    )

    await message.answer(
        "📚 Mavzularni tanlang yoki marafonni boshlang:",
        reply_markup=kb
    )

    await MixedTest.selecting_topics.set()

@dp.callback_query_handler(lambda c: c.data == "marathon", state=MixedTest.selecting_topics)
async def start_marathon(call: types.CallbackQuery, state: FSMContext):
    await call.answer()

    questions = cursor.execute("SELECT * FROM questions").fetchall()

    if not questions:
        return await call.answer("❌ Savollar yo‘q!", show_alert=True)

    random.shuffle(questions)

    await state.update_data(
        questions=questions,
        current=0,
        score=0,
        wrong=0,
        user_id=call.from_user.id,
        end_time=None
    )

    await call.message.answer(
        "📌 Barcha mavzulardan test savollari.\n"
        "Eslatma❗ Agar 3 ta xato qilsangiz test yakunlanadi."
    )

    await send_next_mixed_question(call.message, state)

@dp.callback_query_handler(lambda c: c.data.startswith("mix_topic_"), state=MixedTest.selecting_topics)
async def toggle_topic(call: types.CallbackQuery, state: FSMContext):
    topic_id = int(call.data.split("_")[-1])

    data = await state.get_data()
    selected = data.get('selected_topics', set())

    # 🔄 toggle
    if topic_id in selected:
        selected.remove(topic_id)
    else:
        selected.add(topic_id)

    await state.update_data(selected_topics=selected)

    # 🔥 YANGI KLAVIATURA
    kb = get_mixed_topics_keyboard(selected)

    # 🔄 XABARNI YANGILAYMIZ
    await call.message.edit_reply_markup(reply_markup=kb)

    await call.answer(f"Tanlangan mavzular: {len(selected)} ta")

@dp.callback_query_handler(lambda c: c.data == "back_main", state=MixedTest.selecting_topics)
async def mixed_back(call: types.CallbackQuery, state: FSMContext):
    kb = main_menu()
    await call.message.edit_text("Asosiy menyu:", reply_markup=kb)
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "mix_next", state=MixedTest.selecting_topics)
async def mixed_next(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get('selected_topics'):
        return await call.answer("❌ Kamida 1 mavzu tanlang!", show_alert=True)
    await call.message.answer("📌 Savollar sonini kiriting (masalan: 20 yoki boshqa son):")
    await MixedTest.entering_count.set()

@dp.message_handler(state=MixedTest.entering_count)
async def mixed_count(message: types.Message, state: FSMContext):
    try:
        count = int(message.text)
    except:
        return await message.answer("❌ Iltimos, raqam kiriting.")
    
    data = await state.get_data()
    topic_ids = data.get('selected_topics', [])

    # 🔥 Savollarni yig‘amiz
    questions = []
    for tid in topic_ids:
        qs = cursor.execute(
            "SELECT * FROM questions WHERE topic_id=?", (tid,)
        ).fetchall()
        questions.extend(qs)

    # ❗ MUHIM: savollar yo‘qligini tekshiramiz
    if not questions:
        await state.finish()
        return await message.answer("❌ Tanlangan mavzularda savollar yo‘q!")

    # 🔀 Random olish
    if count <= len(questions):
        questions = random.sample(questions, count)
    else:
        count = len(questions)

    await state.update_data(
        questions=questions,
        current=0,
        wrong=0,
        score=0,
        user_id=message.from_user.id
    )

    # ⏳ timer faqat 20 bo‘lsa
    if count == 20:
        end_time = datetime.now() + timedelta(minutes=25)
        await state.update_data(end_time=end_time)
        asyncio.create_task(test_timer(message.from_user.id, state))
    else:
        await state.update_data(end_time=None)

    await send_next_mixed_question(message, state)
    

async def send_next_mixed_question(message, state: FSMContext):
    data = await state.get_data()
    questions = data.get('questions', [])
    current = data.get('current', 0)

    # ❗ Savollar yo‘q bo‘lsa
    if not questions:
        await state.finish()
        return await message.answer("❌ Savollar topilmadi!")

    # ❗ MUHIM: test tugash sharti
    if current >= len(questions):
        await finish_mixed_test(message, state)
        return

    q = questions[current]
    total = len(questions)

    # ⏳ TIMER
    timer_text = ""
    if data.get('end_time'):
        remaining = int((data['end_time'] - datetime.now()).total_seconds())

        if remaining <= 0:
            await message.answer("⏳ Vaqt tugadi!")
            await finish_mixed_test(message, state)
            return

        minutes = remaining // 60
        seconds = remaining % 60
        timer_text = f"⏳ {minutes:02}:{seconds:02}\n"

    # 📊 PROGRESS
    progress = f"📊 {current + 1}/{total}\n\n"

    text = f"{timer_text}{progress}❓ {q[2]}\n\n"

    options = q[4].split("\n")
    kb = InlineKeyboardMarkup()

    for i, opt in enumerate(options, 1):
        kb.add(InlineKeyboardButton(opt, callback_data=f"mix_answer_{i}_{q[0]}"))

    # 📸 Rasm bo‘lsa
    if q[3]:
        await message.answer_photo(q[3], caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)

    await MixedTest.answering.set()

def get_mixed_topics_keyboard(selected_topics=None):
    if selected_topics is None:
        selected_topics = set()

    topics = cursor.execute("SELECT * FROM topics").fetchall()
    kb = InlineKeyboardMarkup()

    for t in topics:
        count = cursor.execute(
            "SELECT COUNT(*) FROM questions WHERE topic_id=?",
            (t[0],)
        ).fetchone()[0]

        # ✅ belgini qo‘shamiz
        prefix = "✔️ " if t[0] in selected_topics else ""

        kb.add(
            InlineKeyboardButton(
                f"{prefix}{t[1]} ({count} ta)",
                callback_data=f"mix_topic_{t[0]}"
            )
        )

    # 🔥 Marafon
    kb.add(InlineKeyboardButton("🏃‍♂️ Marafon rejimi", callback_data="marathon"))

    kb.row(
        InlineKeyboardButton("⬅️ Ortga", callback_data="back_main"),
        InlineKeyboardButton("➡️ Keyingi", callback_data="mix_next")
    )

    return kb

@dp.callback_query_handler(lambda c: c.data.startswith("mix_answer_"), state=MixedTest.answering)
async def mixed_answer(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split("_")

    selected = int(parts[2])
    q_id = int(parts[3])
    selected = int(selected)
    q_id = int(q_id)

    data = await state.get_data()
    questions = data['questions']
    current = data['current']
    score = data['score']
    wrong = data.get('wrong', 0)

    q = questions[current]
    correct = q[5]
    options = q[4].split("\n")

    # 🔒 Tugmalarni update qilish (ko‘rsatish uchun)
    kb = InlineKeyboardMarkup()

    for i, opt in enumerate(options, 1):
        text = opt

        if i == correct:
            text = f"✅ {opt}"
        if i == selected and selected != correct:
            text = f"❌ {opt}"

        kb.add(InlineKeyboardButton(text, callback_data="no_action"))

    # Eski tugmalarni o‘zgartiramiz
    try:
        await call.message.edit_reply_markup(reply_markup=kb)
    except:
        pass

    if selected == correct:
        score += 1
    else:
        wrong += 1
    current += 1
    await state.update_data(current=current, score=score, wrong=wrong)

    # ❗ 3 ta xato bo‘lsa tugaydi
    if wrong >= 3:
        await call.message.answer("❌ Siz 3 ta xato qildingiz! Test yakunlandi.")
        await finish_mixed_test(call.message, state)
        return

    # ⏱ Timer
    end_time = data.get('end_time')

    if end_time is not None and datetime.now() > end_time:
        await finish_mixed_test(call.message, state)
        return

    await send_next_mixed_question(call.message, state)


async def finish_mixed_test(message, state: FSMContext):
    data = await state.get_data()

    score = data.get('score', 0)
    questions = data.get('questions', [])
    total = len(questions)
    user_id = data.get('user_id')

    # ❗ fallback (ishonchli)
    if not user_id:
        user_id = message.from_user.id

    # ❗ nolga bo‘linishni oldini olamiz
    percent = int((score / total) * 100) if total > 0 else 0

    # 💾 bazaga yozish
    cursor.execute(
        "INSERT INTO results (user_id, score, total, date) VALUES (?, ?, ?, ?)",
        (user_id, score, total, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()

    await state.finish()

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🏠 Asosiy menyuga qaytish")

    await message.answer(
        f"🏁 Test tugadi!\n\n"
        f"📊 Natija: {score}/{total}\n"
        f"📈 Foiz: {percent}%",
        reply_markup=kb
    )

# ================= ASOSIY MENYUGA QAYTISH =================

# ================= RUN BERVOMIZ SHOTTAN =================

# ============================== WEBHOOK UCHUN =================
# async def on_startup(dp):
#     await bot.set_webhook(WEBHOOK_URL)
#     logging.info(f"Webhook set to {WEBHOOK_URL}")

# async def on_shutdown(dp):
#     logging.warning("Shutting down..")
#     await bot.delete_webhook()
#     logging.warning("Webhook deleted")

# if __name__ == "__main__":
#     start_webhook(
#         dispatcher=dp,
#         webhook_path=WEBHOOK_PATH,
#         on_startup=on_startup,
#         on_shutdown=on_shutdown,
#         host=WEBAPP_HOST,
#         port=WEBAPP_PORT,
#     )

# ============================== POLLING UCHUN =================
if __name__ == "__main__":
    import time

    while True:
        try:
            logging.info("Bot polling rejimida ishga tushmoqda...")
            executor.start_polling(dp, skip_updates=True)
        except KeyboardInterrupt:
            print("Bot qo‘lda to‘xtatildi.")
            break
        except Exception as e:
            logging.error(f"Pollingda xatolik yuz berdi: {e}")
            traceback.print_exc()
            print("5 soniyadan keyin qayta ishga tushiriladi...")
            time.sleep(5)