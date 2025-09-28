from pyrogram import Client, filters, idle
from pyrogram.types import Message
from flask import Flask
from pymongo import MongoClient
import asyncio
import threading
import os
from datetime import datetime
import re
import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, PORT, MONGO_URI

# ====================
# DATABASE
# ====================
client = MongoClient(MONGO_URI)
db = client["gemini_bot_db"]

memory_col = db["memory"]
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
CHANNEL_ID = -1002966725498  # Your channel ID

quotes = [
    "Dream, dream, dream. Dreams transform into thoughts and thoughts result in action. – A.P.J. Abdul Kalam",
    "Be the change that you wish to see in the world. – Mahatma Gandhi",
    "Arise, awake, and stop not until the goal is reached. – Swami Vivekananda",
    "Excellence is not a skill. It is an attitude. – Ralph Marston",
    "Small aim is a crime; have great aim. – A.P.J. Abdul Kalam"
]

async def send_daily_quote():
    quote = random.choice(quotes)
    await app.send_message(CHANNEL_ID, f"🌅 Good Morning!\n\n{quote}")

# ====================
# MANUAL POSTING
# ====================
@app.on_message(filters.command("post") & filters.user(OWNER_ID))
async def manual_post(client, message: Message):
    if len(message.command) > 1:
        text = " ".join(message.command[1:])
        await app.send_message(CHANNEL_ID, text)
        await message.reply("✅ Posted to channel!")
    elif message.reply_to_message:
        await message.reply_to_message.copy(CHANNEL_ID)
        await message.reply("✅ Media posted to channel!")
    else:
        await message.reply("⚠️ Usage: /post <your message> or reply to media with /post")

# ====================
# START COMMAND
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

    if user.id == OWNER_ID:
        await message.reply_text("✅ Admin Panel Ready!")
    else:
        await message.reply_text("Hello! Your message (text/media) will be sent to the admin.")

# ====================
# FORWARD USER → ADMIN
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

    users = user_profiles_col.find().sort("joined_at", -1)  # latest first
    all_lines = []

    for u in users:
        user_id = u.get("user_id")
        fname = u.get("first_name", "")
        lname = u.get("last_name", "")
        uname = f"@{u['username']}" if u.get("username") else f"[Link](tg://user?id={user_id})"
        joined = u.get("joined_at", "")
        line = f"👤 {fname} {lname}\n🆔 {user_id}\n🔗 {uname}\n📅 {joined}\n"
        all_lines.append(line)

    # Telegram message limit handling
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
# FLASK HEALTH CHECK
# ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Gemini AI Bot running with MongoDB + Clone + Motivation!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

# ====================
# RUN BOT + SCHEDULER + FLASK
# ====================
if __name__ == "__main__":
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_quote, "cron", hour=7, minute=0, timezone="Asia/Kolkata")

    async def main():
        scheduler.start()
        threading.Thread(target=run_flask).start()
        print("Gemini AI Bot Started with MongoDB + Clone + Motivation System...")
        await app.start()
        await idle()

    asyncio.run(main())
