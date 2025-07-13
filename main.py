import asyncio
import time
import uuid
import logging
import random
import os
from aiohttp import web
from telethon import TelegramClient, events, types
from telethon.tl.types import InputBotInlineResult, InputBotInlineMessageText
# اطمینان حاصل کنید که فایل questions.py در کنار اسکریپت اصلی شما قرار دارد
# from tes.question import questions

# --- نمونه سوالات برای تست ---
# این بخش را با فایل `questions.py` خود جایگزین کنید
questions = [
    {"question": "پایتخت ایران کدام شهر است؟", "options": ["اصفهان", "مشهد", "شیراز", "تهران"], "answer": "تهران"},
    {"question": "کدام سیاره به سیاره سرخ معروف است؟", "options": ["زهره", "مریخ", "مشتری", "زمین"], "answer": "مریخ"},
    {"question": "کدام حیوان بزرگترین حیوان روی زمین است؟", "options": ["فیل", "نهنگ آبی", "زرافه", "کوسه"], "answer": "نهنگ آبی"},
    {"question": "عدد پی تقریباً چند است؟", "options": ["3.14", "2.71", "1.61", "4.20"], "answer": "3.14"},
    {"question": "نویسنده کتاب 'شاهنامه' کیست؟", "options": ["حافظ", "سعدی", "فردوسی", "مولوی"], "answer": "فردوسی"},
    {"question": "کدام اقیانوس بزرگترین اقیانوس جهان است؟", "options": ["اقیانوس اطلس", "اقیانوس هند", "اقیانوس آرام", "اقیانوس منجمد شمالی"], "answer": "اقیانوس آرام"},
    {"question": "بلندترین قله جهان چیست؟", "options": ["کی۲", "کانگچنجونگا", "اورست", "لوتسه"], "answer": "اورست"},
    {"question": "واحد پول کشور ژاپن چیست؟", "options": ["وون", "یوان", "ین", "دلار"], "answer": "ین"},
    {"question": "کدام ویتامین از طریق نور خورشید در بدن تولید می‌شود؟", "options": ["ویتامین C", "ویتامین A", "ویتامین D", "ویتامین B12"], "answer": "ویتامین D"},
    {"question": "سال نوری واحد اندازه‌گیری چیست؟", "options": ["زمان", "سرعت", "فاصله", "وزن"], "answer": "فاصله"},
]
# --- پایان نمونه سوالات ---


# --- راه‌اندازی اولیه ---

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

# مقادیر ثابت ربات
API_ID = os.environ.get('API_ID', '3335796')
API_HASH = os.environ.get('API_HASH', '138b992a0e672e8346d8439c3f42ea78')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '5002292255:AAGc9Lk0LXX1cjfERx6CnVye0A5EUNvgtzU')


# دیکشنری‌های مدیریت وضعیت
game_sessions = {}

# راه‌اندازی کلاینت تلگرام
app = TelegramClient("watermark_bot", api_id=API_ID, api_hash=API_HASH)
logger.info(f"Telethon version: {events.client.telethon.__version__}")


# --- توابع کمکی و پس‌زمینه ---

async def cleanup_old_sessions():
    """هر ۱۰ دقیقه جلسات بازی که بیش از ۱۰ دقیقه از عمرشان گذشته را پاک می‌کند."""
    try:
        while True:
            await asyncio.sleep(600)  # هر 10 دقیقه
            now = time.time()
            expired_keys = [key for key, session in game_sessions.items() if now - session.get("created_at", now) > 600]
            for key in expired_keys:
                logger.info(f"Cleaning up expired session {key}")
                if key in game_sessions:
                    del game_sessions[key]
    except asyncio.CancelledError:
        logger.info("Cleanup task cancelled")
        raise

def get_players_text(session):
    """متن لیست بازیکنان و امتیازاتشان را تولید می‌کند."""
    if not session["players"]:
        return "🧑‍🤝‍🧑 لیست پایه‌ها:\n(هنوز کسی پایه نیست)"

    text = "🧑‍🤝‍🧑 لیست پایه‌ها:\n"
    sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
    player_lines = [
        f"👤 {player['name']}{f' | امتیاز: {player['score']}' if session['started'] else ''}"
        for player in sorted_players
    ]
    text += "\n".join(player_lines)
    return text

