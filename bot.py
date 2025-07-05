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
@app.on_message(filters.command("start") & filters.private) # <<< تغییر: این دستور فقط در چت خصوصی کار می‌کند
async def start_command_private(client, message):
    chat_id = message.chat.id
    key = str(chat_id)
    
    game_sessions[key] = {
        "players": [],
        "started": False,
        "finished_players": 0,
        "starter_id": message.from_user.id,
        "questions": random.sample(questions, len(questions))
    }
    
    logger.info(f"PRIVATE_START: Session created for key '{key}'")
    
    session = game_sessions[key]
    text = "🎉 به چالش اطلاعات خوش آمدید!\nبرای شرکت در بازی روی دکمه 'من پایه‌ام' کلیک کنید."
    await message.reply(
        f"{text}\n\n{get_players_text(session)}",
        reply_markup=get_initial_markup(session)
    )

# هندلر برای inline query
@app.on_inline_query()
async def handle_inline_query(client, inline_query):
    # این بخش بدون تغییر است
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🙋‍♂️ من پایه‌ام", callback_data="im_in"),
         InlineKeyboardButton("🚀 شروع بازی", callback_data="start_game")]
    ])
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="دعوت به چالش!",
            input_message_content=InputTextMessageContent("🧑‍🤝‍🧑 لیست پایه‌ها:\n(هنوز کسی پایه نیست)"),
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
    
    key = callback_query.inline_message_id
    is_inline = True
    if not key:
        is_inline = False
        key = str(callback_query.message.chat.id)

    logger.info(f"CALLBACK: Received '{data}' from user {user.id}. Key: '{key}', IsInline: {is_inline}")

    session = game_sessions.get(key)

    # <<< تغییر مهم: منطق مدیریت جلسه
    if not session:
        if is_inline:
            # اگر اینلاین بود و جلسه وجود نداشت، یکی بساز
            logger.warning(f"CALLBACK: No session for inline key '{key}'. Creating new one.")
            game_sessions[key] = {
                "players": [], "started": False, "finished_players": 0,
                "starter_id": user.id, "questions": random.sample(questions, len(questions))
            }
            session = game_sessions[key]
        else:
            # اگر در چت خصوصی بود و جلسه وجود نداشت، یعنی کاربر /start نزده
            logger.error(f"CALLBACK: No session for private chat key '{key}'. Ignoring.")
            return await callback_query.answer("❌ جلسه بازی پیدا نشد! لطفاً دوباره /start را بزنید.", show_alert=True)
    else:
        logger.info(f"CALLBACK: Session found for key '{key}'.")

    # --- مدیریت دکمه "من پایه‌ام" ---
    if data == "im_in":
        if session["started"]:
            return await callback_query.answer("🚫 بازی شروع شده و نمی‌توانید اضافه شوید!", show_alert=True)
            
        if user.id not in [p["id"] for p in session["players"]]:
            player_name = user.first_name or user.username or f"User_{user.id}"
            session["players"].append({
                "id": user.id, "name": player_name, "score": 0,
                "current_q": 0, "start_time": 0
            })
            await callback_query.answer("✅ شما به لیست پایه‌ها اضافه شدید!", show_alert=False)
            logger.info(f"CALLBACK: User {user.id} added to session {key}. Players: {len(session['players'])}")
        else:
            await callback_query.answer("شما از قبل در لیست هستید!", show_alert=False)
            logger.info(f"CALLBACK: User {user.id} already in session {key}.")
        
        # آپدیت پیام
        text = get_players_text(session)
        markup = get_initial_markup(session)
        try:
            if is_inline:
                await client.edit_message_text(inline_message_id=key, text=text, reply_markup=markup)
            else:
                await callback_query.message.edit_text(text, reply_markup=markup)
            logger.info(f"CALLBACK: Message updated successfully for key '{key}'.")
        except Exception as e:
            logger.error(f"CALLBACK_ERROR: Failed to update message for key '{key}'. Error: {e}")
            await callback_query.answer(
                "خطا در بروزرسانی! 😔\n(اگر در گروه هستید، مطمئن شوید ربات ادمین است)",
                show_alert=True
            )

    # ... بقیه کد (start_game, cancel_game, answer) بدون تغییر باقی می‌ماند ...
    # (برای خلاصه‌سازی، بقیه کد را اینجا تکرار نمی‌کنم، لطفاً از کد قبلی کپی کنید یا
    # اگر می‌خواهید، بگویید تا کل فایل را دوباره قرار دهم)


