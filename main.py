import asyncio
import time
import uuid
import logging
import random
import os
from aiohttp import web
from telethon import TelegramClient, events, types
from telethon.tl.types import InputBotInlineResult, InputBotInlineMessageText
from telethon.errors.rpcerrorlist import MessageNotModifiedError

# اطمینان حاصل کنید که این خط از حالت کامنت خارج شده و به فایل شما اشاره دارد
# from tes.question import questions
# برای تست، یک لیست سوالات نمونه اضافه می‌کنیم
questions = [
    {"question": "پایتخت ایران کجاست؟", "options": ["تهران", "اصفهان", "شیراز", "تبریز"], "answer": "تهران"},
    {"question": "کدام سیاره به عنوان سیاره سرخ شناخته می‌شود؟", "options": ["مریخ", "زهره", "مشتری", "زمین"], "answer": "مریخ"},
    {"question": "بزرگترین اقیانوس جهان کدام است؟", "options": ["آرام", "اطلس", "هند", "منجمد جنوبی"], "answer": "آرام"},
]


# تابع برای پاسخ به Health Check هاستینگ
async def health_check(request):
    logger.info("Health check endpoint was called.")
    return web.Response(text="Bot is running and healthy!")

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

# داکیومنت نسخه Telethon هنگام شروع
import telethon
logger.info(f"Telethon version: {telethon.__version__}")

# تابع کمکی و ایمن برای لغو و حذف تایمر
def cancel_timeout_task(session_key):
    if session_key in active_timeouts:
        task = active_timeouts.pop(session_key)
        if not task.done():
            task.cancel()
            logger.info(f"TASK_CANCEL: Timeout task for session {session_key} was cancelled and removed.")
            return True
    return False

# تابع پاک‌سازی جلسات قدیمی
async def cleanup_old_sessions():
    try:
        while True:
            await asyncio.sleep(600)  # هر 10 دقیقه
            now = time.time()
            expired_keys = [key for key, session in game_sessions.items() if now - session.get("created_at", 0) > 1200]
            for key in expired_keys:
                logger.info(f"CLEANUP: Cleaning up expired session {key}")
                cancel_timeout_task(key)
                if key in game_sessions:
                    del game_sessions[key]
    except asyncio.CancelledError:
        logger.info("Cleanup task cancelled")
        raise

# تابع کمکی برای ایجاد متن لیست بازیکنان
def get_players_text(session):
    if not session["players"]:
        return "🧑‍🤝‍🧑 لیست پایه‌ها:\n(هنوز کسی پایه نیست)"
    text = "🧑‍🤝‍🧑 لیست پایه‌ها:\n"
    sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
    player_lines = [f"👤 {p['name']}{f' | امتیاز: {p['score']}' if session['started'] else ''}" for p in sorted_players]
    text += "\n".join(player_lines)
    return text

# تابع کمکی برای ایجاد دکمه‌های اولیه
def get_initial_markup(session_key):
    session = game_sessions[session_key]
    rows = [
        types.KeyboardButtonRow([types.KeyboardButtonCallback("🙋‍♂️ من پایه‌ام", data=f"im_in|{session_key}".encode())]),
        types.KeyboardButtonRow([types.KeyboardButtonCallback("🚀 شروع بازی", data=f"start_game|{session_key}".encode())])
    ]
    if session["players"]:
        rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("❌ لغو بازی", data=f"cancel_game|{session_key}".encode())]))
    rows.append(types.KeyboardButtonRow([types.KeyboardButtonSwitchInline("👥 دعوت دوستان", query="")]))
    return types.ReplyInlineMarkup(rows)

# تابع کمکی و مرکزی برای ویرایش پیام
async def edit_game_message(client, session, text, buttons):
    try:
        # <<< بهبود: اگر session event وجود نداشت، از ویرایش صرف نظر کن >>>
        if session["is_inline_message"]:
            if "event" in session and session["event"]:
                await session["event"].edit(text=text, buttons=buttons)
            else:
                logger.error(f"EDIT_HELPER: Cannot edit inline message for session {session['session_key']} because event object is missing.")
                return
        else:
            await client.edit_message(entity=session["main_chat_id"], message=session["main_message_id"], text=text, buttons=buttons)
        logger.info(f"EDIT_HELPER: Message updated for session {session['session_key']}")
    except MessageNotModifiedError:
        logger.warning(f"EDIT_HELPER: Message not modified for session {session['session_key']}. Skipping.")
    except Exception as e:
        logger.error(f"EDIT_HELPER: Failed to edit message for session {session['session_key']}: {e}", exc_info=True)


