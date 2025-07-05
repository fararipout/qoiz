from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent
from tes.question import questions
import asyncio
import time
import uuid
import logging
import random

# تنظیم لاگ دقیق‌تر برای عیب‌یابی
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# راه‌اندازی ربات
API_ID = '3335796'
API_HASH = '138b992a0e672e8346d8439c3f42ea78'
BOT_TOKEN = '7136875110:AAGr1EREy_qPMgxVbuE4B0cHGVcwWudOrus'

app = Client("watermark_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

game_sessions = {}

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
def get_initial_markup(session):
    buttons = [
        [InlineKeyboardButton("🙋‍♂️ من پایه‌ام", callback_data="im_in")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="start_game")]
    ]
    if session["players"] and not session["started"] and session.get("starter_id"):
        buttons.append([InlineKeyboardButton("❌ لغو بازی", callback_data="cancel_game")])
        
    buttons.append([InlineKeyboardButton("👥 دعوت دوستان", switch_inline_query="invite")])
    return InlineKeyboardMarkup(buttons)

# شروع اولیه
@app.on_message(filters.command("start") & filters.private)
async def start_command_private(client, message):
    chat_id = message.chat.id
    key = str(chat_id) # در چت خصوصی، chat_id را به عنوان key استفاده می‌کنیم
    
    # اگر قبلا جلسه‌ای با این chat_id وجود دارد، آن را حذف می‌کنیم تا جلسه جدیدی شروع شود.
    if key in game_sessions:
        del game_sessions[key]

    game_sessions[key] = {
        "players": [],
        "started": False,
        "finished_players": 0,
        "starter_id": message.from_user.id,
        "questions": random.sample(questions, len(questions)),
        "inline_message_id": None, # برای private chat این null می‌ماند
        "chat_id": chat_id,       # برای private chat این را ذخیره می‌کنیم
        "message_id": None        # این بعد از ارسال پیام اول ست می‌شود
    }
    
    logger.info(f"PRIVATE_START: Session created for key '{key}'")
    
    session = game_sessions[key]
    text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید."
    
    sent_message = await message.reply(
        f"{text}\n\n{get_players_text(session)}",
        reply_markup=get_initial_markup(session)
    )
    # ذخیره message_id برای ویرایش‌های بعدی در چت خصوصی
    session["message_id"] = sent_message.id
    logger.info(f"PRIVATE_START: Message ID {sent_message.id} stored for session '{key}'")

# هندلر برای inline query
@app.on_inline_query()
async def handle_inline_query(client, inline_query):
    query = inline_query.query
    if query != "invite":
        return

    session_key = str(uuid.uuid4()) # استفاده از UUID برای کلید جلسه اینلاین
    game_sessions[session_key] = {
        "players": [],
        "started": False,
        "finished_players": 0,
        "starter_id": inline_query.from_user.id,
        "questions": random.sample(questions, len(questions)),
        "inline_message_id": None, # این در CallbackQuery بعد از ارسال ست می‌شود
        "chat_id": None,         # برای inline message این null می‌ماند
        "message_id": None       # برای inline message این null می‌ماند
    }
    
    logger.info(f"INLINE_QUERY: New session created with key '{session_key}'")
    
    markup = get_initial_markup(game_sessions[session_key])
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="دعوت به چالش!",
            input_message_content=InputTextMessageContent(
                "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(game_sessions[session_key])
            ),
            reply_markup=markup,
            description="دوستانت رو به چالش دعوت کن!"
        )
    ]
    await inline_query.answer(results, cache_time=1)

