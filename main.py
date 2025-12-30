import asyncio
import json
import random
from datetime import datetime
from flask import Flask
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import requests

# ====================
# CONFIG (Set your own)
# ====================
from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, PORT, MONGO_URI

# ====================
# DATABASE
# ====================
client_db = MongoClient(MONGO_URI)
db = client_db["gemini_bot_db"]

memory_col = db["memory"]
user_profiles_col = db["user_profiles"]
welcome_col = db["welcome_config"]
motivation_time_col = db["motivation_time"]
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

# ====================
# FLASK HEALTH CHECK
# ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Gemini AI Bot running with MongoDB + Motivation System!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

# ====================
# DAILY MOTIVATION FUNCTION
# ====================
def fetch_motivation_text():
    """Fetch motivational text from free API or fallback"""
    try:
        r = requests.get("https://zenquotes.io/api/today")
        if r.status_code == 200:
            data = r.json()
            return data[0]["q"] + " – " + data[0]["a"]
    except:
        pass
    # Fallback text
    fallback_quotes = [
        "सपने बड़े देखो और हिम्मत रखो। – Norman Vaughan",
        "Be the change that you wish to see in the world. – Mahatma Gandhi",
        "हर दिन छोटे कदम बढ़ाओ। – Anonymous",
        "Your limitation—it’s only your imagination.",
        "Push yourself, because no one else is going to do it for you."
    ]
    return random.choice(fallback_quotes)

def fetch_motivation_image():
    """Fetch a random motivational image from Unsplash free API or fallback"""
    try:
        r = requests.get("https://source.unsplash.com/800x600/?motivation,inspiration")
        if r.status_code == 200:
            return r.url
    except:
        pass
    # fallback static image
    return "https://i.ibb.co/MkHGvrhL/photo-2025-08-15-12-04-59-7555109221855920164.jpg"

def send_daily_motivation():
    users = user_profiles_col.find()
    text = fetch_motivation_text()
    image_url = fetch_motivation_image()

    loop = asyncio.get_event_loop()
    for user in users:
        user_id = user["user_id"]
        try:
            asyncio.run_coroutine_threadsafe(
                app.send_photo(user_id, photo=image_url, caption=f"🌅 Daily Motivation 🌟\n\n{text}"),
                loop
            )
        except:
            continue

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

