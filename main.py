import os
import logging
import uuid
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from moviepy.editor import VideoFileClip, concatenate_videoclips

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dictionary to store user videos
user_videos = {}

# Health check server for deployment platforms
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

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome! Send me at least two videos (MP4 or MKV), and I'll merge them for you."
    )

# Reset command handler
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_videos[user_id] = []
    await update.message.reply_text("Your uploaded videos have been cleared. You can start uploading new ones.")

# Video message handler
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_videos:
        user_videos[user_id] = []

    video_file = update.message.video or update.message.document
    if not video_file or not video_file.mime_type.startswith("video/"):
        await update.message.reply_text("Please send a valid video file (MP4 or MKV).")
        return

    file = await video_file.get_file()
    filename = f"/tmp/{uuid.uuid4()}.mp4"
    await file.download_to_drive(filename)

    user_videos[user_id].append(filename)
    await update.message.reply_text(f"Video received! You've uploaded {len(user_videos[user_id])} video(s).")

    if len(user_videos[user_id]) >= 2:
        keyboard = [
            [InlineKeyboardButton("Merge Videos", callback_data="merge_now")],
            [InlineKeyboardButton("Upload More", callback_data="upload_more")]
        ]
        await update.message.reply_text(
            "You can upload more videos or merge the current ones.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# Callback query handler
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "upload_more":
        await query.edit_message_text("You can send another video.")
    elif query.data == "merge_now":
        await query.edit_message_text("Merging your videos, please wait...")
        await merge_videos(user_id, query.message, context)

# Merge command handler
async def merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await merge_videos(user_id, update.message, context)

# Function to merge videos
async def merge_videos(user_id, reply_target, context: ContextTypes.DEFAULT_TYPE):
    videos = user_videos.get(user_id, [])
    if len(videos) < 2:
        await reply_target.reply_text("You need to upload at least two videos to merge.")
        return

    await reply_target.reply_text("Merging videos. This may take some time...")

    try:
        clips = [VideoFileClip(v) for v in videos]
        final_clip = concatenate_videoclips(clips, method="compose")
        output_path = f"/tmp/merged_{uuid.uuid4()}.mp4"
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")

        await context.bot.send_video(chat_id=user_id, video=open(output_path, "rb"))
    except Exception as e:
        logger.error(f"Error during merging: {e}")
        await reply_target.reply_text(f"An error occurred: {e}")
    finally:
        for v in videos:
            os.remove(v)
        if 'output_path' in locals():
            os.remove(output_path)
        user_videos[user_id] = []

# Main function to set up the bot
def main():
    start_health_server()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise Exception("BOT_TOKEN environment variable not set.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("merge", merge))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    app.run_polling()

if __name__ == "__main__":
    main()
