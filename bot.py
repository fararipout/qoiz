import asyncio
import time
import uuid
import logging
import random
from telethon import TelegramClient, events, types
from telethon.tl.types import InputBotInlineResult, InputBotInlineMessageText
from tes.question import questions

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
BOT_TOKEN = '5002292255:AAGc9Lk0LXX1cjfERx6CnVye0A5EUNvgtzU'

app = TelegramClient("watermark_bot", api_id=API_ID, api_hash=API_HASH)

game_sessions = {}
active_timeouts = {}
active_updaters = {}

# داکیومنت نسخه Telethon هنگام شروع
import telethon
logger.info(f"Telethon version: {telethon.__version__}")

# تابع پاک‌سازی جلسات قدیمی
async def cleanup_old_sessions():
    try:
        while True:
            await asyncio.sleep(600)  # هر 10 دقیقه
            expired_keys = [key for key, session in game_sessions.items() if time.time() - session.get("created_at", time.time()) > 600]
            for key in expired_keys:
                logger.info(f"Cleaning up expired session {key}")
                if key in game_sessions:
                    del game_sessions[key]
                if key in active_updaters:
                    active_updaters[key].cancel()
                    del active_updaters[key]
                if key in active_timeouts:
                    active_timeouts[key].cancel()
                    del active_timeouts[key]
    except asyncio.CancelledError:
        logger.info("Cleanup task cancelled")
        raise

# تابع کمکی برای ایجاد متن لیست بازیکنان
def get_players_text(session):
    if not session["players"]:
        return "🧑‍🤝‍🧑 لیست پایه‌ها:\n(هنوز کسی پایه نیست)"

    text = "🧑‍🤝‍🧑 لیست پایه‌ها:\n"
    # مرتب‌سازی بازیکنان بر اساس امتیاز به ترتیب نزولی
    sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
    player_lines = []
    for player in sorted_players:
        score_text = f" | امتیاز: {player['score']}" if session["started"] else ""
        player_lines.append(f"👤 {player['name']}{score_text}")
    text += "\n".join(player_lines)
    return text

# تابع کمکی برای ایجاد دکمه‌ها
def get_initial_markup(session, temp_uuid_for_initial_inline=None):
    rows = []
    rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("🙋‍♂️ من پایه‌ام", data=b"im_in")]))
    rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("🚀 شروع بازی", data=b"start_game")]))
    
    if session["is_inline_message"] and not session["started"] and temp_uuid_for_initial_inline:
        rows[0] = types.KeyboardButtonRow([types.KeyboardButtonCallback("🙋‍♂️ من پایه‌ام", data=f"im_in_inline_initial|{temp_uuid_for_initial_inline}".encode())])
    
    if session["players"] and not session["started"] and session.get("starter_id"):
        rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("❌ لغو بازی", data=b"cancel_game")]))
    
    rows.append(types.KeyboardButtonRow([types.KeyboardButtonSwitchInline("👥 دعوت دوستان", query="")]))
    return types.ReplyInlineMarkup(rows)

# تابع آپدیت دوره‌ای لیست بازیکنان (فقط برای چت خصوصی)
async def periodic_player_list_updater(client, session_key):
    try:
        while True:
            await asyncio.sleep(5)
            session = game_sessions.get(session_key)
            if not session or session.get("started"):
                logger.info(f"UPDATER: Stopping for session {session_key}.")
                if session_key in active_updaters:
                    del active_updaters[session_key]
                break
                
            text_to_update = (
                "🎉 به چالش اطلاعات خوش آمدید!\n"
                "برای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n"
                f"{get_players_text(session)}"
            )
            markup = get_initial_markup(session)
            logger.info(f"UPDATER: Attempting to update session {session_key}, is_inline={session['is_inline_message']}, message_id={session.get('main_message_id')}")
            
            try:
                if not session["is_inline_message"]:
                    await client.edit_message(
                        entity=session["main_chat_id"],
                        message=session["main_message_id"],
                        text=text_to_update,
                        buttons=markup
                    )
                    logger.info(f"UPDATER: Chat message {session['main_message_id']} updated successfully")
            except Exception as e:
                logger.error(f"UPDATER_ERROR: Failed to update session {session_key}: {e}", exc_info=True)
                if session_key in active_updaters:
                    del active_updaters[session_key]
                break
    except asyncio.CancelledError:
        logger.info(f"UPDATER: Task cancelled for session {session_key}")
        if session_key in active_updaters:
            del active_updaters[session_key]
        raise