def get_initial_markup(session_key):
    """دکمه‌های اولیه بازی را بر اساس وضعیت جلسه تولید می‌کند."""
    session = game_sessions.get(session_key)
    if not session:
        return None

    rows = []
    
    # اگر جلسه هنوز کلید موقت دارد، یعنی اولین کلیک روی پیام اینلاین است
    if session.get("temp_uuid_game_session"):
         rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("🙋‍♂️ من پایه‌ام", data=f"im_in_inline_initial|{session_key}".encode())]))
    else:
        rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("🙋‍♂️ من پایه‌ام", data=b"im_in")]))
    
    rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("🚀 شروع بازی", data=b"start_game")]))

    # دکمه لغو بازی فقط قبل از شروع و توسط شروع‌کننده
    if session["players"] and not session["started"] and session.get("starter_id"):
        rows.append(types.KeyboardButtonRow([types.KeyboardButtonCallback("❌ لغو بازی", data=b"cancel_game")]))

    rows.append(types.KeyboardButtonRow([types.KeyboardButtonSwitchInline("👥 دعوت دوستان", query="")]))
    return types.ReplyInlineMarkup(rows)

def calculate_score(elapsed_seconds):
    """امتیاز را بر اساس زمان پاسخگویی محاسبه می‌کند."""
    scores = {1: 20, 2: 18, 3: 16, 4: 14, 5: 12, 6: 10, 7: 8, 8: 6, 9: 4}
    return scores.get(int(elapsed_seconds), 2) # اگر دیرتر بود حداقل ۲ امتیاز

# --- هندلرهای اصلی ربات ---

@app.on(events.NewMessage(pattern='/start', incoming=True, private=True))
async def start_command_private(event):
    """هنگام دریافت /start در چت خصوصی، یک پیام راهنما با دکمه دعوت ارسال می‌کند."""
    # این جلسه فقط برای نمایش دکمه "دعوت دوستان" است
    await event.respond(
        "🎉 به چالش اطلاعات خوش آمدید!\nبرای شروع یک بازی جدید، دکمه 'دعوت دوستان' را لمس کنید و بازی را در یک گروه به اشتراک بگذارید.",
        buttons=types.ReplyInlineMarkup([
            types.KeyboardButtonRow([types.KeyboardButtonSwitchInline("👥 دعوت دوستان و ایجاد بازی", query="")])
        ])
    )

@app.on(events.InlineQuery())
async def handle_inline_query(event):
    """هنگام فراخوانی ربات در حالت اینلاین، یک گزینه برای ایجاد بازی ایجاد می‌کند."""
    temp_uuid = str(uuid.uuid4())
    
    # یک جلسه موقت با کلید UUID ایجاد می‌شود
    game_sessions[temp_uuid] = {
        "players": [], "started": False, "starter_id": event.sender_id,
        "questions": random.sample(questions, min(10, len(questions))), 
        "is_inline_message": True, "current_q_index": 0, "created_at": time.time(),
        "temp_uuid_game_session": True # نشانه‌ای برای تشخیص این نوع جلسه
    }
    logger.info(f"INLINE_QUERY: New temp session created with key '{temp_uuid}'.")

    markup = get_initial_markup(temp_uuid)
    initial_message_text = (
        "🎉 به چالش اطلاعات خوش آمدید!\n"
        "برای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n"
        f"{get_players_text(game_sessions[temp_uuid])}"
    )

    result = InputBotInlineResult(
        id=str(uuid.uuid4()),
        type='article',
        title="ایجاد چالش اطلاعات!",
        description="دوستان خود را به یک مسابقه هیجان‌انگیز دعوت کنید!",
        send_message=InputBotInlineMessageText(message=initial_message_text, reply_markup=markup)
    )
    await event.answer([result], cache_time=1)