# هندل دکمه‌ها
@app.on_callback_query()
async def handle_buttons(client, callback_query):
    global game_sessions
    
    user = callback_query.from_user
    data = callback_query.data
    
    # تعیین کلید جلسه بر اساس اینکه پیام اینلاین است یا خصوصی
    key = None
    if callback_query.inline_message_id:
        # برای پیام‌های اینلاین، inline_message_id همان کلید جلسه است
        key = callback_query.inline_message_id
    elif callback_query.message and callback_query.message.chat:
        # برای پیام‌های خصوصی، chat_id همان کلید جلسه است
        key = str(callback_query.message.chat.id)
    
    if not key:
        logger.error(f"CALLBACK: Could not determine session key for callback {callback_query.id}")
        return await callback_query.answer("خطا در یافتن جلسه بازی!", show_alert=True)


    is_inline_message = bool(callback_query.inline_message_id)

    logger.info(f"CALLBACK: Received '{data}' from user {user.id}. Key: '{key}', IsInlineMessage: {is_inline_message}")

    if key not in game_sessions:
        logger.warning(f"CALLBACK: No session for key '{key}'. This might be an old message. Ignoring.")
        # اگر جلسه پیدا نشد، احتمالا پیام خیلی قدیمی است یا ربات ریست شده
        await callback_query.answer("این بازی منقضی شده یا قبلاً بسته شده است. لطفا یک بازی جدید شروع کنید.", show_alert=True)
        # تلاش برای حذف دکمه‌ها از پیام قدیمی
        try:
            if is_inline_message:
                await client.edit_inline_message_text(
                    inline_message_id=key,
                    text="این بازی منقضی شده است. لطفا یک بازی جدید شروع کنید.",
                    reply_markup=None
                )
            elif callback_query.message:
                await callback_query.message.edit_text(
                    text="این بازی منقضی شده است. لطفا یک بازی جدید شروع کنید.",
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Could not edit expired message for key '{key}'. Error: {str(e)}")
        return

    session = game_sessions[key]

    # اگر پیام اینلاین است، inline_message_id را در session ذخیره کن
    if is_inline_message and not session["inline_message_id"]:
        session["inline_message_id"] = key
        logger.info(f"CALLBACK: Inline message ID set to '{key}' for session")
    # اگر پیام خصوصی است، chat_id و message_id را در session ذخیره کن (اگر قبلا ذخیره نشده)
    elif not is_inline_message and callback_query.message and not session["message_id"]:
        session["chat_id"] = callback_query.message.chat.id
        session["message_id"] = callback_query.message.id
        logger.info(f"CALLBACK: Private message (chat:{session['chat_id']}, msg:{session['message_id']}) stored for session '{key}'")


    if data == "im_in":
        if session["started"]:
            return await callback_query.answer("🚫 بازی شروع شده و نمی‌توانید اضافه شوید!", show_alert=True)
            
        player_name = user.first_name or user.username or f"User_{user.id}"
        if user.id not in [p["id"] for p in session["players"]]:
            session["players"].append({
                "id": user.id,
                "name": player_name,
                "score": 0,
                "current_q": 0,
                "start_time": 0
            })
            await callback_query.answer("✅ شما به لیست پایه‌ها اضافه شدید!", show_alert=False)
            logger.info(f"CALLBACK: User {user.id} ({player_name}) added to session {key}. Players: {len(session['players'])}")
        else:
            await callback_query.answer("شما از قبل در لیست هستید!", show_alert=False)
            logger.info(f"CALLBACK: User {user.id} already in session {key}.")
        
        text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(session)
        markup = get_initial_markup(session)
        logger.info(f"CALLBACK: Attempting to update message with text: {text[:50]}... and {len(session['players'])} players")
        try:
            if session["inline_message_id"]: # اگر inline_message_id ست شده است، یعنی پیام اینلاین است
                await client.edit_inline_message_text(
                    inline_message_id=session["inline_message_id"],
                    text=text,
                    reply_markup=markup
                )
                logger.info(f"CALLBACK: Inline message updated successfully for key '{key}' using {session['inline_message_id']}")
            elif session["chat_id"] and session["message_id"]: # اگر chat_id و message_id ست شده است، یعنی پیام خصوصی است
                await client.edit_message_text(
                    chat_id=session["chat_id"],
                    message_id=session["message_id"],
                    text=text,
                    reply_markup=markup
                )
                logger.info(f"CALLBACK: Private message updated successfully for key '{key}' (chat:{session['chat_id']}, msg:{session['message_id']})")
            else:
                logger.warning(f"CALLBACK: No valid message identifier found for session {key} to update.")

            await asyncio.sleep(0.1)  # تأخیر کوچک برای اطمینان از آپدیت
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Failed to update message for key '{key}'. Error: {str(e)}")
            await callback_query.answer(
                "خطا در بروزرسانی! 😔\n(اگر در گروه هستید، مطمئن شوید ربات ادمین است)",
                show_alert=True
            )

    elif data == "start_game":
        if session["started"]:
            return await callback_query.answer("بازی قبلاً شروع شده!", show_alert=True)
        if not session["players"]:
            return await callback_query.answer("هنوز هیچکس پایه نیست!", show_alert=True)
        if user.id != session["starter_id"]:
            return await callback_query.answer("فقط شروع‌کننده بازی می‌تواند آن را استارت بزند!", show_alert=True)

        session["started"] = True
        logger.info(f"Game started for session {key} by user {user.id}")
        
        text = "🚀 بازی شروع شد! سوالات به صورت خصوصی برایتان ارسال می‌شود..."
        try:
            if session["inline_message_id"]:
                await client.edit_inline_message_text(
                    inline_message_id=session["inline_message_id"],
                    text=text,
                    reply_markup=None
                )
                logger.info(f"CALLBACK: Inline message updated for game start, key '{key}'")
            elif session["chat_id"] and session["message_id"]:
                await client.edit_message_text(
                    chat_id=session["chat_id"],
                    message_id=session["message_id"],
                    text=text,
                    reply_markup=None
                )
                logger.info(f"CALLBACK: Private message updated for game start, key '{key}'")
            else:
                logger.warning(f"CALLBACK: No valid message identifier found for session {key} to update on game start.")
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Failed to update message on game start for session {key}: {str(e)}")
            
        for player in session["players"]:
            asyncio.create_task(send_question(player["id"], key))

    elif data == "cancel_game":
        if user.id != session.get("starter_id"):
            return await callback_query.answer("فقط شروع‌کننده بازی می‌تواند آن را لغو کند!", show_alert=True)
            
        text = "❌ بازی توسط شروع‌کننده لغو شد."
        try:
            if session["inline_message_id"]:
                await client.edit_inline_message_text(
                    inline_message_id=session["inline_message_id"],
                    text=text,
                    reply_markup=None
                )
                logger.info(f"CALLBACK: Inline message updated for game cancel, key '{key}'")
            elif session["chat_id"] and session["message_id"]:
                await client.edit_message_text(
                    chat_id=session["chat_id"],
                    message_id=session["message_id"],
                    text=text,
                    reply_markup=None
                )
                logger.info(f"CALLBACK: Private message updated for game cancel, key '{key}'")
            else:
                logger.warning(f"CALLBACK: No valid message identifier found for session {key} to update on game cancel.")
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Failed to update message on game cancel for session {key}: {str(e)}")
        
        # بعد از به‌روزرسانی پیام، جلسه را حذف می‌کنیم.
        if key in game_sessions:
            del game_sessions[key]
            logger.info(f"Game session {key} cancelled and deleted by user {user.id}")


    elif data.startswith("answer|"):
        await handle_answer(client, callback_query, key)

def calculate_score(elapsed):
    if elapsed <= 2: return 20
    elif elapsed <= 4: return 15
    elif elapsed <= 6: return 10
    elif elapsed <= 8: return 5
    else: return 2

async def send_question(user_id, session_key):
    if session_key not in game_sessions:
        logger.warning(f"SEND_QUESTION: Session {session_key} not found. Can't send question to {user_id}.")
        return

    session = game_sessions[session_key]
    player = next((p for p in session["players"] if p["id"] == user_id), None)
    
    if not player: 
        logger.warning(f"SEND_QUESTION: Player {user_id} not found in session {session_key}.")
        return

    if player["current_q"] >= len(session["questions"]):
        session["finished_players"] += 1
        await app.send_message(user_id, f"✅ چالش شما تمام شد!\nامتیاز نهایی شما: {player['score']}")
        logger.info(f"Player {user_id} finished the quiz for session {session_key}")
        
        if session["finished_players"] == len(session["players"]):
            logger.info(f"All players finished for session {session_key}. Announcing results.")
            
            sorted_players = sorted(session["players"], key=lambda p: p['score'], reverse=True)
            
            final_text = "🏆 نتایج نهایی چالش 🏆\n\n"
            for i, p in enumerate(sorted_players):
                final_text += f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '▫️'} {p['name']}: {p['score']} امتیاز\n"

            try:
                # استفاده از inline_message_id یا chat_id/message_id ذخیره شده برای اعلام نتایج نهایی
                if session["inline_message_id"]:
                    await app.edit_inline_message_text(
                        inline_message_id=session["inline_message_id"],
                        text=final_text
                    )
                    logger.info(f"Final results announced for inline session {session_key}")
                elif session["chat_id"] and session["message_id"]:
                    await app.edit_message_text(
                        chat_id=session["chat_id"],
                        message_id=session["message_id"],
                        text=final_text
                    )
                    logger.info(f"Final results announced for private session {session_key}")
                else:
                    # اگر هیچکدام از شناسه‌ها وجود نداشت، احتمالا یک خطا رخ داده یا جلسه قدیمی است
                    logger.warning(f"Could not announce final results for session {session_key}: No valid message identifier.")
            except Exception as e:
                logger.error(f"CALLBACK_ERROR: Failed to announce final results for session {session_key}: {str(e)}")
            
            # پاک کردن جلسه بعد از پایان بازی
            if session_key in game_sessions:
                del game_sessions[session_key]
                logger.info(f"Game session {session_key} deleted after announcing results.")
        return

    q = session["questions"][player["current_q"]]
    
    options_list = q["options"][:]
    random.shuffle(options_list)
    
    buttons = [InlineKeyboardButton(text=opt, callback_data=f"answer|{opt}") for opt in options_list]
    markup = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])

    msg = await app.send_message(
        user_id,
        f"سوال {player['current_q'] + 1}:\n\n❓ **{q['question']}**",
        reply_markup=markup
    )

    player["start_time"] = time.time()
    player["question_msg_id"] = msg.id

    async def timeout_task():
        # نیاز به بررسی مجدد session_key در game_sessions قبل از دسترسی
        await asyncio.sleep(10)
        if session_key in game_sessions:
            # بعد از 10 ثانیه، مجدداً session و player را از game_sessions دریافت می‌کنیم
            # تا از آخرین وضعیت اطمینان حاصل کنیم، زیرا ممکن است در طول این مدت تغییر کرده باشند.
            current_session_state = game_sessions.get(session_key)
            if not current_session_state:
                logger.warning(f"Timeout task: Session {session_key} no longer exists.")
                return

            current_player_state = next((p for p in current_session_state["players"] if p["id"] == user_id), None)
            if not current_player_state:
                logger.warning(f"Timeout task: Player {user_id} no longer exists in session {session_key}.")
                return

            if current_player_state["current_q"] == current_q_index and current_player_state.get("question_msg_id") == msg.id:
                try:
                    await msg.edit_text("⏰ زمان تمام شد! امتیاز این سوال را از دست دادی.")
                except Exception as e:
                    logger.warning(f"Timeout task: Failed to edit message {msg.id} for user {user_id}: {str(e)}")
                    pass # اگر پیام ویرایش شده یا حذف شده باشد، این خطا طبیعی است
                
                # فقط در صورتی که بازیکن هنوز به این سوال پاسخ نداده باشد، امتیاز را صفر می‌کنیم و به سوال بعدی می‌رویم
                if current_player_state["question_msg_id"] is not None:
                    current_player_state["current_q"] += 1
                    current_player_state["question_msg_id"] = None # علامت‌گذاری که به این سوال پاسخ داده شده (یا زمانش تمام شده)
                    logger.info(f"Timeout for user {user_id} on question {current_q_index} in session {session_key}. Moving to next.")
                    await send_question(user_id, session_key)
                else:
                    logger.info(f"Timeout task: User {user_id} already answered question {current_q_index}.")
            else:
                logger.info(f"Timeout task: User {user_id} already moved to next question for session {session_key}.")

    current_q_index = player["current_q"]
    asyncio.create_task(timeout_task())