# شروع اولیه در چت خصوصی
@app.on(events.NewMessage(pattern='/start', incoming=True))
async def start_command_private(event):
    if not event.is_private:
        return
    chat_id = event.chat_id
    key = str(chat_id)

    if key in game_sessions:
        del game_sessions[key]
        logger.info(f"PRIVATE_START: Old session for key '{key}' deleted.")

    session_data = {
        "players": [], "started": False, "starter_id": event.sender_id,
        "questions": random.sample(questions, min(10, len(questions))), "is_inline_message": False,
        "main_message_id": None, "main_chat_id": chat_id, "current_q_index": 0,
        "created_at": time.time(), "responses": [], "responded_users": []
    }
    game_sessions[key] = session_data
    logger.info(f"PRIVATE_START: Session created for key '{key}'.")

    text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید."
    try:
        sent_message = await event.respond(
            f"{text}\n\n{get_players_text(session_data)}",
            buttons=get_initial_markup(session_data)
        )
        session_data["main_message_id"] = sent_message.id
        logger.info(f"PRIVATE_START: Main message ID set to {sent_message.id} for key '{key}'.")
    except Exception as e:
        logger.error(f"PRIVATE_START_ERROR: Failed to send message for key '{key}': {e}", exc_info=True)

# هندلر برای inline query
@app.on(events.InlineQuery())
async def handle_inline_query(event):
    temp_uuid_game_session = str(uuid.uuid4())
    session_data = {
        "players": [], "started": False, "starter_id": event.sender_id,
        "questions": random.sample(questions, min(10, len(questions))), "is_inline_message": True,
        "main_message_id": None, "main_chat_id": None, "current_q_index": 0,
        "temp_uuid_game_session": temp_uuid_game_session, "created_at": time.time(),
        "responses": [], "responded_users": []
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
        InputBotInlineResult(
            id=str(uuid.uuid4()),
            type='article',
            title="ایجاد چالش اطلاعات!",
            description="دوستان خود را به یک مسابقه هیجان‌انگیز دعوت کنید!",
            send_message=InputBotInlineMessageText(
                message=initial_message_text,
                reply_markup=markup
            )
        )
    ]
    try:
        await event.answer(results, cache_time=1)
        logger.info(f"INLINE_QUERY: Answered inline query for user {event.sender_id}")
    except Exception as e:
        logger.error(f"INLINE_QUERY_ERROR: Failed to answer inline query: {e}", exc_info=True)

