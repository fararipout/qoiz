
import asyncio
import time
import uuid
import logging
import random
import os
from aiohttp import web
from telethon import TelegramClient, events, types
from telethon.tl.types import InputBotInlineResult, InputBotInlineMessageText
from tes.question import questions
from asyncio import Lock

# تابع برای پاسخ به Health Check هاستینگ
async def health_check(request):
    logger.info("Health check endpoint was called.")
    return web.Response(text="Bot is running and healthy!")

logger = logging.getLogger(__name__)

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
API_ID = os.environ.get('API_ID', '3335796')
API_HASH = os.environ.get('API_HASH', '138b992a0e672e8346d8439c3f42ea78')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '5002292255:AAGc9Lk0LXX1cjfERx6CnVye0A5EUNvgtzU')

app = TelegramClient("watermark_bot", api_id=API_ID, api_hash=API_HASH)

game_sessions = {}
active_timeouts = {}
active_updaters = {}
message_lock = Lock()

# داکیومنت نسخه Telethon هنگام شروع
import telethon
logger.info(f"Telethon version: {telethon.__version__}")

# تابع پاک‌سازی جلسات قدیمی
async def cleanup_old_sessions():
    try:
        while True:
            await asyncio.sleep(600)
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
    sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
    player_lines = []
    for player in sorted_players:
        score_text = f" | امتیاز: {player['score']}" if session["started"] else ""
        player_lines.append(f"👤 {player['name']}{score_text}")
    text += "\n".join(player_lines)
    return text

# تابع کمکی برای ایجاد دکمه‌ها
def get_initial_markup(session, temp_uuid_for_initial_inline=None, is_start_command=False):
    rows = []
    
    if not is_start_command:
        rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("🙋‍♂️ من پایه‌ام", data=b"im_in")]))
        rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("🚀 شروع بازی", data=b"start_game")]))
    
    if session["is_inline_message"] and not session["started"] and temp_uuid_for_initial_inline:
        rows[0] = types.KeyboardButtonRow([types.KeyboardButtonCallback("🙋‍♂️ من پایه‌ام", data=f"im_in_inline_initial|{temp_uuid_for_initial_inline}".encode())])
    
    if session["players"] and not session["started"] and session.get("starter_id"):
        rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("❌ لغو بازی", data=b"cancel_game")]))
    
    rows.append(types.KeyboardButtonRow([types.KeyboardButtonSwitchInline("👥 دعوت دوستان", query="")]))
    return types.ReplyInlineMarkup(rows)

# تابع به‌روزرسانی دوره‌ای زمان باقی‌مانده
async def update_question_timer(client, session_key):
    if session_key not in game_sessions:
        logger.error(f"UPDATE_TIMER: Session {session_key} not found")
        return

    session = game_sessions[session_key]
    if not session.get("active_question"):
        logger.info(f"UPDATE_TIMER: Stopping for session {session_key} - no active question")
        return

    start_time = session["question_start_time"]
    q = session["questions"][session["current_q_index"]]
    buttons = [types.KeyboardButtonCallback(text=opt, data=f"answer|{opt}".encode()) for opt in session["current_question_options"]]
    rows = [types.KeyboardButtonRow(buttons[i:i+2]) for i in range(0, len(buttons), 2)]
    markup = types.ReplyInlineMarkup(rows)

    while time.time() - start_time < 10 and session.get("active_question"):
        elapsed = time.time() - start_time
        remaining = max(0, 10 - int(elapsed))
        question_text = (
            f"{get_players_text(session)}\n\n"
            f"سوال {session['current_q_index'] + 1} از 10\n\n"
            f"❓ **{q['question']}**\n\n"
            f"زمان باقی‌مانده: {remaining} ثانیه..."
        )

        async with message_lock:
            try:
                if session["is_inline_message"]:
                    event = session.get("event")
                    if not event:
                        logger.error(f"UPDATE_TIMER: No event stored for session {session_key}")
                        return
                    await event.edit(text=question_text, buttons=markup)
                else:
                    await client.edit_message(
                        entity=session["main_chat_id"],
                        message=session["main_message_id"],
                        text=question_text,
                        buttons=markup
                    )
                logger.info(f"UPDATE_TIMER: Updated question timer for session {session_key}, remaining={remaining}s")
            except Exception as e:
                logger.error(f"UPDATE_TIMER_ERROR: Failed for session {session_key}: {e}", exc_info=True)
                break

        await asyncio.sleep(3)