# --- شروع بازی و مدیریت دکمه‌های اولیه ---

@app.on(events.NewMessage(pattern='/start', incoming=True))
async def start_command_handler(event):
    if not event.is_private:
        await event.respond("برای شروع بازی در گروه، لطفاً نام من را تایپ کرده و گزینه 'ایجاد چالش' را انتخاب کنید.", reply_to=event.message)
        return
    chat_id = event.chat_id
    session_key = str(chat_id)
    
    cancel_timeout_task(session_key)

    session = {
        "session_key": session_key, "players": [], "started": False, "starter_id": event.sender_id,
        "questions": random.sample(questions, min(10, len(questions))), "is_inline_message": False,
        "main_message_id": None, "main_chat_id": chat_id, "current_q_index": -1, # <<< تغییر: شروع از -1
        "created_at": time.time(), "responded_users": set(), "event": None,
        "active_question": False
    }
    game_sessions[session_key] = session
    logger.info(f"SESSION_CREATE: Private session '{session_key}' created for user {event.sender_id}.")
    text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(session)
    markup = get_initial_markup(session_key)
    sent_message = await event.respond(text, buttons=markup)
    session["main_message_id"] = sent_message.id


@app.on(events.InlineQuery())
async def handle_inline_query(event):
    session_key = str(uuid.uuid4())
    session = {
        "session_key": session_key, "players": [], "started": False, "starter_id": event.sender_id,
        "questions": random.sample(questions, min(10, len(questions))), "is_inline_message": True,
        "main_message_id": None, "main_chat_id": None, "current_q_index": -1, # <<< تغییر: شروع از -1
        "created_at": time.time(), "responded_users": set(), "event": None,
        "active_question": False
    }
    game_sessions[session_key] = session
    logger.info(f"SESSION_CREATE: Inline session '{session_key}' created for user {event.sender_id}.")
    initial_text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(session)
    markup = get_initial_markup(session_key)
    result = InputBotInlineResult(id=str(uuid.uuid4()), type='article', title="ایجاد چالش اطلاعات!",
                                  description="دوستان خود را به یک مسابقه هیجان‌انگیز دعوت کنید!",
                                  send_message=InputBotInlineMessageText(message=initial_text, reply_markup=markup))
    await event.answer([result], cache_time=1)


