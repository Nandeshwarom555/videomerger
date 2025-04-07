import logging
import os
import threading
import uuid
import asyncio
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Setup logging
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable not set!")

# In-memory store for user videos
user_videos = {}

# --- Dummy HTTP server to satisfy Koyeb health check ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_dummy_server():
    server = HTTPServer(('0.0.0.0', 8000), DummyHandler)
    server.serve_forever()

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me multiple videos (MP4/MKV), then send /merge to combine them.")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    video = update.message.video or update.message.document

    if not video:
        await update.message.reply_text("❌ Unsupported file. Send MP4/MKV videos only.")
        return

    file = await context.bot.get_file(video.file_id)
    ext = os.path.splitext(video.file_name)[-1]
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join("downloads", filename)

    os.makedirs("downloads", exist_ok=True)
    await file.download_to_drive(filepath)

    user_videos.setdefault(user_id, []).append(filepath)
    await update.message.reply_text(f"✅ Video received. Total files: {len(user_videos[user_id])}")

async def merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    files = user_videos.get(user_id, [])

    if len(files) < 2:
        await update.message.reply_text("❗️Send at least two videos to merge.")
        return

    list_path = f"downloads/{uuid.uuid4()}_list.txt"
    output_path = f"downloads/{uuid.uuid4()}_merged.mp4"

    with open(list_path, "w") as f:
        for file_path in files:
            f.write(f"file '{file_path}'\n")

    try:
        cmd = ["ffmpeg", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path]
        subprocess.run(cmd, check=True)

        size = os.path.getsize(output_path)
        if size > 2 * 1024 * 1024 * 1024:
            await update.message.reply_text("❌ Merged file is too large for Telegram (limit: 2GB).")
        else:
            await update.message.reply_video(video=open(output_path, "rb"), caption="🎬 Here is your merged video!")

    except subprocess.CalledProcessError:
        await update.message.reply_text("⚠️ Failed to merge videos.")
    finally:
        # Cleanup
        for file in files:
            os.remove(file)
        if os.path.exists(output_path):
            os.remove(output_path)
        if os.path.exists(list_path):
            os.remove(list_path)
        user_videos[user_id] = []

# --- Start everything ---
if __name__ == '__main__':
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("merge", merge))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    print("Bot is running...")
    app.run_polling()