async def handle_answer(client, callback_query, session_key):
    if session_key not in game_sessions:
        logger.warning(f"HANDLE_ANSWER: Session {session_key} not found for user {callback_query.from_user.id}. Deleting message.")
        try:
            await callback_query.message.edit_text("این بازی منقضی شده یا قبلاً بسته شده است. لطفا یک بازی جدید شروع کنید.", reply_markup=None)
        except Exception as e:
            logger.error(f"HANDLE_ANSWER: Error editing expired message for {callback_query.from_user.id}: {e}")
        return await callback_query.answer("این بازی منقضی شده یا قبلاً بسته شده است!", show_alert=True)

    session = game_sessions[session_key]
    user_id = callback_query.from_user.id
    player = next((p for p in session["players"] if p["id"] == user_id), None)
    
    if not player:
        logger.warning(f"HANDLE_ANSWER: Player {user_id} not found in session {session_key}.")
        return await callback_query.answer("شما در این بازی شرکت نکرده‌اید!", show_alert=True)

    # بررسی اینکه آیا این همان پیام سوالی است که انتظار پاسخ آن را داریم
    if callback_query.message.id != player.get("question_msg_id"):
        logger.warning(f"HANDLE_ANSWER: User {user_id} answered an old/invalid question (msg_id: {callback_query.message.id}, expected: {player.get('question_msg_id')}).")
        await callback_query.answer("این سوال برای شما نیست یا قبلاً پاسخ داده‌اید!", show_alert=True)
        # تلاش برای حذف یا ویرایش پیام قدیمی
        try:
            await callback_query.message.edit_text("این سوال دیگر معتبر نیست.", reply_markup=None)
        except Exception as e:
            logger.error(f"HANDLE_ANSWER: Error editing old question message: {e}")
        return

    selected = callback_query.data.split("|")[1]
    q = session["questions"][player["current_q"]]
    correct_answer = q["answer"]

    elapsed = time.time() - player["start_time"]
    
    # اطمینان حاصل می‌کنیم که این سوال فقط یک بار پاسخ داده شود
    player["question_msg_id"] = None # علامت‌گذاری که به این سوال پاسخ داده شده

    if selected == correct_answer:
        earned_score = calculate_score(elapsed)
        player["score"] += earned_score
        text = f"✅ پاسخ صحیح!\n\n**+{earned_score}** امتیاز ({elapsed:.1f} ثانیه)\nامتیاز کل: {player['score']}"
    else:
        text = f"❌ پاسخ اشتباه!\n\nجواب صحیح: **{correct_answer}**\nامتیاز کل: {player['score']}"

    player["current_q"] += 1
    await callback_query.message.edit_text(text)
    
    await asyncio.sleep(2) # تأخیر قبل از ارسال سوال بعدی
    await send_question(user_id, session_key)

print("Bot is running...")
app.run()