# هندل دکمه‌ها
@app.on(events.CallbackQuery())
async def handle_buttons(event):
    global game_sessions
    user = event.sender
    data = event.data.decode('utf-8')
    current_key = None
    session = None
    is_inline = False

    # بررسی اینکه آیا callback از پیام اینلاین است
    if hasattr(event, 'query') and hasattr(event.query, 'msg_id'):
        is_inline = True
        current_key = str(event.query.msg_id.id)  # استفاده از id ساده به جای شیء کامل
    else:
        current_key = str(event.chat_id)

    logger.info(f"CALLBACK: Received callback from user {user.id} with data '{data}', is_inline={is_inline}, current_key={current_key}")

    # --- Session finding logic ---
    if is_inline:
        session = game_sessions.get(current_key)
        if not session:
            logger.warning(f"CALLBACK: No session found for inline_message_id '{current_key}'")
            if data.startswith("im_in_inline_initial|"):
                temp_uuid = data.split("|")[1]
                logger.info(f"CALLBACK: Attempting to transfer session from temp_uuid '{temp_uuid}'")
                temp_session = game_sessions.get(temp_uuid)
                if temp_session:
                    temp_session["main_message_id"] = current_key
                    game_sessions[current_key] = temp_session
                    del game_sessions[temp_uuid]
                    session = game_sessions[current_key]
                    logger.info(f"CALLBACK: Transferred session from temp key '{temp_uuid}' to '{current_key}'.")
                    data = "im_in"
                else:
                    logger.error(f"CALLBACK: Temp session '{temp_uuid}' not found")
                    await event.answer("این بازی منقضی شده است. لطفاً یک بازی جدید شروع کنید.", alert=True)
                    return
            else:
                logger.error(f"CALLBACK: No session or temp session found for inline_message_id '{current_key}'")
                await event.answer("این بازی منقضی شده است. لطفاً یک بازی جدید شروع کنید.", alert=True)
                return
    else:
        session = game_sessions.get(current_key)
        if not session:
            logger.error(f"CALLBACK: No session found for chat_id '{current_key}'")
            await event.answer("این بازی منقضی شده است. لطفاً یک بازی جدید شروع کنید.", alert=True)
            try:
                await event.edit("این بازی منقضی شده است.")
            except Exception as e:
                logger.error(f"CALLBACK: Failed to edit message: {e}")
            return

    # --- Callback data handling ---
    if data == "im_in":
        if session["started"]:
            await event.answer("🚫 بازی شروع شده!", alert=True)
            logger.info(f"CALLBACK: Start game rejected for session {current_key} - already started")
            return

        player_name = user.first_name or user.username or f"User_{user.id}"
        if user.id not in [p["id"] for p in session["players"]]:
            session["players"].append({"id": user.id, "name": player_name, "score": 0})
            await event.answer("✅ شما به لیست پایه‌ها اضافه شدید!", alert=False)
            logger.info(f"CALLBACK: User {user.id} ({player_name}) added to session {current_key}, players: {session['players']}")

            text_to_update = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(session)
            markup = get_initial_markup(session)
            try:
                await event.edit(text=text_to_update, buttons=markup)
                logger.info(f"CALLBACK: Message {current_key} updated with new player list")
                if is_inline and current_key not in active_updaters:
                    logger.info(f"CALLBACK: Starting periodic updater for inline session {current_key}")
                    task = asyncio.create_task(periodic_player_list_updater(app, current_key))
                    active_updaters[current_key] = task
            except Exception as e:
                logger.error(f"CALLBACK_ERROR on im_in: Failed to update message for session {current_key}: {e}", exc_info=True)
        else:
            await event.answer("شما از قبل در لیست هستید!", alert=False)
            logger.info(f"CALLBACK: User {user.id} already in session {current_key}")

    elif data == "start_game":
        if session["started"]:
            await event.answer("بازی قبلاً شروع شده!", alert=True)
            logger.info(f"CALLBACK: Start game rejected for session {current_key} - already started")
            return
        if not session["players"]:
            await event.answer("هنوز هیچکس پایه نیست!", alert=True)
            logger.info(f"CALLBACK: Start game rejected for session {current_key} - no players")
            return
        if user.id != session.get("starter_id"):
            await event.answer("فقط شروع‌کننده می‌تواند بازی را استارت بزند!", alert=True)
            logger.info(f"CALLBACK: Start game rejected for session {current_key} - user {user.id} is not starter")
            return
        
        if current_key in active_updaters:
            active_updaters[current_key].cancel()
            del active_updaters[current_key]
            logger.info(f"CALLBACK: Stopped updater for session {current_key} before starting game")

        session["started"] = True
        session["event"] = event  # ذخیره event برای استفاده در ask_question_in_chat
        logger.info(f"CALLBACK: Game started for session {current_key} by user {user.id}")
        await event.answer("🚀 بازی شروع می‌شود!")
        try:
            await ask_question_in_chat(app, current_key)
            logger.info(f"CALLBACK: ask_question_in_chat called for session {current_key}")
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Failed to start question for session {current_key}: {e}", exc_info=True)

    elif data == "cancel_game":
        if user.id != session.get("starter_id"):
            await event.answer("فقط شروع‌کننده می‌تواند بازی را لغو کند!", alert=True)
            logger.info(f"CALLBACK: Cancel game rejected for session {current_key} - user {user.id} is not starter")
            return

        if current_key in active_updaters:
            active_updaters[current_key].cancel()
            del active_updaters[current_key]
            logger.info(f"CALLBACK: Stopped updater for session {current_key} on cancel")

        text_to_update = "❌ بازی توسط شروع‌کننده لغو شد."
        try:
            await event.edit(text=text_to_update, buttons=None)
            logger.info(f"CALLBACK: Message {current_key} updated to cancelled")
        except Exception as e:
            logger.error(f"CALLBACK_ERROR on cancel: Failed to update message for session {current_key}: {e}", exc_info=True)
        
        if current_key in game_sessions:
            del game_sessions[current_key]
            logger.info(f"CALLBACK: Session {current_key} deleted due to cancellation")

    elif data.startswith("answer|"):
        await handle_answer(app, event, current_key)

