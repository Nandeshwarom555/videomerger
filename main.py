import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from moviepy.editor import VideoFileClip, concatenate_videoclips
from uuid import uuid4

user_videos = {}
DOWNLOAD_FOLDER = "downloads"
MERGED_FOLDER = "merged"

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(MERGED_FOLDER, exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me videos one by one. When done, type /merge to combine them.")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    video = update.message.video or update.message.document

    if not video:
        await update.message.reply_text("Please send a valid video.")
        return

    file = await context.bot.get_file(video.file_id)
    filename = f"{uuid4()}.mp4"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    await file.download_to_drive(filepath)

    if user_id not in user_videos:
        user_videos[user_id] = []
    user_videos[user_id].append(filepath)

    await update.message.reply_text(f"Video received! {len(user_videos[user_id])} video(s) so far.")

async def merge_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    video_paths = user_videos.get(user_id, [])

    if len(video_paths) < 2:
        await update.message.reply_text("You need to send at least two videos to merge.")
        return

    await update.message.reply_text("Merging videos... Please wait.")

    try:
        clips = [VideoFileClip(v) for v in video_paths]
        final_clip = concatenate_videoclips(clips)
        merged_path = os.path.join(MERGED_FOLDER, f"merged_{uuid4()}.mp4")
        final_clip.write_videofile(merged_path, codec="libx264", audio_codec="aac")

        await context.bot.send_video(chat_id=update.effective_chat.id, video=open(merged_path, 'rb'))

    except Exception as e:
        await update.message.reply_text(f"Error while merging: {e}")

    finally:
        for path in video_paths:
            os.remove(path)
        user_videos[user_id] = []

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    for path in user_videos.get(user_id, []):
        if os.path.exists(path):
            os.remove(path)
    user_videos[user_id] = []
    await update.message.reply_text("Cleared all your uploaded videos.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("merge", merge_videos))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
