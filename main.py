import os
import uuid
import subprocess
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from moviepy.editor import VideoFileClip, concatenate_videoclips

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory store for user video uploads
user_videos = {}

# Health check server for Koyeb
def start_health_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running...")

    def run():
        server = HTTPServer(("", 8000), Handler)
        server.serve_forever()

    threading.Thread(target=run, daemon=True).start()

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me at least 2 videos (.mp4 or .mkv), then press 'Merge Now'!")

# /reset command
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_videos[user_id] = []
    await update.message.reply_text("✅ Cleared your uploaded videos. You can send new ones now.")

# Handle incoming videos
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

    # Show buttons after file is received
    keyboard = [
        [InlineKeyboardButton("➕ Upload More", callback_data="upload_more")],
        [InlineKeyboardButton("🛠 Merge Now", callback_data="merge_now")]
    ]
    await update.message.reply_text("What would you like to do next?", reply_markup=InlineKeyboardMarkup(keyboard))

# Handle callback buttons
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "upload_more":
        await query.edit_message_text("📤 Okay, send another video.")
    elif query.data == "merge_now":
        await query.edit_message_text("⏳ Merging your videos...")
        await do_merge(user_id, query.message, context)

# /merge command (alternative to button)
async def merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await do_merge(user_id, update.message, context)

# Perform merging
async def do_merge(user_id, reply_target, context: ContextTypes.DEFAULT_TYPE):
    videos = user_videos.get(user_id, [])
    if len(videos) < 2:
        await reply_target.reply_text("❗ You need to upload at least 2 videos to merge.")
        return

    await reply_target.reply_text("🔄 Merging videos. Please wait...")

    try:
        clips = [VideoFileClip(v) for v in videos]
        final_clip = concatenate_videoclips(clips, method="compose")
        output_path = f"/tmp/merged_{uuid.uuid4()}.mp4"
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")

        await context.bot.send_video(chat_id=user_id, video=open(output_path, "rb"))
    except Exception as e:
        logger.error(f"Merge error: {e}")
        await reply_target.reply_text(f"❌ Merge failed: {e}")
    finally:
        # Cleanup
        for v in videos:
            try:
                os.remove(v)
            except Exception:
                pass
        if 'output_path' in locals():
            try:
                os.remove(output_path)
            except Exception:
                pass
        user_videos[user_id] = []

# Main function
def main():
    start_health_server()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise Exception("❌ BOT_TOKEN environment variable not set.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("merge", merge))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    app.run_polling()

if __name__ == "__main__":
    main()
