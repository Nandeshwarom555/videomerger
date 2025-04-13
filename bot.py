import os
import logging
import shutil
import tempfile
import subprocess
import threading
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from flask import Flask

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}
MAX_FILE_SIZE_MB = 2000

# --- Command: /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_sessions[update.effective_user.id] = {
        "videos": [],
        "tempdir": tempfile.mkdtemp(),
        "progress": None,
        "merging": False,
        "cancel": False,
        "thumbnail": None
    }
    await update.message.reply_text("Send me multiple video files. When you're done, press the 'Merge Videos' button.")

# --- Command: /cancel ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        user_sessions[user_id]["cancel"] = True
        await update.message.reply_text("Operation cancelled.")
    else:
        await update.message.reply_text("Nothing to cancel.")

# --- Handle Video Uploads ---
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)

    if not session:
        await update.message.reply_text("Please send /start first.")
        return

    file = update.message.video or update.message.document
    if not file:
        await update.message.reply_text("That doesn't look like a video.")
        return

    file_id = str(uuid4())
    filepath = os.path.join(session["tempdir"], f"{file_id}.mp4")
    file_obj = await file.get_file()
    await file_obj.download_to_drive(filepath)

    session["videos"].append(filepath)
    await update.message.reply_text(f"Saved: {file.file_name or 'video'}")

    keyboard = [
        [InlineKeyboardButton("✅ Merge Videos", callback_data="merge_videos")],
        [InlineKeyboardButton("📊 Status", callback_data="check_status")]
    ]
    await update.message.reply_text("Click below when you're done uploading:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Handle Thumbnail Upload ---
async def handle_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)

    if not session or not session.get("waiting_for_thumbnail"):
        return

    file = update.message.photo[-1] if update.message.photo else update.message.document
    if not file:
        await update.message.reply_text("Send a valid image as thumbnail.")
        return

    thumb_path = os.path.join(session["tempdir"], "thumb.jpg")
    file_obj = await file.get_file()
    await file_obj.download_to_drive(thumb_path)

    session["thumbnail"] = thumb_path
    session["waiting_for_thumbnail"] = False
    await update.message.reply_text("Thumbnail received. Sending final video now...")

# --- Skip Thumbnail Option ---
async def skip_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session:
        return

    session["thumbnail"] = "default_thumbnail.jpg"
    session["waiting_for_thumbnail"] = False
    await update.message.reply_text("You have skipped the thumbnail. Sending final video now...")

# --- Merge Button Handler ---
async def handle_merge_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    session = user_sessions.get(user_id)

    if not session or not session["videos"]:
        await query.edit_message_text("No videos uploaded.")
        return

    session["progress"] = "Starting merge..."
    session["merging"] = True
    await query.edit_message_text("Merging videos... Use the 📊 Status button to check progress.")

    output_path = os.path.join(session["tempdir"], "merged_output.mp4")

    def merge_task():
        try:
            if session["cancel"]:
                return

            merge_videos(session["videos"], output_path, session)

            if os.path.getsize(output_path) > MAX_FILE_SIZE_MB * 1024 * 1024:
                keyboard = [
                    [InlineKeyboardButton("🗜 Compress to under 2GB", callback_data="compress")],
                    [InlineKeyboardButton("✂ Split into 2GB parts", callback_data="split")]
                ]
                context.bot.send_message(chat_id=user_id, text="Output is too large (>2GB). Choose an option:", reply_markup=InlineKeyboardMarkup(keyboard))
                return

            preview_path = generate_preview(output_path, session["tempdir"])
            context.bot.send_video(chat_id=user_id, video=open(preview_path, 'rb'), caption="Here is a 30s preview. Now send me a custom thumbnail image or skip it.")
            session["waiting_for_thumbnail"] = True
        except Exception as e:
            logger.error("Merge failed: %s", str(e))
            context.bot.send_message(chat_id=user_id, text="Merging failed.")
            session["merging"] = False
            shutil.rmtree(session["tempdir"], ignore_errors=True)
            del user_sessions[user_id]

    threading.Thread(target=merge_task).start()

