import os
import re
import time
import traceback
import asyncio
import aiohttp
import uuid
import shutil
import glob
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

load_dotenv()

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALLOWED_USERS = [
    int(x.strip()) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()
]
LOCAL_TG_API = os.getenv("LOCAL_TG_API", "http://127.0.0.1:8081")
SEND_LINKS = os.getenv("SEND_LINKS", "True").lower() in ("true", "1", "yes")
# =================

session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_TG_API))
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()

def format_download_progress(line):
    """Превращает строчку прогресса yt-dlp в красивый прогресс-бар"""
    percent_match = re.search(r"(\d+(?:\.\d+)?)%", line)
    if not percent_match:
        return None
        
    percent = float(percent_match.group(1))
    
    total_match = re.search(r"of\s+([0-9\.]+(?:KiB|MiB|GiB|B|KB|MB|GB|iB))", line, re.IGNORECASE)
    total_size = total_match.group(1) if total_match else "Неизвестно"
    
    speed_match = re.search(r"at\s+([0-9\.]+(?:KiB|MiB|GiB|B|KB|MB|GB|iB)/s|Unknown speed)", line, re.IGNORECASE)
    speed = speed_match.group(1) if speed_match else "Неизвестная скорость"
    
    eta_match = re.search(r"(?:ETA|in)\s+([0-9:]+)", line)
    eta = eta_match.group(1) if eta_match else ""
    
    filled = min(20, int(percent / 5))
    bar = "█" * filled + "▒" * (20 - filled)
    
    total_size = total_size.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    speed = speed.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    eta = eta.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    eta_str = f" (ETA: <code>{eta}</code>)" if eta else ""
    
    return (
        f"📥 <b>Скачиваем с источника...</b>\n"
        f"<code>[{bar}] {percent:.1f}%</code>\n"
        f"📦 <code>Размер: {total_size}</code>\n"
        f"⚡️ <code>{speed}</code>{eta_str}"
    )

def clean_url(url):
    """Очистка ссылки от трекинговых параметров (si, igsh, igshid, utm_*, etc)"""
    if not url:
        return url
    try:
        parsed = urlparse(url)
        query_params = parse_qsl(parsed.query)
        cleaned_params = []
        for k, v in query_params:
            k_lower = k.lower()
            if k_lower in ('si', 'igsh', 'igshid', 'is_from_webapp', 'sender_device', 'feature', '_r', '_t'):
                continue
            if k_lower.startswith('utm_'):
                continue
            cleaned_params.append((k, v))
        new_query = urlencode(cleaned_params)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url

def extract_url(message: types.Message):
    """Вытаскиваем чистую ссылку из сообщения"""
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

async def send_media_file(chat_id, file_path, caption=None, reply_to=None):
    ext = os.path.splitext(file_path)[1].lower()
    input_file = FSInputFile(file_path)
    
    if ext in ('.mp4', '.mkv', '.mov', '.webm'):
        return await bot.send_video(chat_id=chat_id, video=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML")
    elif ext in ('.jpg', '.jpeg', '.png', '.webp'):
        return await bot.send_photo(chat_id=chat_id, photo=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML")
    elif ext in ('.mp3', '.m4a', '.ogg', '.wav', '.flac'):
        return await bot.send_audio(chat_id=chat_id, audio=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML")
    elif ext in ('.gif',):
        return await bot.send_animation(chat_id=chat_id, animation=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML")
    else:
        return await bot.send_document(chat_id=chat_id, document=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML")

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
            await bot.send_media_group(chat_id=chat_id, media=media_group.build(), reply_to_message_id=reply_to)
            
    for path in others:
        file_caption = caption if (not photos_videos and path == others[0]) else None
        await send_media_file(chat_id, path, caption=file_caption, reply_to=reply_to)

async def download_media_ytdl(message: types.Message, status_msg: types.Message, url: str):
    dl_dir = f"dl_{uuid.uuid4().hex}"
    os.makedirs(dl_dir, exist_ok=True)
        
    await status_msg.edit_text("📥 <b>Подключение к источнику...</b>", parse_mode="HTML")
    
    cmd = f'yt-dlp --newline -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" -o "{dl_dir}/%(id)s_%(autonumber)s.%(ext)s" "{url}"'
    
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    
    last_update = time.time()
    
    while True:
        line = await process.stdout.readline()
        if not line:
            break
            
        text_line = line.decode('utf-8', errors='ignore').strip()
        
        if "[download]" in text_line and "%" in text_line:
            now = time.time()
            if now - last_update >= 1.0:
                last_update = now
                progress_text = format_download_progress(text_line)
                if progress_text:
                    try:
                        await status_msg.edit_text(progress_text, parse_mode="HTML")
                    except Exception:
                        pass
                        
    await process.wait()
    
    files = glob.glob(f"{dl_dir}/*")
    if not files:
        shutil.rmtree(dl_dir, ignore_errors=True)
        return await status_msg.edit_text("❌ <b>Ошибка скачивания или нет медиа.</b>", parse_mode="HTML")
        
    await status_msg.edit_text("🚀 <b>Локальный сервер загружает в Telegram...</b>\n<i>Ожидайте, это может занять время для больших файлов.</i>", parse_mode="HTML")
    
    try:
        media_files = [f for f in files if not f.endswith(('.json', '.description', '.info'))]
        if not media_files:
            media_files = files
            
        safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        caption = f"🔗 {safe_url}" if SEND_LINKS else None
        
        if len(media_files) == 1:
            await send_media_file(message.chat.id, media_files[0], caption=caption, reply_to=message.message_id)
        else:
            await send_multiple_media(message.chat.id, media_files, caption=caption, reply_to=message.message_id)
            
        await status_msg.delete()
    except Exception as e:
        safe_error = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        await status_msg.edit_text(f"❌ <b>Telegram вернул ошибку:</b> <code>{safe_error}</code>", parse_mode="HTML")
    finally:
        shutil.rmtree(dl_dir, ignore_errors=True)

@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return

    url = extract_url(message)
    if not url:
        return

    safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    status_msg = await message.reply(f"⏳ <b>Парсим:</b> <code>{safe_url}</code>", parse_mode="HTML")

    await download_media_ytdl(message, status_msg, url)

async def main():
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

if __name__ == "__main__":
    asyncio.run(main())