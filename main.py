import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
from pymongo import MongoClient
import threading
import random
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, PORT, MONGO_URI

# ====================
# DATABASE
# ====================
client_db = MongoClient(MONGO_URI)
db = client_db["gemini_bot_db"]

memory_col = db["memory"]
user_profiles_col = db["user_profiles"]
welcome_col = db["welcome_config"]
fsub_col = db["fsub_config"]
user_profiles_col = db["user_profiles"]
# ====================
# BOT CLIENT
# ====================
app = Client(
    "gemini_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100
)

clones = {}  # track clones

# ====================
# MOTIVATION SYSTEM
# ====================
CHANNEL_ID = -1002966725498
quotes = [
    "Dream, dream, dream. Dreams transform into thoughts and thoughts result in action. – A.P.J. Abdul Kalam",
    "Be the change that you wish to see in the world. – Mahatma Gandhi",
    "Arise, awake, and stop not until the goal is reached. – Swami Vivekananda",
    "Excellence is not a skill. It is an attitude. – Ralph Marston",
    "Small aim is a crime; have great aim. – A.P.J. Abdul Kalam"
]

def send_daily_quote_job():
    quote = random.choice(quotes)
    from asyncio import get_event_loop, run_coroutine_threadsafe
    loop = get_event_loop()
    run_coroutine_threadsafe(
        app.send_message(CHANNEL_ID, f"🌅 Good Morning!\n\n{quote}"), loop
    )

# ====================
# FLASK HEALTH CHECK
# ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Gemini AI Bot running with MongoDB + Clone + Motivation + Manual Post!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

