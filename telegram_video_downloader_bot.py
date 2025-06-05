import os
import subprocess
import asyncio
from yt_dlp import YoutubeDL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.environ['BOT_TOKEN']

user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a YouTube or M3U8 link to start. I'll let you pick video quality and send you the video!"
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    chat_id = update.effective_chat.id
    user_states[chat_id] = {'url': url}

    await update.message.reply_text("Fetching available qualities, please wait...")

    try:
        with YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [info])

            qualities = [
                (f"{f['format_id']} - {f.get('format_note', f.get('height', ''))}p", f['format_id'])
                for f in formats if f.get('vcodec', 'none') != 'none' and f.get('acodec', 'none') != 'none'
            ]
            if not qualities:
                await update.message.reply_text("Couldn't find downloadable video formats.")
                return

            user_states[chat_id]['qualities'] = qualities

            keyboard = [
                [InlineKeyboardButton(text, callback_data=format_id)]
                for text, format_id in qualities
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Choose quality:", reply_markup=reply_markup)
    except Exception as e:
        await update.message.reply_text(f"Error fetching formats: {e}")

async def quality_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    format_id = query.data
    url = user_states[chat_id]['url']

    msg = await query.edit_message_text("Downloading...")

    output_file = f"{chat_id}_video.%(ext)s"
    progress_msg = msg

    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '??')
            asyncio.run_coroutine_threadsafe(
                progress_msg.edit_text(f"Downloading: {percent}"), context.application.loop
            )

    ydl_opts = {
        'format': format_id,
        'outtmpl': output_file,
        'progress_hooks': [progress_hook],
        'quiet': True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url)

        ext = info['ext']
        local_path = output_file.replace('%(ext)s', ext)

        # If m3u8, convert to mp4
        if '.m3u8' in info.get('url', '') or ext == 'm3u8':
            mp4_path = local_path.replace(ext, 'mp4')
            ffmpeg_cmd = ['ffmpeg', '-y', '-i', local_path, '-c', 'copy', mp4_path]
            subprocess.run(ffmpeg_cmd, check=True)
            os.remove(local_path)
            final_path = mp4_path
        else:
            final_path = local_path

        await progress_msg.edit_text("Uploading video to Telegram...")
        with open(final_path, 'rb') as f:
            await context.bot.send_video(chat_id=chat_id, video=f)
        os.remove(final_path)
        await progress_msg.delete()
    except Exception as e:
        await progress_msg.edit_text(f"Error downloading or sending video: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(quality_selected))
    print('Bot is running...')
    app.run_polling()