# --- Handle Compress or Split ---
async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    session = user_sessions[user_id]
    output_path = os.path.join(session["tempdir"], "merged_output.mp4")

    if query.data == "compress":
        compressed_path = os.path.join(session["tempdir"], "compressed.mp4")
        subprocess.run(["ffmpeg", "-i", output_path, "-b:v", "2M", "-fs", f"{MAX_FILE_SIZE_MB}M", "-y", compressed_path])
        await query.edit_message_text("Compressed. Sending preview...")
        preview_path = generate_preview(compressed_path, session["tempdir"])
        await context.bot.send_video(chat_id=user_id, video=open(preview_path, 'rb'), caption="Here is a 30s preview. Now send me a custom thumbnail image or skip it.")
        session["waiting_for_thumbnail"] = True
    elif query.data == "split":
        await query.edit_message_text("Splitting video...")
        parts = split_video(output_path, session["tempdir"], MAX_FILE_SIZE_MB)
        for i, part in enumerate(parts):
            await context.bot.send_document(chat_id=user_id, document=InputFile(part), caption=f"Part {i+1}")
        await context.bot.send_message(chat_id=user_id, text="All parts sent!")
        cleanup_session(user_id)

# --- Generate 30s Preview ---
def generate_preview(video_path, tempdir):
    preview_path = os.path.join(tempdir, "preview.mp4")
    subprocess.run(["ffmpeg", "-i", video_path, "-t", "30", "-c:v", "libx264", "-c:a", "aac", "-y", preview_path])
    return preview_path

# --- Split Large Video into Parts ---
def split_video(input_path, tempdir, max_mb):
    split_cmd = [
        "ffmpeg", "-i", input_path, "-c", "copy", "-f", "segment", "-segment_time", "600",
        os.path.join(tempdir, "part%03d.mp4")
    ]
    subprocess.run(split_cmd)
    return [os.path.join(tempdir, f) for f in os.listdir(tempdir) if f.startswith("part")]

# --- Merge Core Logic ---
def merge_videos(input_paths, output_path, session):
    tempdir = tempfile.mkdtemp()
    reencoded = []
    for i, path in enumerate(input_paths):
        out_path = os.path.join(tempdir, f"vid{i}.mp4")
        subprocess.run(["ffmpeg", "-i", path, "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-y", out_path])
        reencoded.append(out_path)

    concat_list = os.path.join(tempdir, "list.txt")
    with open(concat_list, 'w') as f:
        for fpath in reencoded:
            f.write(f"file '{fpath}'\n")

    subprocess.run(["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", "-y", output_path])
    shutil.rmtree(tempdir, ignore_errors=True)

# --- Status Button ---
async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    session = user_sessions.get(user_id)

    if not session or not session["merging"]:
        await query.edit_message_text("No active merging process.")
        return

    progress = session.get("progress", "Waiting for update...")
    await query.edit_message_text(f"🔄 Merging in progress...\n\n{progress}")

# --- Cleanup Session ---
def cleanup_session(user_id):
    shutil.rmtree(user_sessions[user_id]["tempdir"], ignore_errors=True)
    del user_sessions[user_id]

# --- Flask App (MUST be named 'app') ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

# --- Telegram Bot Start ---
def main():
    TOKEN = os.getenv("BOT_TOKEN")
    telegram_app = ApplicationBuilder().token(TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("cancel", cancel))
    telegram_app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    telegram_app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_thumbnail))
    telegram_app.add_handler(CallbackQueryHandler(handle_merge_button, pattern="merge_videos"))
    telegram_app.add_handler(CallbackQueryHandler(handle_status, pattern="check_status"))
    telegram_app.add_handler(CallbackQueryHandler(handle_choice, pattern="compress|split"))
    telegram_app.add_handler(CallbackQueryHandler(skip_thumbnail, pattern="skip_thumbnail"))

    telegram_app.run_polling()

if __name__ == "__main__":
    main()
