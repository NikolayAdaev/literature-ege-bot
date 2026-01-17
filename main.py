import asyncio
import logging
import os
import sqlite3
import html
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from database import Database

# Загрузка конфига
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

bot = Bot(token=TOKEN)
dp = Dispatcher()
db = Database('literature_bot.db')

class Registration(StatesGroup):
    waiting_for_name = State()

class Solving(StatesGroup):
    waiting_for_answer = State()

main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🔥 Получить задания на сегодня")]
], resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not db.user_exists(user_id):
        await message.answer("Привет! Я бот для подготовки к ЕГЭ по литературе.\n"
                             "Для начала введи свои **Фамилию и Имя** (например: Иванов Иван).", parse_mode="Markdown")
        await state.set_state(Registration.waiting_for_name)
    else:
        name = db.get_user_name(user_id)
        await message.answer(f"С возвращением, {html.escape(name)}!", reply_markup=main_kb)

@dp.message(Registration.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    full_name = message.text.strip()
    safe_name = html.escape(full_name)
    if len(full_name.split()) < 2:
        await message.answer("Пожалуйста, введи и Фамилию, и Имя (два слова).")
        return
    db.add_user(message.from_user.id, message.from_user.username, full_name)
    await state.clear()
    await message.answer(f"Приятно познакомиться, {safe_name}! Регистрация пройдена.", reply_markup=main_kb)

@dp.message(F.text == "🔥 Получить задания на сегодня")
async def start_daily_tasks(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if db.check_today_completed(user_id):
        await message.answer("✋ **На сегодня план выполнен!**\nВозвращайся завтра за новой порцией заданий.", parse_mode="Markdown")
        return
    tasks = db.get_new_tasks_for_user(user_id)
    if not tasks:
        await message.answer("На сегодня заданий больше нет. Приходи завтра!")
        return
    await state.set_data({'tasks_queue': tasks, 'current_index': 0})
    await send_next_task(message, state)

async def send_next_task(message: types.Message, state: FSMContext):
    data = await state.get_data()
    queue = data['tasks_queue']
    index = data['current_index']

    if index >= len(queue):
        await finish_daily_session(message, state)
        return

    task = queue[index]
    safe_question = html.escape(task['question'])
    safe_options = html.escape(task['options']) if task['options'] else ""

    msg_text = f"📝 **Задание №{index + 1}** (Линия {task['line']})\n\n"
    if task.get('is_debt'):
        msg_text = "⚠️ **ДОЛГ С ПРОШЛОГО РАЗА**\n\n" + msg_text
    msg_text += f"{safe_question}\n\n"
    if safe_options:
        msg_text += f"{safe_options}\n"
    
    buttons = []
    if task['text']:
        buttons.append([InlineKeyboardButton(text="📖 Показать текст", callback_data=f"user_show_text_{task['id']}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await message.answer(msg_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        await message.answer(msg_text.replace("<b>", "").replace("</b>", ""), reply_markup=keyboard)
    await state.set_state(Solving.waiting_for_answer)

@dp.callback_query(F.data.startswith("user_show_text_"))
async def user_show_text(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[3])
    try:
        with sqlite3.connect('literature_bot.db') as conn:
            res = conn.cursor().execute("SELECT content_text FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if res and res[0]:
                text = res[0]
                safe_text = html.escape(text)
                if len(safe_text) > 3800: safe_text = safe_text[:3800] + "\n..."
                await callback.message.answer(f"📜 **Текст к заданию:**\n\n{safe_text}", parse_mode="HTML")
            else:
                await callback.answer("Текст не найден", show_alert=True)
    except:
        await callback.answer("Ошибка")
    await callback.answer()

@dp.message(Solving.waiting_for_answer)
async def check_answer(message: types.Message, state: FSMContext):
    user_answer = message.text.strip().lower()
    data = await state.get_data()
    index = data['current_index']
    task = data['tasks_queue'][index]
    db_answer = db.get_correct_answer(task['id']) 
    correct_variants = db_answer.split("|")
    is_correct = False
    
    if task['line'] == 8:
        clean_user = "".join(filter(str.isdigit, user_answer))
        for variant in correct_variants:
            if clean_user == variant: is_correct = True; break
    else:
        if user_answer in correct_variants: is_correct = True

    db.update_task_status(message.from_user.id, task['id'], is_correct, message.text)
    if is_correct: await message.answer("✅ **Верно!**", parse_mode="Markdown")
    else: await message.answer("❌ **Неверно.**", parse_mode="Markdown")
    await state.update_data(current_index=index + 1)
    await send_next_task(message, state)

# ==========================================
#          ЛОГИКА АДМИН-ПАНЕЛИ
# ==========================================

async def finish_daily_session(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    name = db.get_user_name(user_id)
    stats = db.get_daily_stats(user_id)
    
    correct_count = sum(1 for s in stats if s[3] == 1)
    total_count = len(stats)
    
    await message.answer(f"🏁 Задания на сегодня закончены!\nТвой результат: {correct_count}/{total_count}\nЖду тебя завтра!", reply_markup=main_kb)
    await state.clear()
    
    if ADMIN_ID:
        safe_name = html.escape(name)
        header_text = (f"🔔 <b>Новый отчет</b>\n"
                       f"👤 Ученик: {safe_name}\n"
                       f"📊 Результат: {correct_count}/{total_count}")
        
        await bot.send_message(ADMIN_ID, header_text, parse_mode="HTML")
        
        if correct_count != total_count:
            for s in stats:
                # s: (result_id, task_id, line, status, user_ans, cor_ans, q_text)
                if s[3] == 2: # Если ошибка
                    result_id = s[0]
                    task_id = s[1] # Это ID задания в таблице tasks
                    line = s[2]
                    u_ans = html.escape(s[4]) if s[4] else "Нет ответа"
                    c_ans = html.escape(s[5])
                    q_text = html.escape(s[6])
                    q_text_short = q_text[:150] + "..." if len(q_text) > 150 else q_text
                    
                    err_msg = (
                        f"❌ <b>Ошибка (Линия {line})</b>\n\n"
                        f"❓ <b>Вопрос:</b> {q_text_short}\n"
                        f"👤 <b>Ответ ученика:</b> {u_ans}\n"
                        f"✅ <b>Правильно:</b> {c_ans}"
                    )
                    
                    # Кнопки для админа (ДОБАВИЛ УДАЛЕНИЕ ЗАДАНИЯ)
                    # result_id - для исправления оценки ученика
                    # task_id - для удаления задания из БД
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📖 Показать текст", callback_data=f"adm_text_show_{result_id}")],
                        [InlineKeyboardButton(text="✅ Отметить как правильное", callback_data=f"adm_mark_correct_{result_id}")],
                        [InlineKeyboardButton(text="🗑 Удалить задание из БД", callback_data=f"adm_task_del_{task_id}")]
                    ])
                    
                    try:
                        await bot.send_message(ADMIN_ID, err_msg, parse_mode="HTML", reply_markup=keyboard)
                        await asyncio.sleep(0.2)
                    except Exception as e:
                        print(f"Ошибка отправки админу: {e}")

# --- КНОПКА "ПОКАЗАТЬ/СКРЫТЬ ТЕКСТ" ---
@dp.callback_query(F.data.startswith("adm_text_"))
async def admin_toggle_text(callback: types.CallbackQuery):
    action, result_id = callback.data.split("_")[2], int(callback.data.split("_")[3])
    current_text = callback.message.html_text
    current_markup = callback.message.reply_markup
    
    if action == "show":
        text_content = db.get_task_text_by_result_id(result_id)
        if not text_content:
            await callback.answer("Текст не найден", show_alert=True)
            return
        safe_content = html.escape(text_content)
        if len(safe_content) > 3000: safe_content = safe_content[:3000] + "..."
        new_text = f"{current_text}\n\n📜 <b>Текст произведения:</b>\n{safe_content}"
        new_markup = update_button(current_markup, 0, "📖 Скрыть текст", f"adm_text_hide_{result_id}")
        await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=new_markup)
        
    elif action == "hide":
        marker = "\n\n📜 <b>Текст произведения:</b>"
        if marker in current_text:
            new_text = current_text.split(marker)[0]
            new_markup = update_button(current_markup, 0, "📖 Показать текст", f"adm_text_show_{result_id}")
            await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=new_markup)
    
    await callback.answer()

# --- КНОПКА "СМЕНИТЬ СТАТУС ОТВЕТА" ---
@dp.callback_query(F.data.startswith("adm_mark_"))
async def admin_toggle_status(callback: types.CallbackQuery):
    action, result_id = callback.data.split("_")[2], int(callback.data.split("_")[3])
    current_text = callback.message.html_text
    current_markup = callback.message.reply_markup
    
    marker_correct = "\n\n✅ <b>ВЫ ИЗМЕНИЛИ ЭТОТ ОТВЕТ НА ПРАВИЛЬНЫЙ</b>"
    
    if action == "correct":
        db.toggle_result_status(result_id, 1)
        new_text = current_text + marker_correct
        new_markup = update_button(current_markup, 1, "❌ Отметить как неправильное", f"adm_mark_wrong_{result_id}")
    elif action == "wrong":
        db.toggle_result_status(result_id, 2)
        new_text = current_text.replace(marker_correct, "")
        new_markup = update_button(current_markup, 1, "✅ Отметить как правильное", f"adm_mark_correct_{result_id}")
        
    await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=new_markup)
    await callback.answer("Статус ответа изменен")

# --- КНОПКА "УДАЛИТЬ ЗАДАНИЕ ИЗ БД" ---
@dp.callback_query(F.data.startswith("adm_task_"))
async def admin_toggle_task_active(callback: types.CallbackQuery):
    action, task_id = callback.data.split("_")[2], int(callback.data.split("_")[3])
    current_text = callback.message.html_text
    current_markup = callback.message.reply_markup
    
    marker_deleted = "\n\n🗑 <b>ЗАДАНИЕ УДАЛЕНО ИЗ БАЗЫ (СКРЫТО)</b>"
    
    if action == "del":
        db.toggle_task_active_status(task_id, 0) # 0 = скрыто
        new_text = current_text + marker_deleted
        new_markup = update_button(current_markup, 2, "♻️ Вернуть задание в базу", f"adm_task_res_{task_id}")
        
    elif action == "res": # restore
        db.toggle_task_active_status(task_id, 1) # 1 = активно
        new_text = current_text.replace(marker_deleted, "")
        new_markup = update_button(current_markup, 2, "🗑 Удалить задание из БД", f"adm_task_del_{task_id}")
        
    await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=new_markup)
    await callback.answer("Статус задания изменен")

# Вспомогательная функция для замены кнопок
def update_button(markup, row_index, new_text, new_callback):
    rows = markup.inline_keyboard
    # Проверяем, существует ли такая кнопка (чтобы не упало)
    if row_index < len(rows) and len(rows[row_index]) > 0:
        rows[row_index][0].text = new_text
        rows[row_index][0].callback_data = new_callback
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())