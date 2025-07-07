from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent
from pyrogram.errors import MessageNotModified
from tes.question import questions
import asyncio
import time
import uuid
import logging
import random

# تنظیم لاگ دقیق‌تر برای عیب‌یابی
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# راه‌اندازی ربات
API_ID = '3335796'
API_HASH = '138b992a0e672e8346d8439c3f42ea78'
BOT_TOKEN = '5002292255:AAG3EmBHEaTPRxW8hZ797xuES-baLWm29Wo' # توکن ربات خود را اینجا قرار دهید

app = Client("watermark_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# داکیومنت نسخه Pyrogram هنگام شروع
import pyrogram
logger.info(f"Pyrogram version: {pyrogram.__version__}")

game_sessions = {}
active_timeouts = {} # برای تسک‌های تایم‌اوت سوالات
active_updaters = {} # NEW: برای تسک‌های آپدیت لیست بازیکنان

# تابع کمکی برای ایجاد متن لیست بازیکنان
def get_players_text(session):
    if not session["players"]:
        return "🧑‍🤝‍🧑 لیست پایه‌ها:\n(هنوز کسی پایه نیست)"

    text = "🧑‍🤝‍🧑 لیست پایه‌ها:\n"
    player_lines = []
    for player in session["players"]:
        score_text = f" | امتیاز: {player['score']}" if session["started"] else ""
        player_lines.append(f"👤 {player['name']}{score_text}")
    text += "\n".join(player_lines)
    return text

# تابع کمکی برای ایجاد دکمه‌ها
def get_initial_markup(session, temp_uuid_for_initial_inline=None):
    buttons = [
        [InlineKeyboardButton("🙋‍♂️ من پایه‌ام", callback_data="im_in")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="start_game")]
    ]
    if session["is_inline_message"] and not session["started"] and temp_uuid_for_initial_inline:
        buttons[0] = [InlineKeyboardButton("🙋‍♂️ من پایه‌ام", callback_data=f"im_in_inline_initial|{temp_uuid_for_initial_inline}")]

    if session["players"] and not session["started"] and session.get("starter_id"):
        buttons.append([InlineKeyboardButton("❌ لغو بازی", callback_data="cancel_game")])

    buttons.append([InlineKeyboardButton("👥 دعوت دوستان", switch_inline_query="")])
    return InlineKeyboardMarkup(buttons)

# NEW FUNCTION: برای آپدیت دوره‌ای لیست بازیکنان در حالت اینلاین
async def periodic_player_list_updater(session_key):
    """
    این تابع به صورت دوره‌ای پیام اینلاین را با لیست جدید بازیکنان آپدیت می‌کند
    تا زمانی که بازی شروع یا لغو شود.
    """
    while True:
        await asyncio.sleep(5)
        session = game_sessions.get(session_key)

        # شرایط توقف آپدیت
        if not session or session.get("started"):
            logger.info(f"UPDATER: Stopping for session {session_key}.")
            if session_key in active_updaters: del active_updaters[session_key]
            break
            
        logger.info(f"UPDATER: Running for session {session_key}")
        text_to_update = (
            "🎉 به چالش اطلاعات خوش آمدید!\n"
            "برای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n"
            f"{get_players_text(session)}"
        )
        markup = get_initial_markup(session)
        
        try:
            await app.edit_inline_message_text(session["main_message_id"], text_to_update, reply_markup=markup)
        except MessageNotModified:
            continue
        except Exception as e:
            logger.error(f"UPDATER_ERROR: Failed to update player list for {session_key}: {e}")
            if session_key in active_updaters: del active_updaters[session_key]
            break

# شروع اولیه در چت خصوصی
@app.on_message(filters.command("start") & filters.private)
async def start_command_private(client, message):
    chat_id = message.chat.id
    key = str(chat_id)

    if key in game_sessions:
        del game_sessions[key]

    session_data = {
        "players": [], "started": False, "starter_id": message.from_user.id,
        "questions": random.sample(questions, len(questions)), "is_inline_message": False,
        "main_message_id": None, "main_chat_id": chat_id, "current_q_index": 0,
    }
    game_sessions[key] = session_data
    logger.info(f"PRIVATE_START: Session created for key '{key}'.")

    text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید."
    sent_message = await message.reply(
        f"{text}\n\n{get_players_text(session_data)}",
        reply_markup=get_initial_markup(session_data)
    )
    session_data["main_message_id"] = sent_message.id

