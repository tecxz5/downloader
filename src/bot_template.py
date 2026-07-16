import os
import logging
import json
import re
import time
import traceback
import asyncio
import aiohttp
import uuid
import shutil
import glob
import aiofiles
from collections.abc import AsyncGenerator
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, unquote
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, BufferedInputFile
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("UniDLBot")

# === DOWNLOADER_CORE ===

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALLOWED_USERS = [
    int(x.strip()) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()
]
LOCAL_TG_API = os.getenv("LOCAL_TG_API", "http://127.0.0.1:8081")

COBALT_INSTANCE = os.getenv("COBALT_INSTANCE", "http://127.0.0.1:9000/")

# =================

session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_TG_API, is_local=False), timeout=3600)
bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

class ProgressFSInputFile(FSInputFile):
    def __init__(self, path, filename=None, chunk_size=65536, callback=None):
        super().__init__(path, filename=filename, chunk_size=chunk_size)
        self.callback = callback
        self.total_size = os.path.getsize(path)
        self.bytes_read = 0

    async def read(self, bot) -> AsyncGenerator[bytes, None]:
        async with aiofiles.open(self.path, "rb") as f:
            while chunk := await f.read(self.chunk_size):
                self.bytes_read += len(chunk)
                if self.callback:
                    try:
                        await self.callback(self.bytes_read, self.total_size)
                    except Exception:
                        pass
                yield chunk

async def make_upload_callback(status_msg, start_time, tracker_dict=None):
    last_update = [0.0]
    last_bytes = [0]
    if tracker_dict is None:
        tracker_dict = {}
    
    async def callback(current, total):
        if total > 0 and total < 10 * 1024 * 1024:
            return
        if tracker_dict.get("done") or current == total or (total > 0 and current / total > 0.90):
            return
        now = time.time()
        if now - last_update[0] >= 1.5:
            elapsed = now - last_update[0] if last_update[0] > 0.0 else (now - start_time)
            bytes_sent = current - last_bytes[0]
            speed = (bytes_sent / 1048576) / elapsed if elapsed > 0 else 0
            
            last_update[0] = now
            last_bytes[0] = current
            
            percent = (current * 100 / total) if total > 0 else 0
            filled = min(20, int(percent / 5))
            bar = "█" * filled + "▒" * (20 - filled)
            
            cur_mb = current / 1048576
            tot_mb = total / 1048576
            
            text = (
                f"🚀 <b>Загружаем в Telegram...</b>\n"
                f"<code>[{bar}] {percent:.1f}%</code>\n"
                f"📦 <code>{cur_mb:.1f} / {tot_mb:.1f} MB</code>\n"
                f"⚡️ <code>{speed:.1f} MB/s</code>"
            )
            await update_status_media_and_text(status_msg, "uploading", text, tracker_dict, only_text=True)
    return callback

def extract_url(message: types.Message):
    text = message.text or message.caption or ""
    if text:
        match = re.search(r"(https?://[^\s]+)", text)
        if match:
            url = match.group(1).strip()
            while url and url[-1] in ".,!?;:\"')}]>":
                url = url[:-1]
            return clean_url(url)
    return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    await message.answer("👋 <b>Привет!</b> Отправь мне ссылку на видео (YouTube, TikTok, Instagram), и я его скачаю.", parse_mode="HTML")

async def edit_status_message(status_msg, text):
    try:
        if status_msg.photo or status_msg.document or status_msg.video or status_msg.animation:
            await status_msg.edit_caption(caption=text, parse_mode="HTML")
        else:
            await status_msg.edit_text(text, parse_mode="HTML")
    except Exception:
        pass

async def update_status_media_and_text(status_msg, stage_name, text, tracker, force_media_update=False, only_text=False):
    if "stage" not in tracker:
        tracker["stage"] = None
    if tracker["stage"] != stage_name:
        tracker["stage"] = stage_name
        force_media_update = True
        
    if force_media_update and not only_text:
        gif_path = f"assets/{stage_name}.gif"
        if os.path.exists(gif_path):
            try:
                with open(gif_path, "rb") as f:
                    gif_bytes = f.read()
                media = types.InputMediaAnimation(
                    media=BufferedInputFile(gif_bytes, filename=f"{stage_name}.gif"),
                    caption=text,
                    parse_mode="HTML"
                )
                await bot.edit_message_media(
                    chat_id=status_msg.chat.id,
                    message_id=status_msg.message_id,
                    media=media
                )
                return
            except Exception as e:
                print(f"⚠️ Не удалось сменить стадию на {stage_name}.gif: {e}")
                
    await edit_status_message(status_msg, text)