# ====================
# /setwelcome → Set Welcome
# ====================
@app.on_message(filters.command("setwelcome") & filters.user(OWNER_ID))
async def set_welcome(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply(
            "⚠️ Reply to a photo/text to set welcome.\n"
            "Optional: `btn=Text1|URL1,Text2|URL2` or JSON format `btn=[{{'text':'T','url':'U'}}]`"
        )

    file_id = message.reply_to_message.photo.file_id if message.reply_to_message.photo else None
    caption = message.reply_to_message.caption or message.reply_to_message.text or "👋 Welcome!"
    buttons = []

    if "btn=" in message.text:
        btn_text = message.text.split("btn=")[1].strip()
        try:
            btn_list = json.loads(btn_text)
            for b in btn_list:
                buttons.append([InlineKeyboardButton(b["text"], url=b["url"])])
        except:
            btn_pairs = btn_text.split(",")
            for pair in btn_pairs:
                try:
                    text, url = pair.split("|")
                    buttons.append([InlineKeyboardButton(text.strip(), url=url.strip())])
                except:
                    continue

    welcome_col.update_one(
        {"_id": "welcome"},
        {"$set": {"photo": file_id, "caption": caption, "buttons": buttons}},
        upsert=True
    )
    await message.reply("✅ Welcome message set successfully!")
    
    
# ====================
# /delwelcome → Delete Welcome
# ====================
@app.on_message(filters.command("delwelcome") & filters.user(OWNER_ID))
async def del_welcome(client: Client, message: Message):
    result = welcome_col.delete_one({"_id": "welcome"})
    if result.deleted_count:
        await message.reply("🗑️ Welcome message deleted. Default message will show now.")
    else:
        await message.reply("⚠️ No welcome message was set previously.")

# ====================
# /start → Show Welcome + register user
# ====================
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
        default_photo = "https://i.ibb.co/MkHGvrhL/photo-2025-08-15-12-04-59-7555109221855920164.jpg"
        default_buttons = [[InlineKeyboardButton("Smile Plz 🫰🏻", url="https://t.me/Dream_Job_soon")]]
        default_caption = f" Welcome {user.first_name} ❤️\nAsk your questions or doubts, I will reply soon!"
        await client.send_photo(message.chat.id, photo=default_photo, caption=default_caption, reply_markup=InlineKeyboardMarkup(default_buttons))

# ====================
# FORWARD USER → ADMIN + CONFIRMATION
# ====================
@app.on_message(filters.private & ~filters.user(OWNER_ID))
async def forward_user_msg(client: Client, message: Message):
    user_id = message.from_user.id
    user = message.from_user
    username = f"@{user.username}" if user.username else f"tg://user?id={user_id}"

    # Ban check
    profile = user_profiles_col.find_one({"user_id": user_id})
    if profile and profile.get("banned", False):
        return await message.reply("🚫 You are banned from using this bot.")

    # Save in DB
    memory_col.insert_one({
        "user_id": user_id,
        "message": message.text or "<media>",
        "media_type": message.media.value if message.media else "text",
        "timestamp": datetime.utcnow()
    })

    fwd = await message.forward(OWNER_ID)
    info_text = (
        f"📩 New Message\n"
        f"👤 Name: {user.first_name} {user.last_name or ''}\n"
        f"🆔 ID: {user_id}\n"
        f"🔗 Profile: {username}\n"
        f"💬 Message: {message.text if message.text else '<media>'}"
    )
    await fwd.reply_text(info_text)
    conf_msg = await message.reply_text("✅ Your message has been successfully sent!")
    await asyncio.sleep(2)
    try: await conf_msg.delete()
    except: pass

# ====================
# ADMIN REPLY → USER
# ====================
@app.on_message(filters.private & filters.user(OWNER_ID) & filters.reply)
async def reply_to_user(client: Client, message: Message):
    try:
        reply_to = message.reply_to_message
        import re
        match = re.search(r'ID: (\d+)', reply_to.text)
        if not match: return await message.reply_text("⚠️ User ID not found!")
        user_id = int(match.group(1))

        memory_col.insert_one({
            "user_id": user_id,
            "admin_reply": message.text or "<text only>",
            "timestamp": datetime.utcnow()
        })
        if message.text: await client.send_message(user_id, message.text)
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
            await client.send_message(user["user_id"], text)
            sent += 1
        except:
            failed += 1
        await asyncio.sleep(0.05)
    await message.reply_text(f"📢 Broadcast sent to {sent} users, failed: {failed}")

# ====================
# STATS
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
    if chunk: await message.reply_text(chunk, disable_web_page_preview=True)    
    
    
# ====================
# BOT COMMANDS (AUTO SET)
# ====================
user_commands = [
    BotCommand("start", "👋 Start & Register"),
]

admin_commands = [
    BotCommand("ban", "⛔ 𝗕𝗮𝗻 𝗮 𝗨𝘀𝗲𝗿 [ADMIN]"),
    BotCommand("unban", "✅ 𝗨𝗻𝗯𝗮𝗻 𝗮 𝗨𝘀𝗲𝗿 [ADMIN]"),
    BotCommand("count_banned", "📛 𝗖𝗵𝗲𝗰𝗸 𝗕𝗮𝗻𝗻𝗲𝗱 𝗨𝘀𝗲𝗿𝘀 [ADMIN]"),
    BotCommand("broadcast", "📢 𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁 𝗮 𝗠𝗲𝘀𝘀𝗮𝗴𝗲 [ADMIN]"),
    BotCommand("stats", "📊 Get Detailed User Stats [ADMIN]"),
    BotCommand("setwelcome", "👋 Set Welcome Message [ADMIN]"),
    BotCommand("delwelcome", "🗑️ Delete Welcome Message [ADMIN]"),
    BotCommand("reply", "✉️ Reply To User [ADMIN]")
]

await self.set_bot_commands(user_commands + admin_commands)

# ====================
# DAILY MOTIVATION FUNCTIONS
# ====================
def fetch_motivation_text():
    try:
        r = requests.get("https://zenquotes.io/api/today")
        if r.status_code == 200:
            data = r.json()
            return data[0]["q"] + " – " + data[0]["a"]
    except:
        pass
    fallback_quotes = [
        "सपने बड़े देखो और असफल होने से डरो मत। – Norman Vaughan\nDream big and dare to fail.",
        "वो बदलाव बनो जो आप दुनिया में देखना चाहते हैं। – Mahatma Gandhi\nBe the change that you wish to see in the world.",
        "हर दिन छोटे कदम उठाओ। – Anonymous\nSmall steps every day.",
        "आपकी सीमा सिर्फ आपकी कल्पना है।\nYour limitation—it’s only your imagination.",
        "खुद को आगे बढ़ाओ, क्योंकि कोई और आपके लिए यह नहीं करेगा।\nPush yourself, because no one else is going to do it for you."
    ]
    return random.choice(fallback_quotes)

def fetch_motivation_image():
    try:
        r = requests.get("https://source.unsplash.com/800x600/?motivation,inspiration")
        if r.status_code == 200:
            return r.url
    except:
        pass
    return "https://i.ibb.co/MkHGvrhL/photo-2025-08-15-12-04-59-7555109221855920164.jpg"

def send_daily_motivation():
    users = user_profiles_col.find()
    text = fetch_motivation_text()
    image_url = fetch_motivation_image()
    loop = asyncio.get_event_loop()
    for user in users:
        user_id = user["user_id"]
        try:
            asyncio.run_coroutine_threadsafe(
                app.send_photo(user_id, photo=image_url, caption=f"🌅 Daily Motivation 🌟\n\n{text}"),
                loop
            )
        except:
            continue


# ====================
# /setmotivation → Set time for daily motivation
# ====================
@app.on_message(filters.command("setmotivation") & filters.user(OWNER_ID))
async def set_motivation_time(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: /setmotivation HH:MM (24-hour format)")

    try:
        time_str = message.command[1]
        hour, minute = map(int, time_str.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return await message.reply("⚠️ Invalid time format!")

        # Save in DB
        motivation_time_col.update_one(
            {"_id": "daily_motivation"},
            {"$set": {"hour": hour, "minute": minute}},
            upsert=True
        )

        # Remove existing job if exists
        scheduler.remove_all_jobs()
        # Add new job
        scheduler.add_job(send_daily_motivation, "cron", hour=hour, minute=minute, timezone="Asia/Kolkata")

        await message.reply(f"✅ Daily motivation time set to {hour:02d}:{minute:02d} IST")
    except:
        await message.reply("⚠️ Something went wrong. Use HH:MM format.")

# ====================
# /delmotivation → Delete scheduled daily motivation
# ====================
@app.on_message(filters.command("delmotivation") & filters.user(OWNER_ID))
async def delete_motivation_time(client: Client, message: Message):
    result = motivation_time_col.delete_one({"_id": "daily_motivation"})
    scheduler.remove_all_jobs()
    if result.deleted_count:
        await message.reply("🗑️ Daily motivation schedule deleted!")
    else:
        await message.reply("⚠️ No daily motivation schedule was set.")


# ====================
# RUN BOT
# ====================
async def main():
    # Set commands first
    await set_bot_commands()
    
    # Start Flask in background
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Scheduler start
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_daily_quote_job, "cron", hour=7, minute=0, timezone="Asia/Kolkata")
    scheduler.start()

    print("✅ Gemini AI Bot Started with MongoDB + Clone + Motivation System...")
    # Start the bot
    await app.start()
    print("Bot is now running...")
    await app.idle()  # Keeps bot running until Ctrl+C

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