# توابع بازی
async def ask_question_in_chat(client, session_key):
    if session_key not in game_sessions:
        logger.error(f"ASK_QUESTION: Session {session_key} not found")
        return
    session = game_sessions[session_key]
    session["responses"] = []  # ریست کردن پاسخ‌ها برای سوال جدید
    session["responded_users"] = []  # ریست کردن کاربران پاسخ‌دهنده

    if session["current_q_index"] >= 10:  # محدود کردن به 10 سوال
        logger.info(f"ASK_QUESTION: No more questions for session {session_key}, announcing results")
        await announce_final_results(client, session_key)
        return

    if not session.get("main_message_id"):
        logger.error(f"ASK_QUESTION: No main_message_id for session {session_key}")
        return

    q = session["questions"][session["current_q_index"]]
    options_list = q["options"][:]
    random.shuffle(options_list)
    buttons = [types.KeyboardButtonCallback(text=opt, data=f"answer|{opt}".encode()) for opt in options_list]
    rows = [types.KeyboardButtonRow(buttons[i:i+2]) for i in range(0, len(buttons), 2)]  # دو ردیف، هر ردیف دو دکمه
    markup = types.ReplyInlineMarkup(rows)

    question_text = (
        f"{get_players_text(session)}\n\n"
        f"سوال {session['current_q_index'] + 1} از 10\n\n"  # نمایش 10 به جای کل سوالات
        f"❓ **{q['question']}**\n\n"
        f"۱۰ ثانیه فرصت پاسخگویی دارید..."
    )

    logger.info(f"ASK_QUESTION: Sending question {session['current_q_index'] + 1} for session {session_key}, is_inline={session['is_inline_message']}, message_id={session['main_message_id']}")

    try:
        if session["is_inline_message"]:
            event = session.get("event")
            if not event:
                logger.error(f"ASK_QUESTION: No event stored for session {session_key}")
                return
            await event.edit(text=question_text, buttons=markup)
            logger.info(f"ASK_QUESTION: Inline message {session['main_message_id']} updated with question {session['current_q_index'] + 1}")
        else:
            await client.edit_message(
                entity=session["main_chat_id"],
                message=session["main_message_id"],
                text=question_text,
                buttons=markup
            )
            logger.info(f"ASK_QUESTION: Chat message {session['main_message_id']} updated with question {session['current_q_index'] + 1}")
        
        session["question_start_time"] = time.time()
        session["active_question"] = True

        timeout_task = asyncio.create_task(question_timeout(client, session_key))
        active_timeouts[session_key] = timeout_task
        logger.info(f"ASK_QUESTION: Started timeout task for session {session_key}")
    except Exception as e:
        logger.error(f"ASK_QUESTION_ERROR: Failed to send question for session {session_key}: {e}", exc_info=True)

