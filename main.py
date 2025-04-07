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

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage for user videos
user_videos = {}

# Health check server (important for Koyeb)
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
    await update.message.reply_text("👋 Welcome! Send at least 2 videos (MP4 or MKV), and I'll merge them for you.")

# /reset command
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_videos[user_id] = []
    await update.message.reply_text("✅ Your uploaded videos have been cleared. Send new ones now!")

# Handle video or document uploads
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_videos:
        user_videos[user_id] = []

    video = update.message.video or update.message.document
    if not video or not video.mime_type.startswith("video"):
        await update.message.reply_text("❌ Please send a valid video file (MP4 or MKV).")
        return

    file = await video.get_file()
    filename = f"/tmp/{uuid.uuid4()}.mp4"
    await file.download_to_drive(filename)
    user_videos[user_id].append(filename)

    logger.info(f"Received video from user {user_id}. Total: {len(user_videos[user_id])}")

    await update.message.reply_text(f"✅ Received video #{len(user_videos[user_id])}.")

    # Show buttons
    keyboard = [
        [InlineKeyboardButton("➕ Upload More", callback_data="upload_more")],
        [InlineKeyboardButton("🛠 Merge Now", callback_data="merge_now")]
    ]
    await update.message.reply_text("What would you like to do next?", reply_markup=InlineKeyboardMarkup(keyboard))

# Handle button actions
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "upload_more":
        await query.edit_message_text("📤 Please send another video.")
    elif query.data == "merge_now":
        await query.edit_message_text("⏳ Merging your videos. Please wait...")
        await merge_videos(user_id, query.message, context)

# Merging logic
async def merge_videos(user_id, reply_target, context: ContextTypes.DEFAULT_TYPE):
    videos = user_videos.get(user_id, [])
    if len(videos) < 2:
        await reply_target.reply_text("❗ You need to upload at least 2 videos to merge.")
        return

    output_path = f"/tmp/merged_{uuid.uuid4()}.mp4"
    try:
        clips = [VideoFileClip(v) for v in videos]
        final_clip = concatenate_videoclips(clips)
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")

        await context.bot.send_video(chat_id=user_id, video=open(output_path, "rb"))
        await reply_target.reply_text("✅ Done! Here is your merged video.")
    except Exception as e:
        logger.error(f"Merge failed: {e}")
        await reply_target.reply_text(f"❌ Failed to merge videos: {e}")
    finally:
        for v in videos:
            try:
                os.remove(v)
            except Exception:
                pass
        if os.path.exists(output_path):
            os.remove(output_path)
        user_videos[user_id] = []

# /merge command (optional)
async def merge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await merge_videos(user_id, update.message, context)

# Main function
def main():
    start_health_server()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise Exception("BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("merge", merge_command))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