# هندلر برای inline query
@app.on_inline_query()
async def handle_inline_query(client, inline_query):
    temp_uuid_game_session = str(uuid.uuid4())
    session_data = {
        "players": [], "started": False, "starter_id": inline_query.from_user.id,
        "questions": random.sample(questions, len(questions)), "is_inline_message": True,
        "main_message_id": None, "main_chat_id": None, "current_q_index": 0,
        "temp_uuid_game_session": temp_uuid_game_session
    }
    game_sessions[temp_uuid_game_session] = session_data
    logger.info(f"INLINE_QUERY: New temp session created with key '{temp_uuid_game_session}'.")

    markup = get_initial_markup(session_data, temp_uuid_game_session)
    initial_message_text = (
        "🎉 به چالش اطلاعات خوش آمدید!\n"
        "برای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n"
        f"{get_players_text(session_data)}"
    )
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()), title="ایجاد چالش اطلاعات!",
            input_message_content=InputTextMessageContent(initial_message_text),
            reply_markup=markup, description="دوستان خود را به یک مسابقه هیجان‌انگیز دعوت کنید!"
        )
    ]
    await inline_query.answer(results, cache_time=1)

# هندل دکمه‌ها (HEAVILY MODIFIED)
@app.on_callback_query()
async def handle_buttons(client, callback_query):
    global game_sessions
    user = callback_query.from_user
    data = callback_query.data
    current_key = None
    session = None
    is_inline = bool(callback_query.inline_message_id)

    if is_inline:
        current_key = callback_query.inline_message_id
        session = game_sessions.get(current_key)
        if not session:
            if data.startswith("im_in_inline_initial|"):
                temp_uuid = data.split("|")[1]
                temp_session = game_sessions.pop(temp_uuid, None)
                if temp_session:
                    temp_session["main_message_id"] = current_key
                    game_sessions[current_key] = temp_session
                    session = game_sessions[current_key]
                    logger.info(f"CALLBACK: Transferred session from temp key '{temp_uuid}' to '{current_key}'.")
                    callback_query.data = "im_in"
                    data = "im_in"
            if not session:
                await callback_query.answer("این بازی منقضی شده است. لطفاً یک بازی جدید شروع کنید.", show_alert=True)
                return
    else:
        current_key = str(callback_query.message.chat.id)
        session = game_sessions.get(current_key)
        if not session:
            await callback_query.answer("این بازی منقضی شده است. لطفاً یک بازی جدید شروع کنید.", show_alert=True)
            try: await callback_query.message.edit_text("این بازی منقضی شده است.")
            except: pass
            return

    if data == "im_in":
        if session["started"]:
            return await callback_query.answer("🚫 بازی شروع شده و نمی‌توانید اضافه شوید!", show_alert=True)

        player_name = user.first_name or user.username or f"User_{user.id}"
        if user.id not in [p["id"] for p in session["players"]]:
            session["players"].append({"id": user.id, "name": player_name, "score": 0})
            await callback_query.answer("✅ شما به لیست پایه‌ها اضافه شدید!", show_alert=False)
            logger.info(f"CALLBACK: User {user.id} added to session {current_key}.")

            # --- MODIFICATION START ---
            # بروزرسانی فوری پیام بعد از اضافه شدن
            text_to_update = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(session)
            markup = get_initial_markup(session)
            try:
                if is_inline:
                    await app.edit_inline_message_text(session["main_message_id"], text_to_update, reply_markup=markup)
                    # اگر آپدیتر دوره‌ای فعال نیست، آن را فعال کن
                    if current_key not in active_updaters:
                        logger.info(f"Starting periodic updater for session {current_key}")
                        task = asyncio.create_task(periodic_player_list_updater(current_key))
                        active_updaters[current_key] = task
                else: # برای حالت چت خصوصی
                    await app.edit_message_text(session["main_chat_id"], session["main_message_id"], text_to_update, reply_markup=markup)
            except MessageNotModified:
                logger.warning(f"Message not modified for session {current_key}, likely no change in content.")
            except Exception as e:
                logger.error(f"CALLBACK_ERROR: Failed to update message for key '{current_key}'. Error: {e}", exc_info=True)
            # --- MODIFICATION END ---
        else:
            await callback_query.answer("شما از قبل در لیست هستید!", show_alert=False)
            logger.info(f"CALLBACK: User {user.id} already in session {current_key}.")

    elif data == "start_game":
        if session["started"]: return await callback_query.answer("بازی قبلاً شروع شده!", show_alert=True)
        if not session["players"]: return await callback_query.answer("هنوز هیچکس پایه نیست!", show_alert=True)
        if user.id != session.get("starter_id"): return await callback_query.answer("فقط شروع‌کننده بازی می‌تواند آن را استارت بزند!", show_alert=True)
        
        # MODIFICATION: توقف آپدیتر دوره‌ای هنگام شروع بازی
        if current_key in active_updaters:
            active_updaters[current_key].cancel()
            logger.info(f"Updater task for session {current_key} cancelled due to game start.")

        session["started"] = True
        logger.info(f"Game started for session {current_key} by user {user.id}")
        await callback_query.answer("🚀 بازی شروع می‌شود!")
        await ask_question_in_chat(current_key)

    elif data == "cancel_game":
        if user.id != session.get("starter_id"): return await callback_query.answer("فقط شروع‌کننده بازی می‌تواند آن را لغو کند!", show_alert=True)

        # MODIFICATION: توقف آپدیتر دوره‌ای هنگام لغو بازی
        if current_key in active_updaters:
            active_updaters[current_key].cancel()
            logger.info(f"Updater task for session {current_key} cancelled.")

        text_to_update = "❌ بازی توسط شروع‌کننده لغو شد."
        try:
            if is_inline: await app.edit_inline_message_text(session["main_message_id"], text_to_update, reply_markup=None)
            else: await app.edit_message_text(session["main_chat_id"], session["main_message_id"], text_to_update, reply_markup=None)
        except Exception as e: logger.error(f"CALLBACK_ERROR: Failed to update on cancel for session {current_key}: {e}", exc_info=True)
        
        if current_key in game_sessions: del game_sessions[current_key]
        logger.info(f"Game session {current_key} cancelled and deleted.")

    elif data.startswith("answer|"):
        await handle_answer(client, callback_query, current_key)

