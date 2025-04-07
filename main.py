import os
import uuid
import logging
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from moviepy.editor import VideoFileClip, concatenate_videoclips

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store uploaded videos
user_videos = {}

# Get bot token from environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable not set!")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send at least 2 videos (.mp4 or .mkv), then use /merge to combine them!")

# Reset command
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_videos[user_id] = []
    await update.message.reply_text("🗑️ Video list cleared. Send new videos!")

# Handle video uploads
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_videos:
        user_videos[user_id] = []

    video = update.message.video
    file = await video.get_file()
    filename = f"/tmp/{uuid.uuid4()}.mp4"
    await file.download_to_drive(filename)

    user_videos[user_id].append(filename)
    await update.message.reply_text(f"📥 Video saved! Total: {len(user_videos[user_id])} video(s) uploaded.")

    keyboard = [
        [InlineKeyboardButton("➕ Upload More", callback_data="upload_more")],
        [InlineKeyboardButton("🛠 Merge Now", callback_data="merge_now")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("What would you like to do next?", reply_markup=reply_markup)

# Handle button presses
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "upload_more":
        await query.edit_message_text("✅ Okay! Send another video.")
    elif query.data == "merge_now":
        await merge(update, context, is_callback=True)

# Merge command or button trigger
async def merge(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    user_id = update.effective_user.id
    videos = user_videos.get(user_id, [])

    if len(videos) < 2:
        msg = "❗ You need to upload at least two videos to merge."
        if is_callback:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    if is_callback:
        await update.callback_query.edit_message_text("🔧 Merging videos. Please wait...")
    else:
        await update.message.reply_text("🔧 Merging videos. Please wait...")

    try:
        clips = [VideoFileClip(v) for v in videos]
        final_clip = concatenate_videoclips(clips)
        output_path = f"/tmp/merged_{uuid.uuid4()}.mp4"
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")

        await context.bot.send_video(chat_id=user_id, video=open(output_path, "rb"))

    except Exception as e:
        logger.error(f"Error during merge: {e}")
        await context.bot.send_message(chat_id=user_id, text=f"❌ Merge failed: {e}")

    finally:
        for f in videos:
            if os.path.exists(f):
                os.remove(f)
        if 'output_path' in locals() and os.path.exists(output_path):
            os.remove(output_path)
        user_videos[user_id] = []

# Health check server
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

# Main
def main():
    start_health_server()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("merge", merge))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(CallbackQueryHandler(button))

    application.run_polling()

if __name__ == "__main__":
    main()
