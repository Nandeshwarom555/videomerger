import os
import uuid
import logging
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from moviepy.editor import VideoFileClip, concatenate_videoclips

# Enable logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory user video storage
user_videos = {}

# Health check for Koyeb
def start_health_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running...")

    threading.Thread(target=lambda: HTTPServer(("", 8000), Handler).serve_forever(), daemon=True).start()

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me at least 2 videos (.mp4 or .mkv), then press 'Merge Now'!")

# Reset command
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_videos[user_id] = []
    await update.message.reply_text("✅ Cleared your uploaded videos. You can send new ones now.")

# Handle videos
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_videos:
        user_videos[user_id] = []

    video_file = None
    if update.message.video:
        video_file = update.message.video
    elif update.message.document and update.message.document.mime_type.startswith("video"):
        video_file = update.message.document

    if not video_file:
        await update.message.reply_text("❌ Please send a valid video file (.mp4 or .mkv).")
        return

    file = await video_file.get_file()
    filename = f"/tmp/{uuid.uuid4()}.mp4"
    await file.download_to_drive(filename)
    user_videos[user_id].append(filename)

    await update.message.reply_text(f"✅ Video received! You've uploaded {len(user_videos[user_id])} video(s).")

    # Show buttons after each upload
    keyboard = [
        [InlineKeyboardButton("➕ Upload More", callback_data="upload_more")],
        [InlineKeyboardButton("🛠 Merge Now", callback_data="merge_now")]
    ]
    await update.message.reply_text("What would you like to do next?", reply_markup=InlineKeyboardMarkup(keyboard))

# Button callbacks
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update