@app.on(events.CallbackQuery())
async def handle_buttons(event):
    """تمام دکمه‌های بازی را مدیریت می‌کند."""
    user = event.sender
    data_str = event.data.decode('utf-8')
    session_key = None
    session = None
    
    is_inline = bool(event.inline_message_id)
    if is_inline:
        session_key = event.inline_message_id
        session = game_sessions.get(session_key)
        
        if not session and data_str.startswith("im_in_inline_initial|"):
            temp_uuid = data_str.split("|")[1]
            temp_session = game_sessions.get(temp_uuid)
            if temp_session:
                session = temp_session
                game_sessions[session_key] = session
                del session["temp_uuid_game_session"]
                del game_sessions[temp_uuid]
                logger.info(f"CALLBACK: Transferred session from temp key '{temp_uuid}' to '{session_key}'.")
                data_str = "im_in"
            else:
                await event.answer("این بازی منقضی شده است. لطفاً یک بازی جدید شروع کنید.", alert=True)
                return
    else:
        # ربات در حالت چت خصوصی یا گروهی معمولی کار نمی‌کند، فقط اینلاین
        return await event.answer("این ربات فقط در حالت اینلاین (inline) کار می‌کند. لطفاً با @ نام ربات را منشن کنید.", alert=True)

    if not session:
        await event.answer("این بازی منقضی شده یا وجود ندارد.", alert=True)
        return

    if data_str == "im_in":
        if session["started"]:
            return await event.answer("🚫 بازی شروع شده!", alert=True)
        
        player_name = user.first_name or user.username or f"User_{user.id}"
        if user.id not in [p["id"] for p in session["players"]]:
            session["players"].append({"id": user.id, "name": player_name, "score": 0})
            await event.answer("✅ شما به لیست پایه‌ها اضافه شدید!", alert=False)
            logger.info(f"CALLBACK: User {user.id} added to session {session_key}")

            text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(session)
            markup = get_initial_markup(session_key)
            await event.edit(text, buttons=markup)
        else:
            await event.answer("شما از قبل در لیست هستید!", alert=False)

    elif data_str == "start_game":
        if session["started"]:
            return await event.answer("بازی قبلاً شروع شده!", alert=True)
        if not session["players"]:
            return await event.answer("هنوز هیچکس پایه نیست!", alert=True)
        if user.id != session.get("starter_id"):
            return await event.answer("فقط شروع‌کننده می‌تواند بازی را استارت بزند!", alert=True)

        session["started"] = True
        logger.info(f"CALLBACK: Game started for session {session_key}")
        await event.answer("🚀 بازی شروع می‌شود!")
        
        asyncio.create_task(run_game_loop(event, session_key))

    elif data_str == "cancel_game":
        if user.id != session.get("starter_id"):
            return await event.answer("فقط شروع‌کننده می‌تواند بازی را لغو کند!", alert=True)
        
        await event.edit("❌ بازی توسط شروع‌کننده لغو شد.", buttons=None)
        if session_key in game_sessions:
            del game_sessions[session_key]
        logger.info(f"CALLBACK: Session {session_key} cancelled and deleted.")

    elif data_str.startswith("answer|"):
        await handle_answer(event, session_key)

async def handle_answer(event, session_key):
    """
    پاسخ کاربر را پردازش می‌کند، امتیاز را در حافظه ثبت می‌کند و فقط یک پیام
    پاپ‌آپ به کاربر نشان می‌دهد، بدون اینکه پیام اصلی بازی را ویرایش کند.
    """
    session = game_sessions.get(session_key)
    if not session:
        return await event.answer("این بازی دیگر وجود ندارد!", alert=True)

    user = event.sender
    
    if not session.get("active_question", False):
        return await event.answer("زمان پاسخ به این سوال تمام شده!", alert=True)
    if user.id in session.get("responded_users", []):
        return await event.answer("شما قبلاً پاسخ داده‌اید!", alert=True)

    player = next((p for p in session["players"] if p["id"] == user.id), None)
    if not player:
        return await event.answer("شما در این بازی شرکت نکرده‌اید!", alert=True)

    session["responded_users"].append(user.id)
    selected = event.data.decode('utf-8').split("|")[1]
    q = session["questions"][session["current_q_index"]]
    elapsed = time.time() - session["question_start_time"]
    
    response_text = "❌ اشتباه بود!"
    if selected == q["answer"]:
        earned_score = calculate_score(elapsed)
        player["score"] += earned_score
        response_text = f"✅ آفرین! {earned_score} امتیاز گرفتی."
    
    await event.answer(response_text, alert=False)