# ====================
# ====================
# /ban → Ban user
# ====================
@app.on_message(filters.command("ban") & filters.user(OWNER_ID))
async def ban_user(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: /ban <user_id>")

    try:
        user_id = int(message.command[1])
        user_profiles_col.update_one(
            {"user_id": user_id},
            {"$set": {"banned": True}},
            upsert=True
        )
        await message.reply(f"⛔ User {user_id} has been banned!")
    except ValueError:
        await message.reply("⚠️ Invalid user ID.")

# ====================
# /unban → Unban user
# ====================
@app.on_message(filters.command("unban") & filters.user(OWNER_ID))
async def unban_user(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: /unban <user_id>")

    try:
        user_id = int(message.command[1])
        user_profiles_col.update_one(
            {"user_id": user_id},
            {"$set": {"banned": False}},
        )
        await message.reply(f"✅ User {user_id} has been unbanned!")
    except ValueError:
        await message.reply("⚠️ Invalid user ID.")


@app.on_message(filters.private & ~filters.user(OWNER_ID))
async def handle_user_messages(client: Client, message: Message):
    user_id = message.from_user.id
    user = user_profiles_col.find_one({"user_id": user_id})

    # Check ban
    if user and user.get("banned", False):
        try:
            await message.reply("🚫 You are banned from using this bot.")
        except:
            pass
        return  # stop processing further

    # Existing forwarding code
    full_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
    username = f"@{message.from_user.username}" if message.from_user.username else f"tg://user?id={user_id}"

    memory_col.insert_one({
        "user_id": user_id,
        "message": message.text or "<media>",
        "media_type": message.media.value if message.media else "text",
        "timestamp": datetime.utcnow()
    })

    fwd = await message.forward(OWNER_ID)
    info_text = (
        f"📩 New Message\n"
        f"👤 Name: {full_name}\n"
        f"🆔 ID: {user_id}\n"
        f"🔗 Profile: {username}\n"
        f"💬 Message: {message.text if message.text else '<media>'}"
    )
    await fwd.reply_text(info_text)

    conf_msg = await message.reply_text("✅ Your message has been successfully sent!")
    await asyncio.sleep(2)
    try:
        await conf_msg.delete()
    except:
        pass
# ===============================
# /setwelcome → Set Welcome
# ===============================
@app.on_message(filters.command("setwelcome") & filters.user(OWNER_ID))
async def set_welcome(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply(
            "⚠️ Reply to a photo/text to set welcome.\n"
            "Optional: `btn=Text1|URL1,Text2|URL2` or JSON format `btn=[{{'text':'T','url':'U'}}]`"
        )

    # Photo & caption
    file_id = message.reply_to_message.photo.file_id if message.reply_to_message.photo else None
    caption = message.reply_to_message.caption or message.reply_to_message.text or "👋 Welcome!"

    # Buttons
    buttons = []
    if "btn=" in message.text:
        btn_text = message.text.split("btn=")[1].strip()

        # Try JSON first
        try:
            btn_list = json.loads(btn_text)
            for b in btn_list:
                buttons.append([InlineKeyboardButton(b["text"], url=b["url"])])
        except:
            # Fallback: comma separated format
            btn_pairs = btn_text.split(",")
            for pair in btn_pairs:
                try:
                    text, url = pair.split("|")
                    buttons.append([InlineKeyboardButton(text.strip(), url=url.strip())])
                except:
                    continue

    # Save to DB
    welcome_col.update_one(
        {"_id": "welcome"},
        {"$set": {"photo": file_id, "caption": caption, "buttons": buttons}},
        upsert=True
    )

    await message.reply("✅ Welcome message set successfully!")

# ===============================
# /delwelcome → Delete Welcome
# ===============================
@app.on_message(filters.command("delwelcome") & filters.user(OWNER_ID))
async def del_welcome(client: Client, message: Message):
    result = welcome_col.delete_one({"_id": "welcome"})
    if result.deleted_count:
        await message.reply("🗑️ Welcome message deleted. Default message will show now.")
    else:
        await message.reply("⚠️ No welcome message was set previously.")

# ===============================
# /start → Show Welcome
# ===============================
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    user_profiles_col.update_one(
        {"user_id": user.id},
        {"$set": {
            "user_id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
            "joined_at": datetime.utcnow()
        }},
        upsert=True
    )

    # Fetch welcome config
    config = welcome_col.find_one({"_id": "welcome"})
    if config:
        caption = config.get("caption", f"👋 Welcome {user.first_name}!")
        photo = config.get("photo", None)
        buttons = config.get("buttons", [])
        markup = InlineKeyboardMarkup(buttons) if buttons else None

        if photo:
            await client.send_photo(message.chat.id, photo=photo, caption=caption, reply_markup=markup)
        else:
            await client.send_message(message.chat.id, text=caption, reply_markup=markup)
    else:
        # Default welcome with photo, name included in caption
        default_photo = "https://i.ibb.co/MkHGvrhL/photo-2025-08-15-12-04-59-7555109221855920164.jpg"
        default_buttons = [
            [InlineKeyboardButton("Smile Plz 🫰🏻", url="https://t.me/Dream_Job_soon")]
        ]
        default_caption = f" Welcome {user.first_name} ❤️\nAsk your questions or doubts, I will reply soon!"
        await client.send_photo(
            message.chat.id,
            photo=default_photo,
            caption=default_caption,
            reply_markup=InlineKeyboardMarkup(default_buttons)
        )

# ====================
# FORWARD USER → ADMIN + CONFIRMATION
# ====================
@app.on_message(filters.private & ~filters.user(OWNER_ID))
async def forward_user_msg(client: Client, message: Message):
    user = message.from_user
    user_id = user.id
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else f"tg://user?id={user_id}"

    memory_col.insert_one({
        "user_id": user_id,
        "message": message.text or "<media>",
        "media_type": message.media.value if message.media else "text",
        "timestamp": datetime.utcnow()
    })

    fwd = await message.forward(OWNER_ID)
    info_text = (
        f"📩 New Message\n"
        f"👤 Name: {full_name}\n"
        f"🆔 ID: {user_id}\n"
        f"🔗 Profile: {username}\n"
        f"💬 Message: {message.text if message.text else '<media>'}"
    )
    await fwd.reply_text(info_text)

    conf_msg = await message.reply_text("✅ Your message has been successfully sent!")
    await asyncio.sleep(2)
    try:
        await conf_msg.delete()
    except:
        pass

# ====================
# ADMIN REPLY → USER
# ====================
@app.on_message(filters.private & filters.user(OWNER_ID) & filters.reply)
async def reply_to_user(client: Client, message: Message):
    try:
        reply_to = message.reply_to_message
        text = reply_to.text or ""
        import re
        match = re.search(r'ID: (\d+)', text)
        if not match:
            return await message.reply_text("⚠️ User ID not found!")

        user_id = int(match.group(1))

        memory_col.insert_one({
            "user_id": user_id,
            "admin_reply": message.text or "<text only>",
            "timestamp": datetime.utcnow()
        })

        if message.text:
            await client.send_message(user_id, message.text)

        await message.reply_text("✅ Reply delivered.")
    except Exception as e:
        await message.reply_text(f"Error: {e}")

# ====================
# BROADCAST
# ====================
@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /broadcast Your message here")

    text = message.text.split(" ", 1)[1]
    users = user_profiles_col.find()
    sent, failed = 0, 0

    for user in users:
        try:
            await client.send_message(user["user_id"], f"{text}")
            sent += 1
        except:
            failed += 1
        await asyncio.sleep(0.05)

    await message.reply_text(f"📢 Broadcast sent to {sent} users, failed: {failed}")

# ====================
# STATS (Detailed)
# ====================
@app.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def stats_cmd(client: Client, message: Message):
    total_users = user_profiles_col.count_documents({})
    text = f"📊 Total users: {total_users}\n\n"

    users = user_profiles_col.find().sort("joined_at", -1)
    all_lines = []

    for u in users:
        user_id = u.get("user_id")
        fname = u.get("first_name", "")
        lname = u.get("last_name", "")
        uname = f"@{u['username']}" if u.get("username") else f"[Link](tg://user?id={user_id})"
        joined = u.get("joined_at", "")
        line = f"👤 {fname} {lname}\n🆔 {user_id}\n🔗 {uname}\n📅 {joined}\n"
        all_lines.append(line)

    chunk = ""
    for line in all_lines:
        if len(chunk) + len(line) > 4000:
            await message.reply_text(chunk, disable_web_page_preview=True)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await message.reply_text(chunk, disable_web_page_preview=True)

# ====================
# CLONE SYSTEM
# ====================
@app.on_message(filters.command("clone") & filters.user(OWNER_ID))
async def clone_bot(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /clone BOT_TOKEN")

    new_token = message.command[1]
    if new_token in clones:
        return await message.reply_text("⚠️ Clone bot already running!")

    try:
        clone_client = Client(
            f"clone_{new_token[:6]}",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=new_token,
            workers=100
        )
        await clone_client.start()
        clones[new_token] = clone_client
        await message.reply_text(f"✅ Clone Bot started with token ending {new_token[-6:]}")
    except Exception as e:
        await message.reply_text(f"Clone failed: {e}")

# ====================
# MANUAL POST (text or reply media)
# ====================
# ====================
# MANUAL POSTING (Owner only)
# ====================
@app.on_message(filters.command("post") & filters.user(OWNER_ID))
async def manual_post(client, message: Message):
    if len(message.command) > 1:
        # Text post
        text = " ".join(message.command[1:])
        await app.send_message(CHANNEL_ID, text)
        conf_msg = await message.reply("✅ Posted to channel!")
        await asyncio.sleep(2)
        await conf_msg.delete()
    elif message.reply_to_message:
        # Media post
        await message.reply_to_message.copy(CHANNEL_ID)
        conf_msg = await message.reply("✅ Media posted to channel!")
        await asyncio.sleep(2)
        await conf_msg.delete()
    else:
        # Invalid usage
        conf_msg = await message.reply("⚠️ Usage: /post <your message> or reply to media with /post")
        await asyncio.sleep(2)
        await conf_msg.delete()

# ====================
# FORWARD USER → ADMIN + Confirmation (Non-owner users only)
# ====================
@app.on_message(filters.private & ~filters.user(OWNER_ID))
async def forward_user_msg(client: Client, message: Message):
    user = message.from_user
    user_id = user.id
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else f"tg://user?id={user_id}"

    # Save in DB
    memory_col.insert_one({
        "user_id": user_id,
        "message": message.text or "<media>",
        "media_type": message.media.value if message.media else "text",
        "timestamp": datetime.utcnow()
    })

    # Forward to admin
    fwd = await message.forward(OWNER_ID)
    info_text = (
        f"📩 New Message\n"
        f"👤 Name: {full_name}\n"
        f"🆔 ID: {user_id}\n"
        f"🔗 Profile: {username}\n"
        f"💬 Message: {message.text if message.text else '<media>'}"
    )
    await fwd.reply_text(info_text)

    # Confirmation to user
    conf_msg = await message.reply_text("✅ Your message has been successfully sent!")
    await asyncio.sleep(2)
    try:
        await conf_msg.delete()
    except:
        pass



# ====================
# ALL YOUR HANDLERS, COMMANDS, FUNCTIONS, FLASK APP ETC.
# ====================

# Example:
# @app.on_message(filters.command("start") & filters.private)
# async def start_cmd(...):
#     ...

# ====================
# RUN BOT + SCHEDULER + FLASK + DEPLOY MESSAGE
# ====================
if __name__ == "__main__":
    import threading
    from apscheduler.schedulers.background import BackgroundScheduler

    # Flask background
    threading.Thread(target=run_flask, daemon=True).start()

    # Scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_daily_quote_job, "cron", hour=7, minute=0, timezone="Asia/Kolkata")
    scheduler.start()

    # Deploy success message after bot starts
    def send_deploy_message():
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(app.send_message("@You_Are_A_Officer", "✅ Gemini AI Bot successfully deployed and running!"))

    # Schedule deploy message 5 sec after start
    threading.Timer(5, send_deploy_message).start()

    print("✅ Gemini AI Bot Started with MongoDB + Clone + Motivation System...")
    # Start bot (handlers will now work)
    app.run()