# بقیه توابع بدون تغییر باقی می‌مانند
async def ask_question_in_chat(session_key):
    if session_key not in game_sessions: return
    session = game_sessions[session_key]

    if session_key in active_timeouts:
        active_timeouts[session_key].cancel()
        del active_timeouts[session_key]

    if session["current_q_index"] >= len(session["questions"]):
        return await announce_final_results(session_key)

    q = session["questions"][session["current_q_index"]]
    options_list = q["options"][:]
    random.shuffle(options_list)
    buttons = [InlineKeyboardButton(text=opt, callback_data=f"answer|{opt}") for opt in options_list]
    markup = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])

    question_text = (
        f"سوال {session['current_q_index'] + 1} از {len(session['questions'])}\n\n"
        f"❓ **{q['question']}**\n\n"
        f"۱۰ ثانیه فرصت پاسخگویی دارید..."
    )

    try:
        if session["is_inline_message"]:
            await app.edit_inline_message_text(session["main_message_id"], question_text, reply_markup=markup)
        else:
            await app.edit_message_text(session["main_chat_id"], session["main_message_id"], question_text, reply_markup=markup)
        
        session["question_start_time"] = time.time()
        session["active_question"] = True

        timeout_task = asyncio.create_task(question_timeout(session_key))
        active_timeouts[session_key] = timeout_task
    except Exception as e:
        logger.error(f"ASK_QUESTION_ERROR: {e}", exc_info=True)