async def question_timeout(client, session_key):
    try:
        await asyncio.sleep(10)
        if session_key not in game_sessions:
            logger.error(f"TIMEOUT: Session {session_key} not found")
            return
        session = game_sessions[session_key]
        
        logger.info(f"TIMEOUT: Processing timeout for session {session_key}, question {session['current_q_index'] + 1}")
        
        if session.get("active_question"):
            session["active_question"] = False
            q = session["questions"][session["current_q_index"]]
            correct_answer = q["answer"]
            timeout_text = (
                f"{get_players_text(session)}\n\n"
                f"⏰ زمان پاسخ به سوال تمام شد!\n\n"
                f"جواب صحیح: **{correct_answer}**\n\n"
                f"آماده برای سوال بعدی..."
            )
            try:
                if session["is_inline_message"]:
                    event = session.get("event")
                    if not event:
                        logger.error(f"TIMEOUT: No event stored for session {session_key}")
                        return
                    await event.edit(text=timeout_text, buttons=None)
                    logger.info(f"TIMEOUT: Inline message {session['main_message_id']} updated for timeout")
                else:
                    await client.edit_message(
                        entity=session["main_chat_id"],
                        message=session["main_message_id"],
                        text=timeout_text,
                        buttons=None
                    )
                    logger.info(f"TIMEOUT: Chat message {session['main_message_id']} updated for timeout")
            except Exception as e:
                logger.error(f"TIMEOUT_EDIT_ERROR: Failed for session {session_key}: {e}", exc_info=True)
                logger.info(f"TIMEOUT: Continuing despite edit error for session {session_key}")

            session["current_q_index"] += 1
            session["responses"] = []  # ریست کردن پاسخ‌ها
            session["responded_users"] = []  # ریست کردن کاربران پاسخ‌دهنده
            logger.info(f"TIMEOUT: Moving to next question, current_q_index={session['current_q_index']} for session {session_key}")
            await asyncio.sleep(2)  # انتظار 2 ثانیه‌ای قبل از سوال بعدی
            await ask_question_in_chat(client, session_key)
    except asyncio.CancelledError:
        logger.info(f"TIMEOUT: Task cancelled for session {session_key}")
        if session_key in active_timeouts:
            del active_timeouts[session_key]
        raise
    except Exception as e:
        logger.error(f"TIMEOUT_ERROR: Unexpected error in timeout for session {session_key}: {e}", exc_info=True)
        # ادامه دادن حتی در صورت خطا
        if session_key in game_sessions:
            session = game_sessions[session_key]
            session["current_q_index"] += 1
            session["responses"] = []
            session["responded_users"] = []
            logger.info(f"TIMEOUT: Forcing move to next question, current_q_index={session['current_q_index']} for session {session_key}")
            await asyncio.sleep(10)
            await ask_question_in_chat(client, session_key)

async def announce_final_results(client, session_key):
    if session_key not in game_sessions:
        logger.error(f"ANNOUNCE_RESULTS: Session {session_key} not found")
        return
    session = game_sessions[session_key]

    sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
    final_text = "🏆 نتایج نهایی چالش 🏆\n\n"
    for i, p in enumerate(sorted_players):
        final_text += f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '▫️'} {p['name']}: {p['score']} امتیاز\n"
    final_text += "\nبازی تمام شد!"

    try:
        if session["is_inline_message"]:
            event = session.get("event")
            if not event:
                logger.error(f"ANNOUNCE_RESULTS: No event stored for session {session_key}")
                return
            await event.edit(text=final_text, buttons=None)
            logger.info(f"ANNOUNCE_RESULTS: Inline message {session['main_message_id']} updated with final results")
        else:
            await client.edit_message(
                entity=session["main_chat_id"],
                message=session["main_message_id"],
                text=final_text,
                buttons=None
            )
            logger.info(f"ANNOUNCE_RESULTS: Chat message {session['main_message_id']} updated with final results")
    except Exception as e:
        logger.error(f"ANNOUNCE_RESULTS_ERROR: Failed for session {session_key}: {e}", exc_info=True)
    
    if session_key in game_sessions:
        del game_sessions[session_key]
        logger.info(f"ANNOUNCE_RESULTS: Session {session_key} deleted")
    if session_key in active_timeouts:
        active_timeouts[session_key].cancel()
        del active_timeouts[session_key]
    if session_key in active_updaters:
        active_updaters[session_key].cancel()
        del active_updaters[session_key]

