from pyrogram import Client, filters
from pyrogram.types import Message
from flask import Flask
from pymongo import MongoClient
import asyncio
import threading
import os
from datetime import datetime
import re
import config

# ====================
# DATABASE
# ====================
client = MongoClient(MONGO_URI)
db = client["gemini_bot_db"]

memory_col = db["memory"]
mode_col = db["modes"]
api_keys_col = db["api_keys"]
user_profiles_col = db["user_profiles"]

# ====================
# BOT CLIENT
# ====================
app = Client(
    "gemini_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100  # Render / Docker friendly
)

# Dictionary to track clone bots
clones = {}

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
        await message.reply_text("👑 Admin Panel Ready!")
    else:
        await message.reply_text(
            "👋 Namaste! Yeh ek Livegram Style ChatBot hai.\n"
            "Apka message directly Admin ko bhej diya jayega."
        )

# ====================
# FORWARD USER → ADMIN
# ====================
@app.on_message(filters.private & ~filters.user(OWNER_ID))
async def forward_user_msg(client: Client, message: Message):
    user = message.from_user
    user_id = user.id
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else f"tg://user?id={user_id}"

    # Save message in DB
    memory_col.insert_one({
        "user_id": user_id,
        "message": message.text or "📎 Media",
        "timestamp": datetime.utcnow()
    })

    # Forward to admin
    fwd = await message.forward(OWNER_ID)

    info_text = (
        f"👤 New Message\n"
        f"📛 Name: {full_name}\n"
        f"🆔 ID: {user_id}\n"
        f"🔗 Profile: {username}\n"
        f"💬 Message: {message.text if message.text else '📎 Media'}"
    )

    await fwd.reply_text(info_text)  # plain text

# ====================
# ADMIN REPLY → USER
# ====================
@app.on_message(filters.private & filters.user(OWNER_ID) & filters.reply)
async def reply_to_user(client: Client, message: Message):
    try:
        text = message.reply_to_message.text
        match = re.search(r'🆔 ID: (\d+)', text)
        if not match:
            return await message.reply_text("⚠️ User ID not found!")

        user_id = int(match.group(1))

        memory_col.insert_one({
            "user_id": user_id,
            "admin_reply": message.text,
            "timestamp": datetime.utcnow()
        })

        await client.send_message(user_id, f"📩 Admin: {message.text}")
        await message.reply_text("✅ Reply delivered.")

    except Exception as e:
        await message.reply_text(f"⚠️ Error: {e}")

# ====================
# BROADCAST SYSTEM
# ====================
@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚡ Usage: /broadcast Your message here")

    text = message.text.split(" ", 1)[1]
    users = user_profiles_col.find()
    sent, failed = 0, 0

    for user in users:
        try:
            await client.send_message(user["user_id"], f"📢 Broadcast:\n\n{text}")
            sent += 1
        except:
            failed += 1
        await asyncio.sleep(0.05)  # prevent floodwait

    await message.reply_text(f"✅ Broadcast sent to {sent} users, ❌ Failed: {failed}")

# ====================
# STATS COMMAND
# ====================
@app.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def stats_cmd(client: Client, message: Message):
    total_users = user_profiles_col.count_documents({})
    await message.reply_text(f"📊 Total registered users: {total_users}")

# ====================
# CLONE SYSTEM
# ====================
@app.on_message(filters.command("clone") & filters.user(OWNER_ID))
async def clone_bot(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚡ Usage: /clone BOT_TOKEN")

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
        await message.reply_text(f"⚠️ Clone failed: {e}")

# ====================
# FLASK HEALTH CHECK
# ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "✅ Gemini AI Bot running with MongoDB + Clone System!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

# ====================
# RUN BOT + FLASK
# ====================
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    print("🤖 Gemini AI Livegram Bot Started with MongoDB + Clone System...")
    app.run()