# >>>>>>>> توجه: این بخش را باید با ادامه کد خودتان از پاسخ قبلی جایگزین کنید <<<<<<<<
# بخش‌های مربوط به start_game, cancel_game, calculate_score, send_question, handle_answer
# و در نهایت app.run() را اینجا قرار دهید. آنها نیازی به تغییر ندارند.
# برای کامل بودن، من آنها را در زیر دوباره قرار می‌دهم.

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
            if is_inline:
                await client.edit_message_text(inline_message_id=key, text=text, reply_markup=None)
            else:
                await callback_query.message.edit_text(text, reply_markup=None)
        except Exception as e:
            logger.error(f"Error editing message on game start for session {key}: {e}")
            
        for player in session["players"]:
            # ارسال سوال اول برای همه بازیکنان
            # asyncio.create_task برای اطمینان از اجرای همزمان است
            asyncio.create_task(send_question(player["id"], key))


    elif data == "cancel_game":
        if user.id != session.get("starter_id"):
            return await callback_query.answer("فقط شروع‌کننده بازی می‌تواند آن را لغو کند!", show_alert=True)
        
        del game_sessions[key]
        logger.info(f"Game session {key} cancelled by user {user.id}")
        text = "❌ بازی توسط شروع‌کننده لغو شد."
        try:
            if is_inline:
                await client.edit_message_text(inline_message_id=key, text=text, reply_markup=None)
            else:
                await callback_query.message.edit_text(text, reply_markup=None)
        except Exception as e:
             logger.error(f"Error editing message on game cancel for session {key}: {e}")

    elif data.startswith("answer|"):
        await handle_answer(client, callback_query, key)

def calculate_score(elapsed):
    if elapsed <= 2: return 20
    elif elapsed <= 4: return 15
    elif elapsed <= 6: return 10
    elif elapsed <= 8: return 5
    else: return 2

async def send_question(user_id, session_key):
    # این تابع برای جلوگیری از خطا باید اول چک کند که جلسه هنوز وجود دارد یا نه
    if session_key not in game_sessions:
        logger.warning(f"SEND_QUESTION: Session {session_key} not found. Can't send question to {user_id}.")
        return

    session = game_sessions[session_key]
    player = next((p for p in session["players"] if p["id"] == user_id), None)
    
    if not player: return

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
                # اگر کلید، آیدی پیام اینلاین باشد
                if not session_key.isdigit():
                    await app.edit_message_text(inline_message_id=session_key, text=final_text)
                else: # اگر کلید، آیدی چت باشد
                    await app.send_message(int(session_key), final_text)
            except Exception as e:
                logger.error(f"Failed to announce final results for session {session_key}: {e}")
            
            del game_sessions[session_key]
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

    current_q_index = player["current_q"]
    async def timeout_task():
        await asyncio.sleep(10)
        if session_key in game_sessions and player["current_q"] == current_q_index:
            try:
                await msg.edit_text("⏰ زمان تمام شد! امتیاز این سوال را از دست دادی.")
            except Exception:
                pass # اگر پیام قبلا ادیت شده بود (توسط پاسخ کاربر) مشکلی نیست
            player["current_q"] += 1
            await send_question(user_id, session_key)
            logger.info(f"Timeout for user {user_id} on question {current_q_index} in session {session_key}")

    asyncio.create_task(timeout_task())

async def handle_answer(client, callback_query, session_key):
    if session_key not in game_sessions:
        return await callback_query.message.delete()

    session = game_sessions[session_key]
    user_id = callback_query.from_user.id
    player = next((p for p in session["players"] if p["id"] == user_id), None)
    
    if not player or callback_query.message.id != player.get("question_msg_id"):
        return await callback_query.answer("این سوال برای شما نیست یا منقضی شده!", show_alert=True)

    selected = callback_query.data.split("|")[1]
    q = session["questions"][player["current_q"]]
    correct_answer = q["answer"]

    elapsed = time.time() - player["start_time"]
    
    player["question_msg_id"] = None
    
    if selected == correct_answer:
        earned_score = calculate_score(elapsed)
        player["score"] += earned_score
        text = f"✅ پاسخ صحیح!\n\n**+{earned_score}** امتیاز ({elapsed:.1f} ثانیه)\nامتیاز کل: {player['score']}"
    else:
        text = f"❌ پاسخ اشتباه!\n\nجواب صحیح: **{correct_answer}**\nامتیاز کل: {player['score']}"

    player["current_q"] += 1
    await callback_query.message.edit_text(text)
    
    await asyncio.sleep(2)
    await send_question(user_id, session_key)

print("Bot is running...")
app.run()