async def run_game_loop(event, session_key):
    """
    موتور و حلقه اصلی بازی. این تابع به تنهایی مسئول نمایش سوالات،
    تایمر معکوس، و نمایش نتایج هر مرحله است.
    """
    session = game_sessions.get(session_key)
    if not session:
        return

    while session.get("current_q_index", 0) < 10:
        if session_key not in game_sessions:
            logger.warning(f"GAME_LOOP: Session {session_key} disappeared. Stopping loop.")
            return

        q_index = session["current_q_index"]
        q = session["questions"][q_index]

        session["active_question"] = True
        session["question_start_time"] = time.time()
        session["responded_users"] = []
        options_list = q["options"][:]
        random.shuffle(options_list)
        session["current_question_options"] = options_list

        buttons = [types.KeyboardButtonCallback(text=opt, data=f"answer|{opt}".encode()) for opt in options_list]
        rows = [types.KeyboardButtonRow(buttons[i:i + 2]) for i in range(0, len(buttons), 2)]
        markup = types.ReplyInlineMarkup(rows)

        for i in range(10, -1, -1):
            if session_key not in game_sessions:
                return

            question_text = (
                f"{get_players_text(session)}\n\n"
                f"سوال {q_index + 1} از 10\n\n"
                f"❓ **{q['question']}**\n\n"
                f"⏳ {i} ثانیه فرصت باقیست..."
            )
            try:
                await event.edit(question_text, buttons=markup)
            except Exception:
                break
            
            if i > 0:
                await asyncio.sleep(1)

        session["active_question"] = False
        logger.info(f"GAME_LOOP: Timeout for question {q_index + 1} in session {session_key}")

        correct_answer = q["answer"]
        final_round_text = (
            f"{get_players_text(session)}\n\n"
            f"⏰ زمان پاسخ تمام شد!\n"
            f"جواب صحیح: **{correct_answer}**\n\n"
            f"آماده برای سوال بعدی..."
        )
        try:
            await event.edit(final_round_text, buttons=None)
        except Exception as e:
            logger.warning(f"GAME_LOOP: Final edit failed for session {session_key}: {e}")

        session["current_q_index"] += 1
        await asyncio.sleep(3)

    if session_key in game_sessions:
        await announce_final_results(event, session_key)

async def announce_final_results(event, session_key):
    """نتایج نهایی بازی را اعلام و جلسه را پاک می‌کند."""
    session = game_sessions.get(session_key)
    if not session: return

    sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
    final_text = "🏆 نتایج نهایی چالش 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(sorted_players):
        medal = medals[i] if i < 3 else '▫️'
        final_text += f"{medal} {p['name']}: {p['score']} امتیاز\n"
    final_text += "\nبازی تمام شد! برای یک بازی دیگر، دوستانتان را دعوت کنید."

    invite_button = types.KeyboardButtonRow([types.KeyboardButtonSwitchInline("👥 دعوت دوستان", query="")])
    final_markup = types.ReplyInlineMarkup([invite_button])
    
    try:
        await event.edit(final_text, buttons=final_markup)
        logger.info(f"ANNOUNCE_RESULTS: Final results sent for session {session_key}")
    except Exception as e:
        logger.error(f"ANNOUNCE_RESULTS_ERROR for session {session_key}: {e}", exc_info=True)
    finally:
        if session_key in game_sessions:
            del game_sessions[session_key]

# --- تابع اصلی و اجرای برنامه ---
async def main():
    """تابع اصلی برای راه‌اندازی ربات، وب‌سرور و تسک‌های پس‌زمینه."""
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
    
    logger.info(f"Starting web server on port {port}...")
    await site.start()
    
    logger.info("Bot is fully running.")
    await app.run_until_disconnected()

    logger.info("Bot disconnected. Cleaning up...")
    cleanup_task.cancel()
    await runner.cleanup()
    logger.info("Cleanup complete. Bot stopped.")

if __name__ == "__main__":
    try:
        app.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