# تابع به‌روزرسانی دوره‌ای لیست بازیکنان
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
            markup = get_initial_markup(session, is_start_command=False)
            async with message_lock:
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
        "created_at": time.time(), "responses": [], "responded_users": [],
        "current_question_options": None
    }
    game_sessions[key] = session_data
    logger.info(f"PRIVATE_START: Session created for key '{key}'.")

    text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شروع یک بازی جدید، دکمه 'دعوت دوستان' را لمس کنید و بازی را در یک گروه یا چت خصوصی با دوستانتان به اشتراک بگذارید."
    try:
        sent_message = await event.respond(
            text,
            buttons=get_initial_markup(session_data, is_start_command=True)
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
        "responses": [], "responded_users": [],
        "current_question_options": None
    }
    game_sessions[temp_uuid_game_session] = session_data
    logger.info(f"INLINE_QUERY: New temp session created with key '{temp_uuid_game_session}'.")

    markup = get_initial_markup(session_data, temp_uuid_game_session, is_start_command=False)
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

    if hasattr(event, 'query') and hasattr(event.query, 'msg_id'):
        is_inline = True
        current_key = str(event.query.msg_id.id)
    else:
        current_key = str(event.chat_id)

    logger.info(f"CALLBACK: Received callback from user {user.id} with data '{data}', is_inline={is_inline}, current_key={current_key}")

    async with message_lock:
        if is_inline:
            session = game_sessions.get(current_key)
            if not session:
                if data.startswith("im_in_inline_initial|"):
                    temp_uuid = data.split("|")[1]
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
                markup = get_initial_markup(session, is_start_command=False)
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
            session["event"] = event
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
            if current_key in active_timeouts:
                active_timeouts[current_key].cancel()
                del active_timeouts[current_key]

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
    session["responses"] = []
    session["responded_users"] = []

    if session["current_q_index"] >= 10:
        logger.info(f"ASK_QUESTION: No more questions for session {session_key}, announcing results")
        await announce_final_results(client, session_key)
        return

    if not session.get("main_message_id"):
        logger.error(f"ASK_QUESTION: No main_message_id for session {session_key}")
        await client.send_message(session["main_chat_id"], "خطا: پیام اصلی بازی پیدا نشد!")
        return

    q = session["questions"][session["current_q_index"]]
    options_list = q["options"][:]
    random.shuffle(options_list)
    session["current_question_options"] = options_list

    buttons = [types.KeyboardButtonCallback(text=opt, data=f"answer|{opt}".encode()) for opt in options_list]
    rows = [types.KeyboardButtonRow(buttons[i:i+2]) for i in range(0, len(buttons), 2)]
    markup = types.ReplyInlineMarkup(rows)

    question_text = (
        f"{get_players_text(session)}\n\n"
        f"سوال {session['current_q_index'] + 1} از 10\n\n"
        f"❓ **{q['question']}**\n\n"
        f"زمان باقی‌مانده: 10 ثانیه..."
    )

    async with message_lock:
        try:
            if session["is_inline_message"]:
                event = session.get("event")
                if not event:
                    logger.error(f"ASK_QUESTION: No event stored for session {session_key}")
                    await announce_final_results(client, session_key)
                    return
                await event.edit(text=question_text, buttons=markup)
            else:
                await client.edit_message(
                    entity=session["main_chat_id"],
                    message=session["main_message_id"],
                    text=question_text,
                    buttons=markup
                )
            logger.info(f"ASK_QUESTION: Question {session['current_q_index'] + 1} sent for session {session_key}")
        except Exception as e:
            logger.error(f"ASK_QUESTION_ERROR: Failed to send question for session {session_key}: {e}", exc_info=True)
            await client.send_message(session["main_chat_id"], "خطا در نمایش سوال. بازی متوقف شد.")
            await announce_final_results(client, session_key)
            return

    session["question_start_time"] = time.time()
    session["active_question"] = True

    timeout_task = asyncio.create_task(question_timeout(client, session_key))
    active_timeouts[session_key] = timeout_task
    timer_task = asyncio.create_task(update_question_timer(client, session_key))
    active_updaters[session_key] = timer_task

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

            # محاسبه امتیازات برای همه پاسخ‌ها
            for response in session["responses"]:
                user_id = response["user_id"]
                selected = response["answer"]
                elapsed = response["elapsed"]
                player = next((p for p in session["players"] if p["id"] == user_id), None)
                if player and selected == correct_answer:
                    earned_score = calculate_score(elapsed)
                    player["score"] += earned_score
                    response["result"] = f"✅ درست | {earned_score} امتیاز"
                else:
                    response["result"] = "❌ اشتباه"

            # ایجاد متن برای نمایش نتایج
            result_text = (
                f"{get_players_text(session)}\n\n"
                f"⏰ زمان پاسخ به سوال تمام شد!\n\n"
                f"جواب صحیح: **{correct_answer}**\n\n"
                "نتایج پاسخ‌ها:\n" + "\n".join([f"👤 {next(p['name'] for p in session['players'] if p['id'] == r['user_id'])}: {r['result']}" for r in session["responses"]]) + "\n\n"
                f"آماده برای سوال بعدی..."
            )

            async with message_lock:
                try:
                    if session["is_inline_message"]:
                        event = session.get("event")
                        if not event:
                            logger.error(f"TIMEOUT: No event stored for session {session_key}")
                            return
                        await event.edit(text=result_text, buttons=None)
                    else:
                        await client.edit_message(
                            entity=session["main_chat_id"],
                            message=session["main_message_id"],
                            text=result_text,
                            buttons=None
                        )
                    logger.info(f"TIMEOUT: Message {session['main_message_id']} updated with results")
                except Exception as e:
                    logger.error(f"TIMEOUT_EDIT_ERROR: Failed for session {session_key}: {e}", exc_info=True)

            session["current_q_index"] += 1
            session["responses"] = []
            session["responded_users"] = []
            if "current_question_options" in session:
                del session["current_question_options"]

            logger.info(f"TIMEOUT: Moving to next question, current_q_index={session['current_q_index']} for session {session_key}")
            await asyncio.sleep(2)
            await ask_question_in_chat(client, session_key)
    except asyncio.CancelledError:
        logger.info(f"TIMEOUT: Task cancelled for session {session_key}")
        if session_key in active_timeouts:
            del active_timeouts[session_key]
        raise
    except Exception as e:
        logger.error(f"TIMEOUT_ERROR: Unexpected error in timeout for session {session_key}: {e}", exc_info=True)
        if session_key in game_sessions:
            await announce_final_results(client, session_key)

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

    invite_button = types.KeyboardButtonRow([types.KeyboardButtonSwitchInline("👥 دعوت دوستان", query="")])
    final_markup = types.ReplyInlineMarkup([invite_button])

    async with message_lock:
        try:
            if session["is_inline_message"]:
                event = session.get("event")
                if not event:
                    logger.error(f"ANNOUNCE_RESULTS: No event stored for session {session_key}")
                    return
                await event.edit(text=final_text, buttons=final_markup)
            else:
                await client.edit_message(
                    entity=session["main_chat_id"],
                    message=session["main_message_id"],
                    text=final_text,
                    buttons=final_markup
                )
            logger.info(f"ANNOUNCE_RESULTS: Message {session['main_message_id']} updated with final results")
        except Exception as e:
            logger.error(f"ANNOUNCE_RESULTS_ERROR: Failed for session {session_key}: {e}", exc_info=True)
    
    if session_key in game_sessions:
        del game_sessions[session_key]
    if session_key in active_timeouts:
        active_timeouts[session_key].cancel()
        del active_timeouts[session_key]
    if session_key in active_updaters:
        active_updaters[session_key].cancel()
        del active_updaters[session_key]

