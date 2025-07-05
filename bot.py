from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InlineQueryResultArticle, InputTextMessageContent
from tes.question import questions # فرض می‌کنیم فایل tes/question.py شما وجود دارد
import asyncio
import time
import uuid
import logging
import random
# import re # دیگر نیازی به این نیست

# تنظیم لاگ دقیق‌تر برای عیب‌یابی
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"), # برای ذخیره لاگ در فایل
        logging.StreamHandler()        # برای نمایش لاگ در کنسول
    ]
)
logger = logging.getLogger(__name__)

# راه‌اندازی ربات
API_ID = '3335796'
API_HASH = '138b992a0e672e8346d8439c3f42ea78'
BOT_TOKEN = '7136875110:AAGr1EREy_qPMgxVbuE4B0cHGVcwWudOrus' # توکن ربات خود را اینجا قرار دهید

app = Client("watermark_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# داکیومنت نسخه Pyrogram هنگام شروع
import pyrogram
logger.info(f"Pyrogram version: {pyrogram.__version__}")

# game_sessions حالا برای پیام‌های اینلاین از inline_message_id واقعی به عنوان کلید استفاده می‌کند.
# برای پیام‌های خصوصی، از chat_id استفاده می‌شود.
game_sessions = {}

# نگاشت (map) بین query result ID (که Pyrogram تولید می‌کند) و UUID موقت ما
# این برای زمانی است که کاربر برای اولین بار روی یک پیام اینلاین کلیک می‌کند.
inline_query_result_id_to_temp_uuid = {}


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

# شروع اولیه در چت خصوصی
@app.on_message(filters.command("start") & filters.private)
async def start_command_private(client, message):
    chat_id = message.chat.id
    key = str(chat_id) # در چت خصوصی، chat_id را به عنوان key استفاده می‌کنیم

    # اگر قبلا جلسه‌ای با این chat_id وجود دارد، آن را حذف می‌کنیم تا جلسه جدیدی شروع شود.
    if key in game_sessions:
        del game_sessions[key]
        logger.info(f"PRIVATE_START: Existing session for key '{key}' deleted for new start.")


    session_data = {
        "players": [],
        "started": False,
        "finished_players": 0,
        "starter_id": message.from_user.id,
        "questions": random.sample(questions, len(questions)),
        "is_inline_message": False, # مشخص می‌کند که این یک پیام اینلاین نیست
        "main_message_id": None,    # message_id پیام اصلی در چت خصوصی
        "main_chat_id": chat_id     # chat_id پیام اصلی در چت خصوصی
    }
    game_sessions[key] = session_data

    logger.info(f"PRIVATE_START: Session created for key '{key}'. Data: {session_data}")

    text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید."

    sent_message = await message.reply(
        f"{text}\n\n{get_players_text(session_data)}",
        reply_markup=get_initial_markup(session_data)
    )
    # ذخیره message_id برای ویرایش‌های بعدی در چت خصوصی
    session_data["main_message_id"] = sent_message.id
    logger.info(f"PRIVATE_START: Message ID {sent_message.id} stored for session '{key}'")

# هندلر برای inline query
@app.on_inline_query()
async def handle_inline_query(client, inline_query):
    query = inline_query.query
    if query != "invite":
        return

    # تولید یک UUID موقت برای نگهداری اطلاعات جلسه
    temp_uuid_game_session = str(uuid.uuid4())
    temp_uuid_query_result = str(uuid.uuid4()) # ID برای InlineQueryResultArticle

    game_sessions[temp_uuid_game_session] = {
        "players": [],
        "started": False,
        "finished_players": 0,
        "starter_id": inline_query.from_user.id,
        "questions": random.sample(questions, len(questions)),
        "is_inline_message": True, # مشخص می‌کند که این یک پیام اینلاین است
        "main_message_id": None,    # این بعداً ست می‌شود (inline_message_id)
        "main_chat_id": None,       # این برای inline message استفاده نمی‌شود
        "temp_uuid_game_session": temp_uuid_game_session # ذخیره UUID موقت در session_data
    }
    # نگاشت Query Result ID به UUID موقت جلسه
    inline_query_result_id_to_temp_uuid[temp_uuid_query_result] = temp_uuid_game_session

    logger.info(f"INLINE_QUERY: New temporary game session created with key '{temp_uuid_game_session}' (mapped from Query Result ID: {temp_uuid_query_result})")

    markup = get_initial_markup(game_sessions[temp_uuid_game_session])

    initial_message_text = (
        "🎉 به چالش اطلاعات خوش آمدید!\n"
        "برای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n"
        f"{get_players_text(game_sessions[temp_uuid_game_session])}"
    )

    results = [
        InlineQueryResultArticle(
            id=temp_uuid_query_result, # استفاده از UUID برای ID نتیجه کوئری
            title="دعوت به چالش!",
            input_message_content=InputTextMessageContent(initial_message_text),
            reply_markup=markup,
            description="دوستانت رو به چالش دعوت کن!"
        )
    ]
    await inline_query.answer(results, cache_time=1)
    logger.info(f"INLINE_QUERY: Answered for query '{query}' with Query Result ID '{temp_uuid_query_result}' which maps to temp_game_session '{temp_uuid_game_session}'.")


# هندل دکمه‌ها
@app.on_callback_query()
async def handle_buttons(client, callback_query):
    global game_sessions
    global inline_query_result_id_to_temp_uuid # برای دسترسی به نگاشت UUID ها

    user = callback_query.from_user
    data = callback_query.data

    current_key = None
    session = None
    is_inline_message_callback = bool(callback_query.inline_message_id)

    if is_inline_message_callback:
        current_key = callback_query.inline_message_id
        logger.info(f"CALLBACK: Inline message callback received. Message ID: {current_key}")

        # 1. ابتدا سعی می‌کنیم جلسه را با inline_message_id پیدا کنیم (برای کلیک‌های بعدی)
        session = game_sessions.get(current_key)

        if session:
            logger.info(f"CALLBACK: Found existing inline session with key '{current_key}'.")
        else:
            # 2. اگر پیدا نشد، به دنبال UUID موقت از نگاشت inline_query_result_id_to_temp_uuid می‌گردیم
            # callback_query.id در اینجا همان ID مربوط به InlineQueryResultArticle است که در on_inline_query تنظیم کردیم.
            temp_uuid_game_session = inline_query_result_id_to_temp_uuid.pop(callback_query.id, None)

            if temp_uuid_game_session:
                logger.info(f"CALLBACK: Found temporary game session UUID '{temp_uuid_game_session}' from callback_query.id: '{callback_query.id}'.")

                # 3. جلسه موقت را با استفاده از temp_uuid_game_session پیدا و منتقل می‌کنیم
                temp_session = game_sessions.pop(temp_uuid_game_session, None)
                if temp_session:
                    temp_session["main_message_id"] = current_key # inline_message_id واقعی را ذخیره می‌کنیم
                    game_sessions[current_key] = temp_session
                    session = game_sessions[current_key]
                    logger.info(f"CALLBACK: Transferred session from temporary key '{temp_uuid_game_session}' to '{current_key}'.")
                else:
                    logger.warning(f"CALLBACK: Temporary session '{temp_uuid_game_session}' not found for transfer. Might be an old or expired session.")
            else:
                logger.warning(f"CALLBACK: No temporary game session UUID found in map for callback_query.id '{callback_query.id}'.")

        # اگر session همچنان None بود، یعنی نه با inline_message_id پیدا شد و نه از UUID موقت منتقل شد
        if not session:
            logger.warning(f"CALLBACK: No existing session found for inline message ID '{current_key}'. This might be an old message. Answering with expiry message.")
            await callback_query.answer("این بازی منقضی شده یا قبلاً بسته شده است. لطفا یک بازی جدید شروع کنید.", show_alert=True)
            try:
                # برای پیام های اینلاین، message خود object نیست، فقط message_id هست.
                # بنابراین نیازی به callback_query.message.text نیست.
                # اینجا فقط پیام رو ویرایش می‌کنیم.
                await client.edit_inline_message_text(
                    inline_message_id=current_key,
                    text="این بازی منقضی شده است. لطفا یک بازی جدید شروع کنید.",
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"CALLBACK_ERROR: Could not edit expired inline message for '{current_key}'. Error: {str(e)}", exc_info=True)
            return # از تابع خارج می‌شویم

    else:
        # برای پیام‌های خصوصی، chat_id کلید است.
        current_key = str(callback_query.message.chat.id)
        logger.info(f"CALLBACK: Private message callback received. Chat ID: {current_key}, Message ID: {callback_query.message.id}")

        session = game_sessions.get(current_key)
        if not session:
            logger.warning(f"CALLBACK: No existing session found for private chat ID '{current_key}'. This might be an old message. Answering with expiry message.")
            await callback_query.answer("این بازی منقضی شده یا قبلاً بسته شده است. لطفا یک بازی جدید شروع کنید.", show_alert=True)
            try:
                await callback_query.message.edit_text(
                    text="این بازی منقضی شده است. لطفا یک بازی جدید شروع کنید.",
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"CALLBACK_ERROR: Could not edit expired private message for '{current_key}'. Error: {str(e)}", exc_info=True)
            return # از تابع خارج می‌شویم

    # اگر برای یک پیام خصوصی، main_message_id هنوز تنظیم نشده، آن را تنظیم کن
    if not is_inline_message_callback and session["main_message_id"] is None:
        session["main_message_id"] = callback_query.message.id
        logger.info(f"CALLBACK: Private message ID {session['main_message_id']} stored for session '{current_key}'.")

    # --- نقطه دیباگ: وضعیت session بعد از شناسایی کلید ---
    logger.info(f"DEBUG: Session for key '{current_key}' after identification. Players count: {len(session['players'])}, Started: {session['started']}, Is Inline: {session['is_inline_message']}, Main MSG ID: {session['main_message_id']}")
    # ----------------------------------------------------


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
            logger.info(f"CALLBACK: User {user.id} ({player_name}) added to session {current_key}. Players: {len(session['players'])}")
        else:
            await callback_query.answer("شما از قبل در لیست هستید!", show_alert=False)
            logger.info(f"CALLBACK: User {user.id} already in session {current_key}.")

        text_to_update = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید.\n\n" + get_players_text(session)
        # دیگر نیازی به افزودن UUID به متن نیست زیرا از روش دیگری برای شناسایی session استفاده می‌کنیم.

        markup = get_initial_markup(session)
        logger.info(f"CALLBACK: Attempting to update message for session '{current_key}' with text: {text_to_update[:100]}... and {len(session['players'])} players")

        try:
            if session["is_inline_message"]:
                await client.edit_inline_message_text(
                    inline_message_id=session["main_message_id"],
                    text=text_to_update,
                    reply_markup=markup
                )
                logger.info(f"CALLBACK: Inline message updated successfully for key '{current_key}' using {session['main_message_id']}")
            else: # Private message
                await client.edit_message_text(
                    chat_id=session["main_chat_id"],
                    message_id=session["main_message_id"],
                    text=text_to_update,
                    reply_markup=markup
                )
                logger.info(f"CALLBACK: Private message updated successfully for key '{current_key}' (chat:{session['main_chat_id']}, msg:{session['main_message_id']})")
            await asyncio.sleep(0.1)  # تأخیر کوچک برای اطمینان از آپدیت
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Failed to update message for key '{current_key}'. Error: {str(e)}", exc_info=True)
            await callback_query.answer(
                "خطا در بروزرسانی! 😔\n(اگر در گروه هستید، مطمئن شوید ربات ادمین است و مجوز ویرایش پیام را دارد.)",
                show_alert=True
            )

    elif data == "start_game":
        if session["started"]:
            return await callback_query.answer("بازی قبلاً شروع شده!", show_alert=True)
        if not session["players"]:
            return await callback_query.answer("هنوز هیچکس پایه نیست!", show_alert=True)
        # starter_id را از game_sessions.get استفاده کنید تا اگر starter_id به دلایلی نبود، خطا ندهد.
        if user.id != session.get("starter_id"):
            return await callback_query.answer("فقط شروع‌کننده بازی می‌تواند آن را استارت بزند!", show_alert=True)

        session["started"] = True
        logger.info(f"Game started for session {current_key} by user {user.id}")

        text_to_update = "🚀 بازی شروع شد! سوالات به صورت خصوصی برایتان ارسال می‌شود..."

        try:
            if session["is_inline_message"]:
                await client.edit_inline_message_text(
                    inline_message_id=session["main_message_id"],
                    text=text_to_update,
                    reply_markup=None
                )
                logger.info(f"CALLBACK: Inline message updated for game start, key '{current_key}'")
            else:
                await client.edit_message_text(
                    chat_id=session["main_chat_id"],
                    message_id=session["main_message_id"],
                    text=text_to_update,
                    reply_markup=None
                )
                logger.info(f"CALLBACK: Private message updated for game start, key '{current_key}'")
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Failed to update message on game start for session {current_key}: {str(e)}", exc_info=True)
            await callback_query.answer(
                "خطا در بروزرسانی! 😔\n(اگر در گروه هستید، مطمئن شوید ربات ادمین است و مجوز ویرایش پیام را دارد.)",
                show_alert=True
            )

        for player in session["players"]:
            asyncio.create_task(send_question(player["id"], current_key))

    elif data == "cancel_game":
        if user.id != session.get("starter_id"):
            return await callback_query.answer("فقط شروع‌کننده بازی می‌تواند آن را لغو کند!", show_alert=True)

        text_to_update = "❌ بازی توسط شروع‌کننده لغو شد."

        try:
            if session["is_inline_message"]:
                await client.edit_inline_message_text(
                    inline_message_id=session["main_message_id"],
                    text=text_to_update,
                    reply_markup=None
                )
                logger.info(f"CALLBACK: Inline message updated for game cancel, key '{current_key}'")
            else:
                await client.edit_message_text(
                    chat_id=session["main_chat_id"],
                    message_id=session["main_message_id"],
                    text=text_to_update,
                    reply_markup=None
                )
                logger.info(f"CALLBACK: Private message updated for game cancel, key '{current_key}'")
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Failed to update message on game cancel for session {current_key}: {str(e)}", exc_info=True)
            await callback_query.answer(
                "خطا در بروزرسانی! 😔\n(اگر در گروه هستید، مطمئن شوید ربات ادمین است و مجوز ویرایش پیام را دارد.)",
                show_alert=True
            )

        # بعد از به‌روزرسانی پیام، جلسه را حذف می‌کنیم.
        if current_key in game_sessions:
            del game_sessions[current_key]
            logger.info(f"Game session {current_key} cancelled and deleted by user {user.id}")


    elif data.startswith("answer|"):
        await handle_answer(client, callback_query, current_key)

def calculate_score(elapsed):
    if elapsed <= 2: return 20
    elif elapsed <= 4: return 15
    elif elapsed <= 6: return 10
    elif elapsed <= 8: return 5
    else: return 2

async def send_question(user_id, session_key):
    # همیشه قبل از دسترسی، از وجود session_key در game_sessions اطمینان حاصل کنید.
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
                # استفاده از is_inline_message برای تعیین نوع ویرایش
                if session["is_inline_message"]:
                    await app.edit_inline_message_text(
                        inline_message_id=session["main_message_id"],
                        text=final_text,
                        reply_markup=None # نتایج نهایی دکمه‌ای ندارد
                    )
                    logger.info(f"Final results announced for inline session {session_key}")
                else: # Private message
                    await app.edit_message_text(
                        chat_id=session["main_chat_id"],
                        message_id=session["main_message_id"],
                        text=final_text,
                        reply_markup=None # نتایج نهایی دکمه‌ای ندارد
                    )
                    logger.info(f"Final results announced for private session {session_key}")
            except Exception as e:
                logger.error(f"CALLBACK_ERROR: Failed to announce final results for session {session_key}: {str(e)}", exc_info=True)

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
        await asyncio.sleep(10)
        # دوباره session و player را چک می‌کنیم چون ممکن است در 10 ثانیه تغییر کرده باشند
        if session_key in game_sessions:
            current_session_state = game_sessions.get(session_key)
            if not current_session_state:
                logger.warning(f"Timeout task: Session {session_key} no longer exists during timeout.")
                return

            current_player_state = next((p for p in current_session_state["players"] if p["id"] == user_id), None)
            if not current_player_state:
                logger.warning(f"Timeout task: Player {user_id} not found in session {session_key} during timeout.")
                return

            # فقط در صورتی که پیام سوال هنوز معتبر باشد و کاربر هنوز پاسخ نداده باشد
            if current_player_state.get("question_msg_id") == msg.id:
                try:
                    await msg.edit_text("⏰ زمان تمام شد! امتیاز این سوال را از دست دادی.")
                except Exception as e:
                    logger.warning(f"Timeout task: Failed to edit message {msg.id} for user {user_id}: {str(e)}. Likely already edited or deleted.")

                # فقط در صورتی که بازیکن هنوز به این سوال پاسخ نداده باشد، امتیاز را صفر می‌کنیم و به سوال بعدی می‌رویم
                current_player_state["current_q"] += 1
                current_player_state["question_msg_id"] = None # علامت‌گذاری که به این سوال پاسخ داده شده (یا زمانش تمام شده)
                logger.info(f"Timeout for user {user_id} on question {current_q_index} in session {session_key}. Moving to next.")
                await send_question(user_id, session_key)
            else:
                logger.info(f"Timeout task: User {user_id} already answered question {current_q_index} or moved on.")

    current_q_index = player["current_q"]
    asyncio.create_task(timeout_task())

async def handle_answer(client, callback_query, session_key):
    if session_key not in game_sessions:
        logger.warning(f"HANDLE_ANSWER: Session {session_key} not found for user {callback_query.from_user.id}. Message {callback_query.message.id} is outdated.")
        try:
            # برای پیام‌های خصوصی، message.id و edit_text استفاده می‌شود
            # برای پیام‌های اینلاین، این بخش اجرا نمی‌شود چون message.id ندارد
            if callback_query.message: # اگر message آبجکت وجود دارد (یعنی پیام خصوصی است)
                await callback_query.message.edit_text("این بازی منقضی شده یا قبلاً بسته شده است. لطفا یک بازی جدید شروع کنید.", reply_markup=None)
        except Exception as e:
            logger.error(f"HANDLE_ANSWER: Error editing expired message {callback_query.message.id} for {callback_query.from_user.id}: {e}", exc_info=True)
        return await callback_query.answer("این بازی منقضی شده یا قبلاً بسته شده است!", show_alert=True)

    session = game_sessions[session_key]
    user_id = callback_query.from_user.id
    player = next((p for p in session["players"] if p["id"] == user_id), None)

    if not player:
        logger.warning(f"HANDLE_ANSWER: Player {user_id} not found in session {session_key}.")
        return await callback_query.answer("شما در این بازی شرکت نکرده‌اید!", show_alert=True)

    # بررسی اینکه آیا این همان پیام سوالی است که انتظار پاسخ آن را داریم
    # و همچنین مطمئن می‌شویم که user["question_msg_id"] هنوز تنظیم شده است (یعنی قبلا پاسخ داده نشده).
    if player.get("question_msg_id") is None or callback_query.message.id != player["question_msg_id"]:
        logger.warning(f"HANDLE_ANSWER: User {user_id} answered an old/invalid question (msg_id: {callback_query.message.id}, expected: {player.get('question_msg_id')}).")
        await callback_query.answer("این سوال برای شما نیست یا قبلاً پاسخ داده‌اید!", show_alert=True)
        # تلاش برای حذف یا ویرایش پیام قدیمی
        try:
            await callback_query.message.edit_text("این سوال دیگر معتبر نیست.", reply_markup=None)
        except Exception as e:
            logger.error(f"HANDLE_ANSWER: Error editing old question message {callback_query.message.id}: {e}", exc_info=True)
        return

    selected = callback_query.data.split("|")[1]
    q = session["questions"][player["current_q"]]
    correct_answer = q["answer"]

    elapsed = time.time() - player["start_time"]

    # علامت‌گذاری که به این سوال پاسخ داده شده، تا timeout آن را دوباره پردازش نکند
    player["question_msg_id"] = None

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