async def question_timeout(session_key):
    await asyncio.sleep(10)
    if session_key not in game_sessions: return
    session = game_sessions[session_key]
    
    if session.get("active_question"):
        session["active_question"] = False
        logger.info(f"Timeout for question in session {session_key}")
        
        timeout_text = f"⏰ زمان پاسخ به سوال تمام شد!\n\nآماده برای سوال بعدی..."
        try:
            if session["is_inline_message"]:
                await app.edit_inline_message_text(session["main_message_id"], timeout_text, reply_markup=None)
            else:
                await app.edit_message_text(session["main_chat_id"], session["main_message_id"], timeout_text, reply_markup=None)
        except Exception as e: logger.error(f"TIMEOUT_EDIT_ERROR: {e}")

        session["current_q_index"] += 1
        await asyncio.sleep(2)
        await ask_question_in_chat(session_key)

async def announce_final_results(session_key):
    if session_key not in game_sessions: return
    session = game_sessions[session_key]

    sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
    final_text = "🏆 نتایج نهایی چالش 🏆\n\n"
    for i, p in enumerate(sorted_players):
        final_text += f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '▫️'} {p['name']}: {p['score']} امتیاز\n"
    final_text += "\nبازی تمام شد! برای شروع یک بازی جدید از دستور /start یا @ ربات استفاده کنید."

    try:
        if session["is_inline_message"]:
            await app.edit_inline_message_text(session["main_message_id"], final_text, reply_markup=None)
        else:
            await app.edit_message_text(session["main_chat_id"], session["main_message_id"], final_text, reply_markup=None)
        logger.info(f"Final results announced for session {session_key}")
    except Exception as e: logger.error(f"ANNOUNCE_RESULTS_ERROR: {e}", exc_info=True)
    
    if session_key in game_sessions: del game_sessions[session_key]
    if session_key in active_timeouts:
        active_timeouts[session_key].cancel()
        del active_timeouts[session_key]
    if session_key in active_updaters: # NEW: Clean up updater task
        active_updaters[session_key].cancel()
        del active_updaters[session_key]

def calculate_score(elapsed):
    if elapsed <= 2: return 20
    elif elapsed <= 4: return 15
    elif elapsed <= 6: return 10
    elif elapsed <= 8: return 5
    else: return 2

async def handle_answer(client, callback_query, session_key):
    if session_key not in game_sessions:
        return await callback_query.answer("این بازی منقضی شده است!", show_alert=True)
    
    session = game_sessions[session_key]
    user = callback_query.from_user

    player = next((p for p in session["players"] if p["id"] == user.id), None)
    if not player:
        return await callback_query.answer("شما در این بازی شرکت نکرده‌اید!", show_alert=True)

    if not session.get("active_question"):
        return await callback_query.answer("این سوال دیگر فعال نیست!", show_alert=True)

    session["active_question"] = False
    if session_key in active_timeouts:
        active_timeouts[session_key].cancel()
        del active_timeouts[session_key]

    selected = callback_query.data.split("|")[1]
    q = session["questions"][session["current_q_index"]]
    correct_answer = q["answer"]
    elapsed = time.time() - session["question_start_time"]
    
    if selected == correct_answer:
        earned_score = calculate_score(elapsed)
        player["score"] += earned_score
        text = f"✅ آفرین {player['name']}! پاسخ صحیح بود.\n\n**+{earned_score}** امتیاز ({elapsed:.1f} ثانیه)\n\nآماده برای سوال بعدی..."
    else:
        text = f"❌ افسوس {player['name']}! پاسخ شما اشتباه بود.\n\nجواب صحیح: **{correct_answer}**\n\nآماده برای سوال بعدی..."

    try:
        if session["is_inline_message"]:
            await app.edit_inline_message_text(session["main_message_id"], text, reply_markup=None)
        else:
            await app.edit_message_text(session["main_chat_id"], session["main_message_id"], text, reply_markup=None)
    except Exception as e:
        logger.error(f"HANDLE_ANSWER_EDIT_ERROR: {e}")

    session["current_q_index"] += 1
    await asyncio.sleep(3)
    await ask_question_in_chat(session_key)

print("Bot is running...")
app.run()
