import os
import subprocess
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import yt_dlp
import asyncio

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Helper to check and install ffmpeg on Railway
def ensure_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Install ffmpeg
        subprocess.run(
            "apt-get update && apt-get install -y ffmpeg",
            shell=True,
            check=True
        )

# Ensure ffmpeg is present before starting the bot
ensure_ffmpeg()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a YouTube or M3U8 link and I'll let you pick the video quality for download."
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    await update.message.reply_text("Fetching available formats, please wait...")
    ydl_opts = {"quiet": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get("formats", [])
        # Filter out video-only and audio-only; show progressive/mp4 first
        qualities = []
        for f in formats:
            if f.get("vcodec") != "none" and f.get("acodec") != "none" and f.get("ext") == "mp4":
                label = f"{f.get('format_note', f.get('height', ''))} ({f.get('height', '')}p) - {f.get('filesize', 0)//1024//1024}MB"
                qualities.append((label, f["format_id"]))
        if not qualities:
            for f in formats:
                if f.get("vcodec") != "none" and f.get("acodec") != "none":
                    label = f"{f.get('format_note', f.get('height', ''))} ({f.get('height', '')}p) - {f.get('filesize', 0)//1024//1024}MB"
                    qualities.append((label, f["format_id"]))

        if not qualities:
            await update.message.reply_text("No downloadable video qualities found.")
            return

        keyboard = [
            [InlineKeyboardButton(text, callback_data=f"{f['format_id']}|{url}")]
            for text, format_id in qualities
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose quality:", reply_markup=reply_markup)
    except Exception as e:
        await update.message.reply_text(f"Failed to fetch video info: {e}")

async def quality_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if "|" in data:
        format_id, url = data.split("|", 1)
    else:
        await query.edit_message_text("Invalid selection.")
        return

    await query.edit_message_text("Downloading video, please wait...")

    output_filename = f"video_{query.from_user.id}.mp4"
    ydl_opts = {
        "format": format_id,
        "outtmpl": output_filename,
        "quiet": True,
        "noplaylist": True,
        "retries": 3,
        "merge_output_format": "mp4",
        "ffmpeg_location": "/usr/bin/ffmpeg",
        "progress_hooks": [lambda d: None],  # No progress
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        # Telegram max file size for bot upload is 2GB
        file_size = os.path.getsize(output_filename)
        if file_size > 1.9 * 1024 * 1024 * 1024:
            await query.edit_message_text("File is too large for Telegram to send (max 2GB).")
        else:
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=open(output_filename, "rb"),
                supports_streaming=True,
                caption="Here is your video!"
            )
        os.remove(output_filename)
    except Exception as e:
        await query.edit_message_text(f"Download/send failed: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    application.add_handler(CallbackQueryHandler(quality_selected))
    application.run_polling()

if __name__ == "__main__":
    main()