@app.on(events.CallbackQuery())
async def handle_buttons(event):
    data_parts = event.data.decode('utf-8').split('|')
    action = data_parts[0]
    session_key = data_parts[1] if len(data_parts) > 1 else None
    
    if not session_key or session_key not in game_sessions:
        await event.answer("این بازی منقضی شده یا دیگر وجود ندارد. لطفاً یک بازی جدید شروع کنید.", alert=True)
        return
    
    session = game_sessions[session_key]
    
    # <<< بهبود: ثبت event در هر تعامل برای اطمینان از قابلیت ویرایش >>>
    if session["is_inline_message"] and "event" not in session or session["event"] is None:
        session["event"] = event
        logger.info(f"EVENT_CAPTURE: Captured event object for inline session {session_key}")

    if action == "im_in":
        if session["started"]:
            await event.answer("🚫 بازی شروع شده و دیگر نمی‌توانید به آن ملحق شوید!", alert=True)
            return
        user_id = event.sender_id
        if user_id not in [p["id"] for p in session["players"]]:
            user = await event.get_sender()
            player_name = user.first_name or user.username or f"User_{user_id}"
            session["players"].append({"id": user_id, "name": player_name, "score": 0})
            await event.answer("✅ شما به لیست پایه‌ها اضافه شدید!", alert=False)
            text_to_update = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(session)
            markup = get_initial_markup(session_key)
            await edit_game_message(app, session, text_to_update, markup)
        else:
            await event.answer("شما از قبل در لیست هستید!", alert=False)

    elif action == "start_game":
        if event.sender_id != session.get("starter_id"):
            await event.answer("فقط شروع‌کننده می‌تواند بازی را استارت بزند!", alert=True)
            return
        if not session["players"]:
            await event.answer("هنوز هیچکس پایه نیست! نمی‌توان بازی را شروع کرد.", alert=True)
            return
        if session["started"]:
            await event.answer("بازی قبلاً شروع شده است!", alert=True)
            return
            
        await event.answer("🚀 بازی شروع می‌شود!")
        session["started"] = True
        # <<< منطق جدید: فراخوانی تابع پیشروی به مرحله بعد >>>
        await proceed_to_next_step(app, session_key)

    elif action == "cancel_game":
        if event.sender_id != session.get("starter_id"):
            await event.answer("فقط شروع‌کننده می‌تواند بازی را لغو کند!", alert=True)
            return
        text_to_update = "❌ بازی توسط شروع‌کننده لغو شد."
        await edit_game_message(app, session, text_to_update, None)
        cancel_timeout_task(session_key)
        if session_key in game_sessions:
            del game_sessions[session_key]
        logger.info(f"SESSION_CANCEL: Session {session_key} was cancelled by starter.")

    elif action == "answer":
        await handle_answer(app, event, session_key, data_parts[2])


# --- توابع اصلی جریان بازی (بازنویسی شده برای رفع مشکل) ---

def calculate_score(elapsed):
    return max(0, 20 - (int(elapsed) * 2))

async def handle_answer(client, event, session_key, selected_option):
    session = game_sessions.get(session_key)
    if not session: return

    user_id = event.sender_id
    if not session.get("active_question"):
        await event.answer("زمان پاسخ به این سوال تمام شده است!", alert=True)
        return

    player = next((p for p in session["players"] if p["id"] == user_id), None)
    if not player:
        await event.answer("شما در این بازی شرکت نکرده‌اید!", alert=True)
        return

    if user_id in session["responded_users"]:
        await event.answer("شما قبلاً به این سوال پاسخ داده‌اید!", alert=True)
        return

    session["responded_users"].add(user_id)
    q_index = session["current_q_index"]
    q = session["questions"][q_index]
    correct_answer = q["answer"]
    elapsed = time.time() - session["question_start_time"]
    response_text = "❌ اشتباه بود!"
    if selected_option == correct_answer:
        earned_score = calculate_score(elapsed)
        player["score"] += earned_score
        response_text = f"✅ پاسخ صحیح! | {earned_score}+ امتیاز"
    await event.answer(response_text, alert=False)
    logger.info(f"ANSWER: User {user_id} in session {session_key} answered. Correct: {selected_option == correct_answer}. New score: {player['score']}")

    # <<< بهبود کلیدی: اگر همه پاسخ دادند، بازی را فوراً به مرحله بعد ببر >>>
    if len(session["responded_users"]) == len(session["players"]):
        if cancel_timeout_task(session_key): # تایمر را لغو کن
            logger.info(f"ALL_ANSWERED: All players have responded. Proceeding to next step for session {session_key}.")
            await proceed_to_next_step(client, session_key)

async def ask_question_in_chat(client, session_key):
    session = game_sessions.get(session_key)
    if not session: return

    cancel_timeout_task(session_key) # لغو هر تایمر قدیمی

    session["responded_users"].clear()
    q_index = session["current_q_index"]
    q = session["questions"][q_index]
    options_list = q["options"][:]
    random.shuffle(options_list)
    
    buttons = [types.KeyboardButtonCallback(text=opt, data=f"answer|{session_key}|{opt}".encode()) for opt in options_list]
    rows = [types.KeyboardButtonRow(buttons[i:i+2]) for i in range(0, len(buttons), 2)]
    markup = types.ReplyInlineMarkup(rows)

    question_text = (
        f"سوال {q_index + 1} از {len(session['questions'])}\n\n"
        f"❓ **{q['question']}**\n\n"
        f"۱۰ ثانیه فرصت پاسخگویی دارید..."
    )
    full_text = get_players_text(session) + "\n\n" + question_text
    
    session["question_start_time"] = time.time()
    session["active_question"] = True # <<< وضعیت سوال فعال شد

    await edit_game_message(client, session, full_text, markup)
    
    timeout_task = asyncio.create_task(question_timeout(client, session_key, q_index))
    active_timeouts[session_key] = timeout_task
    logger.info(f"ASK_QUESTION: Question {q_index + 1} sent. New timeout task created for session {session_key}.")

