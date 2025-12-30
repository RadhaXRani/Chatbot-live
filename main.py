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
# CONFIG
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
    """Random motivational text"""
    fallback_quotes = [
        "Dream big and dare to fail. – Norman Vaughan",
        "Be the change that you wish to see in the world. – Mahatma Gandhi",
        "Small steps every day. – Anonymous",
        "Your limitation—it’s only your imagination.",
        "Push yourself, because no one else is going to do it for you."
    ]
    return random.choice(fallback_quotes)

def fetch_motivation_image():
    """Static fallback image"""
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
# /userstats → Show total, active, banned users
# ====================
@app.on_message(filters.command("userstats") & filters.user(OWNER_ID))
async def userstats_cmd(client: Client, message: Message):
    total_users = user_profiles_col.count_documents({})
    banned_users = user_profiles_col.count_documents({"banned": True})
    active_users = total_users - banned_users

    text = (
        f"📊 User Statistics 📊\n\n"
        f"👥 Total Users: {total_users}\n"
        f"✅ Active Users: {active_users}\n"
        f"🚫 Banned Users: {banned_users}"
    )

    await message.reply_text(text)
# ====================
# /setwelcome → Set Welcome
# ====================
@app.on_message(filters.command("setwelcome") & filters.user(OWNER_ID))
async def set_welcome(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply(
            "⚠️ Reply to a photo/text to set welcome.\n"
            "Optional: `btn=Text1|URL1,Text2|URL2` or JSON format `btn=[{'text':'T','url':'U'}]`"
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
    user_id = user.id
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    username = user.username or ""

    # =========================
    # Save user in DB
    # =========================
    user_profiles_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "joined_at": datetime.utcnow()
        }},
        upsert=True
    )

    # =========================
    # Notify OWNER
    # =========================
    try:
        profile_link = f"@{username}" if username else f"tg://user?id={user_id}"
        notice_text = (
            f"👤 New User Started Bot\n"
            f"🆔 ID: {user_id}\n"
            f"Name: {first_name} {last_name}\n"
            f"Profile: {profile_link}\n"
            f"Joined At: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await client.send_message(OWNER_ID, notice_text)
    except:
        pass

    # =========================
    # Send Welcome
    # =========================
    config = welcome_col.find_one({"_id": "welcome"})
    if config:
        caption = config.get("caption", f"👋 Welcome {first_name}!")
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
        default_caption = f"👋 Welcome {first_name} ❤️\nAsk your questions or doubts, I will reply soon!"
        await client.send_photo(message.chat.id, photo=default_photo, caption=default_caption,
                                reply_markup=InlineKeyboardMarkup(default_buttons))


@app.on_message(filters.command("allusers") & filters.user(OWNER_ID))
async def all_users_cmd(client: Client, message: Message):
    users = user_profiles_col.find()
    if not users:
        return await message.reply("⚠️ No users found in database.")

    all_lines = []
    for u in users:
        user_id = u.get("user_id")
        first_name = u.get("first_name", "")
        last_name = u.get("last_name", "")
        line = f"👤 {first_name} {last_name} | 🆔 {user_id}"
        all_lines.append(line)

    # Agar bahut users hai, file me bhej dete hai
    if len(all_lines) > 50:
        file_path = "users_list.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(all_lines))
        await message.reply_document(file_path, caption=f"📄 Total Users: {len(all_lines)}")
    else:
        await message.reply("\n".join(all_lines))

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

    # Forward message to admin
    fwd = await message.forward(OWNER_ID)
    info_text = (
        f"📩 New Message\n"
        f"👤 Name: {user.first_name} {user.last_name or ''}\n"
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
# ADMIN REPLY → USER
# ====================
@app.on_message(filters.private & filters.user(OWNER_ID) & filters.reply)
async def reply_to_user(client: Client, message: Message):
    try:
        reply_to = message.reply_to_message
        import re
        match = re.search(r'ID: (\d+)', reply_to.text)
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
        uname = f"@{u['username']}" if u.get("username") else f"Link"
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
# RUN BOT
# ====================
if __name__ == "__main__":
    # Flask background
    threading.Thread(target=run_flask, daemon=True).start()

    # Scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_daily_motivation, "cron", hour=5, minute=0, timezone="Asia/Kolkata")
    scheduler.start()

    print("✅ Gemini AI Bot Started with MongoDB + Motivation System...")
    app.run()                         