def calculate_score(elapsed):
    elapsed_rounded = int(elapsed)  # گرد کردن به عدد کامل (ثانیه)
    if elapsed_rounded == 1:
        return 20
    elif elapsed_rounded == 2:
        return 18
    elif elapsed_rounded == 3:
        return 16
    elif elapsed_rounded == 4:
        return 14
    elif elapsed_rounded == 5:
        return 12
    elif elapsed_rounded == 6:
        return 10
    elif elapsed_rounded == 7:
        return 8
    elif elapsed_rounded == 8:
        return 6
    elif elapsed_rounded == 9:
        return 4
    else:
        return 0  # اگر زمان بیشتر از ۹ ثانیه باشد، امتیازی داده نمی‌شود

async def handle_answer(client, event, session_key):
    if session_key not in game_sessions:
        logger.error(f"HANDLE_ANSWER: Session {session_key} not found")
        return
    
    session = game_sessions[session_key]
    user = event.sender

    player = next((p for p in session["players"] if p["id"] == user.id), None)
    if not player:
        return await event.answer("شما در این بازی شرکت نکرده‌اید!", alert=True)

    if not session.get("active_question"):
        return await event.answer("این سوال دیگر فعال نیست!", alert=True)

    # بررسی اینکه آیا کاربر قبلاً پاسخ داده است
    if user.id in session["responded_users"]:
        return await event.answer("شما قبلاً به این سوال پاسخ داده‌اید!", alert=True)

    selected = event.data.decode('utf-8').split("|")[1]
    q = session["questions"][session["current_q_index"]]
    correct_answer = q["answer"]
    elapsed = time.time() - session["question_start_time"]
    
    if selected == correct_answer:
        earned_score = calculate_score(elapsed)
        player["score"] += earned_score
        response_text = f"✅ {player['name']}: پاسخ صحیح (+{earned_score} امتیاز، {elapsed:.1f} ثانیه)"
    else:
        response_text = f"❌ {player['name']}: پاسخ اشتباه"
    
    session["responses"].append(response_text)
    session["responded_users"].append(user.id)
    await event.answer(response_text, alert=True)
    logger.info(f"HANDLE_ANSWER: User {user.id} answered for session {session_key}, correct={selected == correct_answer}, score={player['score']}, responses={session['responses']}")

    # به‌روزرسانی پیام سوال بدون نمایش پاسخ‌ها
    question_text = (
        f"{get_players_text(session)}\n\n"
        f"سوال {session['current_q_index'] + 1} از 10\n\n"  # نمایش 10 به جای کل سوالات
        f"❓ **{q['question']}**\n\n"
        f"زمان باقی‌مانده: {max(0, 10 - int(elapsed))} ثانیه..."
    )
    buttons = [types.KeyboardButtonCallback(text=opt, data=f"answer|{opt}".encode()) for opt in q["options"]]
    rows = [types.KeyboardButtonRow(buttons[i:i+2]) for i in range(0, len(buttons), 2)]  # دو ردیف، هر ردیف دو دکمه
    markup = types.ReplyInlineMarkup(rows)

    try:
        if session["is_inline_message"]:
            await event.edit(text=question_text, buttons=markup)
            logger.info(f"HANDLE_ANSWER: Inline message {session['main_message_id']} updated")
        else:
            await client.edit_message(
                entity=session["main_chat_id"],
                message=session["main_message_id"],
                text=question_text,
                buttons=markup
            )
            logger.info(f"HANDLE_ANSWER: Chat message {session['main_message_id']} updated")
    except Exception as e:
        logger.error(f"HANDLE_ANSWER_EDIT_ERROR: Failed for session {session_key}: {e}", exc_info=True)
        logger.info(f"HANDLE_ANSWER: Continuing despite edit error for session {session_key}")

# اجرای دستی ربات
async def main():
    async with app:
        await app.start(bot_token=BOT_TOKEN)
        logger.info("Bot started successfully")
        cleanup_task = asyncio.create_task(cleanup_old_sessions())
        try:
            await app.run_until_disconnected()
        except asyncio.CancelledError:
            logger.info("Received cancellation signal")
        finally:
            # لغو تمام وظایف فعال
            cleanup_task.cancel()
            for task in active_updaters.values():
                task.cancel()
            for task in active_timeouts.values():
                task.cancel()
            active_updaters.clear()
            active_timeouts.clear()
            logger.info("Bot stopped")

if __name__ == "__main__":
    app.loop.run_until_complete(main())