def calculate_score(elapsed):
    elapsed_rounded = int(elapsed)
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
        return 0

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

    if user.id in session["responded_users"]:
        return await event.answer("شما قبلاً به این سوال پاسخ داده‌اید!", alert=True)

    selected = event.data.decode('utf-8').split("|")[1]
    elapsed = time.time() - session["question_start_time"]

    session["responses"].append({
        "user_id": user.id,
        "answer": selected,
        "elapsed": elapsed
    })
    session["responded_users"].append(user.id)
    await event.answer("پاسخ شما ثبت شد!", alert=False)
    logger.info(f"HANDLE_ANSWER: User {user.id} answered for session {session_key}, answer={selected}, elapsed={elapsed}")

# اجرای دستی ربات
async def main():
    await app.start(bot_token=BOT_TOKEN)
    logger.info("Bot client started successfully.")

    cleanup_task = asyncio.create_task(cleanup_old_sessions())
    logger.info("Cleanup task scheduled.")

    webapp = web.Application()
    webapp.router.add_get('/', health_check)

    runner = web.AppRunner(webapp)
    await runner.setup()
    
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    logger.info(f"Starting web server on port {port} to handle health checks...")
    await site.start()
    
    logger.info("Bot is fully running and waiting for events. Web server is active.")
    
    await app.run_until_disconnected()

    logger.info("Bot disconnected. Cleaning up resources...")
    cleanup_task.cancel()
    await runner.cleanup()
    logger.info("Cleanup complete. Bot stopped.")

if __name__ == "__main__":
    try:
        app.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user. Exiting.")