async def send_media_file(chat_id, file_path, caption=None, reply_to=None, progress_callback=None, status_msg=None, width=None, height=None, duration=None, performer=None, title=None):
    ext = os.path.splitext(file_path)[1].lower()
    input_file = ProgressFSInputFile(file_path, callback=progress_callback)
    
    if ext in ('.mp4', '.mkv', '.mov', '.webm'):
        if width is None or height is None or duration is None:
            width, height, duration = await get_video_metadata(file_path)
                
    try:
        edited = False
        if status_msg:
            try:
                if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                    media_obj = types.InputMediaVideo(
                        media="attach://video_file",
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                        width=width,
                        height=height,
                        duration=duration
                    )
                    res = await bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=status_msg.message_id,
                        media=media_obj,
                        video_file=input_file,
                        request_timeout=3600
                    )
                else:
                    if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                        media_obj = types.InputMediaPhoto(media=input_file, caption=caption, parse_mode="HTML")
                    elif ext in ('.mp3', '.m4a', '.ogg', '.wav', '.flac'):
                        media_obj = types.InputMediaAudio(media=input_file, caption=caption, parse_mode="HTML", duration=duration, performer=performer, title=title)
                    elif ext in ('.gif',):
                        media_obj = types.InputMediaAnimation(media=input_file, caption=caption, parse_mode="HTML")
                    else:
                        media_obj = types.InputMediaDocument(media=input_file, caption=caption, parse_mode="HTML")
                    
                    res = await bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=status_msg.message_id,
                        media=media_obj,
                        request_timeout=3600
                    )
                edited = True
                return res
            except Exception as edit_err:
                print(f"⚠️ Не удалось отредактировать сообщение с медиа, отправляем заново: {edit_err}")
                
        if not edited:
            sent_msg = None
            if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                sent_msg = await bot.send_video(
                    chat_id=chat_id,
                    video=input_file,
                    caption=caption,
                    reply_to_message_id=reply_to,
                    parse_mode="HTML",
                    supports_streaming=True,
                    width=width,
                    height=height,
                    duration=duration,
                    request_timeout=3600
                )
            elif ext in ('.jpg', '.jpeg', '.png', '.webp'):
                sent_msg = await bot.send_photo(chat_id=chat_id, photo=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
            elif ext in ('.mp3', '.m4a', '.ogg', '.wav', '.flac'):
                sent_msg = await bot.send_audio(chat_id=chat_id, audio=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", duration=duration, performer=performer, title=title, request_timeout=3600)
            elif ext in ('.gif',):
                sent_msg = await bot.send_animation(chat_id=chat_id, animation=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
            else:
                sent_msg = await bot.send_document(chat_id=chat_id, document=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
            
            if status_msg and sent_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            return sent_msg
    finally:
        pass

async def send_multiple_media(chat_id, media_files, caption=None, reply_to=None):
    photos_videos = []
    others = []
    
    for path in media_files:
        ext = os.path.splitext(path)[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mkv', '.mov', '.webm'):
            photos_videos.append(path)
        else:
            others.append(path)
            
    if photos_videos:
        if len(photos_videos) == 1 and not others:
            await send_media_file(chat_id, photos_videos[0], caption=caption, reply_to=reply_to)
        else:
            media_group = MediaGroupBuilder(caption=caption)
            for path in photos_videos:
                ext = os.path.splitext(path)[1].lower()
                input_file = FSInputFile(path)
                if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                    media_group.add_photo(media=input_file)
                else:
                    media_group.add_video(media=input_file)
            await bot.send_media_group(chat_id=chat_id, media=media_group.build(), reply_to_message_id=reply_to, request_timeout=3600)
            
    for path in others:
        file_caption = caption if (not photos_videos and path == others[0]) else None
        await send_media_file(chat_id, path, caption=file_caption, reply_to=reply_to)

@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return

    url = extract_url(message)
    if not url:
        return

    safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    status_msg = None
    if os.path.exists("assets/parsing.gif"):
        try:
            with open("assets/parsing.gif", "rb") as f:
                gif_bytes = f.read()
            placeholder = BufferedInputFile(gif_bytes, filename="parsing.gif")
            status_msg = await bot.send_animation(
                chat_id=message.chat.id,
                animation=placeholder,
                caption=f"⏳ <b>Парсим:</b> <code>{safe_url}</code>",
                reply_to_message_id=message.message_id,
                parse_mode="HTML"
            )
        except Exception as e:
            log_warning(f"Failed to send GIF placeholder: {e}")
            
    if not status_msg:
        status_msg = await message.reply(f"⏳ <b>Парсим:</b> <code>{safe_url}</code>", parse_mode="HTML")

    tracker = {"stage": "parsing"}
    
    async def status_callback(stage, text, tracker_ref):
        await update_status_media_and_text(status_msg, stage, text, tracker_ref)

    try:
        result = await run_download_flow(url, status_callback, COBALT_INSTANCE, tracker)
        if not result:
            return

        media_files = result["media_files"]
        dl_dir = result["dl_dir"]
        official_thumb = result.get("official_thumb")
        width = result.get("width")
        height = result.get("height")
        duration = result.get("duration")
        tracker = result.get("tracker") or tracker
        performer = tracker.get("music_artist")
        title = tracker.get("music_title")
        
        display_url = tracker.get("original_url", url)
        final_safe_url = display_url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        caption = f"🔗 {final_safe_url}"
        
        if len(media_files) == 1:
            start_upload_time = time.time()
            upload_tracker = {"stage": "uploading"}
            await update_status_media_and_text(status_msg, "uploading", "🚀 <b>Локальный сервер загружает в Telegram...</b>\\n<i>Ожидайте, это может занять время для больших файлов.</i>", upload_tracker, force_media_update=True)
            upload_callback = await make_upload_callback(status_msg, start_upload_time, upload_tracker)
            try:
                log_info(f"Uploading single file {media_files[0]} to Telegram...")
                await send_media_file(
                    chat_id=message.chat.id,
                    file_path=media_files[0],
                    caption=caption,
                    reply_to=message.message_id,
                    progress_callback=upload_callback,
                    status_msg=status_msg,
                    width=width,
                    height=height,
                    duration=duration,
                    performer=performer,
                    title=title
                )
                log_info(f"Single file upload finished: {media_files[0]}")
            finally:
                upload_tracker["done"] = True
                if "task" in upload_tracker:
                    upload_tracker["task"].cancel()
        else:
            log_info(f"Uploading multiple files {media_files} to Telegram...")
            await update_status_media_and_text(status_msg, "uploading", "🚀 <b>Локальный сервер загружает в Telegram...</b>\\n<i>Ожидайте, это может занять время для больших файлов.</i>", tracker, force_media_update=True)
            await send_multiple_media(message.chat.id, media_files, caption=caption, reply_to=message.message_id)
            log_info("Multiple files upload finished.")
            try:
                await status_msg.delete()
            except Exception:
                pass
                
    except Exception as e:
        log_error("Exception in handle_message:", exc_info=True)
        safe_error = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        await edit_status_message(status_msg, f"❌ <b>Telegram вернул ошибку:</b> <code>{safe_error}</code>")
    finally:
        if 'result' in locals() and result and result.get("dl_dir"):
            log_info(f"Cleaning up directory: {result['dl_dir']}")
            shutil.rmtree(result["dl_dir"], ignore_errors=True)

async def main():
    try:
        try:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.get("http://127.0.0.1:8081", timeout=2) as resp:
                    print("ℹ️ Локальный сервер Telegram API доступен.")
        except Exception:
            print("⏳ Локальный API не отвечает. Пробуем поднять контейнер...")
            process = await asyncio.create_subprocess_shell("docker start tg-bot-api")
            await process.communicate()
            await asyncio.sleep(2)

        print("🤖 Бот запущен!")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