async def question_timeout(client, session_key, question_index_when_created):
    try:
        await asyncio.sleep(10.1) # کمی بیشتر برای جلوگیری از race condition
        session = game_sessions.get(session_key)
        
        # <<< بررسی مهم: آیا این تایمر هنوز معتبر است؟ >>>
        if not session or not session.get("active_question") or session.get("current_q_index") != question_index_when_created:
            logger.warning(f"TIMEOUT: Timeout for session {session_key} is stale or irrelevant. Aborting.")
            return
            
        logger.info(f"TIMEOUT: Processing timeout for session {session_key}, question {session['current_q_index'] + 1}.")
        session["active_question"] = False # <<< وضعیت سوال غیرفعال شد
        
        q = session["questions"][session["current_q_index"]]
        correct_answer = q["answer"]
        timeout_text = (
            f"{get_players_text(session)}\n\n"
            f"⏰ زمان پاسخ تمام شد!\n"
            f"جواب صحیح: **{correct_answer}**\n\n"
            f"آماده برای مرحله بعد..."
        )
        await edit_game_message(client, session, timeout_text, None)
        
        # <<< منطق جدید: فقط تابع پیشروی را فراخوانی کن >>>
        await proceed_to_next_step(client, session_key)

    except asyncio.CancelledError:
        logger.info(f"TIMEOUT: Task for session {session_key} was cancelled as expected.")
    except Exception as e:
        logger.error(f"TIMEOUT_ERROR: Unexpected error for session {session_key}: {e}", exc_info=True)


# <<< تابع جدید: مسئول پیشروی در بازی >>>
async def proceed_to_next_step(client, session_key):
    try:
        session = game_sessions.get(session_key)
        if not session: return

        # اگر سوالی در جریان بود، یک مکث کوتاه برای نمایش نتیجه آن ایجاد کن
        if session["active_question"] == False and session["current_q_index"] != -1:
             await asyncio.sleep(3)

        session["current_q_index"] += 1
        
        if session["current_q_index"] < len(session["questions"]):
            await ask_question_in_chat(client, session_key)
        else:
            await announce_final_results(client, session_key)
    except Exception as e:
        logger.error(f"PROCEED_ERROR: Error in proceeding step for session {session_key}: {e}", exc_info=True)


async def announce_final_results(client, session_key):
    session = game_sessions.get(session_key)
    if not session: return

    sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
    final_text = "🏆 نتایج نهایی چالش 🏆\n\n"
    if sorted_players:
        for i, p in enumerate(sorted_players):
            emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "▫️"
            final_text += f"{emoji} {p['name']}: {p['score']} امتیاز\n"
    else:
        final_text += "هیچ بازیکنی در این دور شرکت نکرد."
    
    final_text += "\nبازی تمام شد! برای شروع یک بازی جدید، از دکمه زیر استفاده کنید."
    invite_button = types.KeyboardButtonRow([types.KeyboardButtonSwitchInline("👥 شروع یک بازی جدید", query="")])
    final_markup = types.ReplyInlineMarkup([invite_button])
    
    await edit_game_message(client, session, final_text, final_markup)
    
    cancel_timeout_task(session_key)
    if session_key in game_sessions:
        del game_sessions[session_key]
    logger.info(f"SESSION_END: Final results announced and session {session_key} cleaned up.")


# --- بخش اصلی اجرای ربات ---

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
        # در نسخه‌های جدید پایتون get_event_loop ممکن است Deprecated باشد
        # استفاده از asyncio.run(main()) راه مدرن‌تری است، اما کد شما هم کار می‌کند
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user. Exiting.")
