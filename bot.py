import os
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

COBALT_INSTANCE = os.getenv("COBALT_INSTANCE", "http://127.0.0.1:9000/")

COBALT_SUPPORTED_DOMAINS = (
    "bilibili.com", "instagram.com", "pinterest.com", "pin.it",
    "reddit.com", "rutube.ru", "snapchat.com", "soundcloud.com",
    "streamable.com", "tiktok.com", "tumblr.com", "twitch.tv",
    "twitter.com", "x.com", "vimeo.com", "vk.com", "vk.video",
    "vine.co", "youtube.com", "youtu.be"
)
# =================

session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_TG_API, is_local=True), timeout=3600)
bot = Bot(token=BOT_TOKEN, session=session)
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
    
    async def callback(current, total):
        now = time.time()
        if now - last_update[0] >= 1.5 or current == total:
            last_update[0] = now
            
            percent = (current * 100 / total) if total > 0 else 0
            filled = min(20, int(percent / 5))
            bar = "█" * filled + "▒" * (20 - filled)
            
            cur_mb = current / 1048576
            tot_mb = total / 1048576
            elapsed = now - start_time
            speed = cur_mb / elapsed if elapsed > 0 else 0
            
            if current == total:
                text = (
                    f"🚀 <b>Файл передан на локальный сервер!</b>\n"
                    f"<code>[{bar}] {percent:.1f}%</code>\n"
                    f"⏳ <b>Отправка из локального сервера в Telegram...</b>\n"
                    f"<i>Ожидаем ответа от серверов Telegram: 0 сек</i>"
                )
                try:
                    await status_msg.edit_text(text, parse_mode="HTML")
                except Exception:
                    pass
                
                if tracker_dict is not None and "task" not in tracker_dict:
                    async def update_timer():
                        t_start = time.time()
                        try:
                            while True:
                                await asyncio.sleep(2)
                                elapsed_sec = int(time.time() - t_start)
                                updated_text = (
                                    f"🚀 <b>Файл передан на локальный сервер!</b>\n"
                                    f"<code>[{bar}] {percent:.1f}%</code>\n"
                                    f"⏳ <b>Отправка из локального сервера в Telegram...</b>\n"
                                    f"<i>Ожидаем ответа от серверов Telegram: {elapsed_sec} сек</i>"
                                )
                                try:
                                    await status_msg.edit_text(updated_text, parse_mode="HTML")
                                except Exception:
                                    pass
                        except asyncio.CancelledError:
                            pass
                    tracker_dict["task"] = asyncio.create_task(update_timer())
            else:
                text = (
                    f"🚀 <b>Загружаем в Telegram...</b>\n"
                    f"<code>[{bar}] {percent:.1f}%</code>\n"
                    f"📦 <code>{cur_mb:.1f} / {tot_mb:.1f} MB</code>\n"
                    f"⚡️ <code>{speed:.1f} MB/s</code>"
                )
                try:
                    await status_msg.edit_text(text, parse_mode="HTML")
                except Exception:
                    pass
    return callback

def format_download_progress(line):
    """Превращает строчку прогресса yt-dlp в красивый прогресс-бар"""
    percent_match = re.search(r"(\d+(?:\.\d+)?)%", line)
    if not percent_match:
        return None
        
    percent = float(percent_match.group(1))
    
    total_match = re.search(r"of\s+~?\s*([0-9\.]+\s*[a-zA-Z]+)", line, re.IGNORECASE)
    total_size = total_match.group(1) if total_match else "Неизвестно"
    
    speed_match = re.search(r"at\s+([0-9\.]+\s*[a-zA-Z]+/s|Unknown speed)", line, re.IGNORECASE)
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
            if k_lower in ('si', 'igsh', 'igshid', 'is_from_webapp', 'sender_device', 'feature', '_r', '_t', 'in'):
                continue
            if k_lower.startswith('utm_'):
                continue
            cleaned_params.append((k, v))
        new_query = unquote(urlencode(cleaned_params))
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

async def send_media_file(chat_id, file_path, caption=None, reply_to=None, progress_callback=None):
    ext = os.path.splitext(file_path)[1].lower()
    input_file = ProgressFSInputFile(file_path, callback=progress_callback)
    
    if ext in ('.mp4', '.mkv', '.mov', '.webm'):
        return await bot.send_video(chat_id=chat_id, video=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
    elif ext in ('.jpg', '.jpeg', '.png', '.webp'):
        return await bot.send_photo(chat_id=chat_id, photo=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
    elif ext in ('.mp3', '.m4a', '.ogg', '.wav', '.flac'):
        return await bot.send_audio(chat_id=chat_id, audio=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
    elif ext in ('.gif',):
        return await bot.send_animation(chat_id=chat_id, animation=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
    else:
        return await bot.send_document(chat_id=chat_id, document=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)

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

async def download_media_ytdl(message: types.Message, status_msg: types.Message, url: str):
    dl_dir = f"dl_{uuid.uuid4().hex}"
    os.makedirs(dl_dir, exist_ok=True)
        
    await status_msg.edit_text("📥 <b>Подключение к источнику...</b>", parse_mode="HTML")
    
    cmd_base = (
        f'yt-dlp --newline --embed-metadata '
        f'--user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" '
        f'--no-check-certificate '
    )

    if "pornhub.com" in url or "rt.pornhub.com" in url:
        cmd_base += f'--impersonate chrome '
        
    cmd_base += f'-f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" '
    cmd_base += f'-o "{dl_dir}/%(id)s_%(autonumber)s.%(ext)s" "{url}"'
    
    cmd = cmd_base
    
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
            start_upload_time = time.time()
            tracker = {}
            upload_callback = await make_upload_callback(status_msg, start_upload_time, tracker)
            try:
                await send_media_file(message.chat.id, media_files[0], caption=caption, reply_to=message.message_id, progress_callback=upload_callback)
            finally:
                if "task" in tracker:
                    tracker["task"].cancel()
        else:
            await send_multiple_media(message.chat.id, media_files, caption=caption, reply_to=message.message_id)
            
        await status_msg.delete()
    except Exception as e:
        safe_error = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        await status_msg.edit_text(f"❌ <b>Telegram вернул ошибку:</b> <code>{safe_error}</code>", parse_mode="HTML")
    finally:
        shutil.rmtree(dl_dir, ignore_errors=True)

async def download_media_cobalt(message: types.Message, status_msg: types.Message, url: str):
    dl_dir = f"dl_{uuid.uuid4().hex}"
    os.makedirs(dl_dir, exist_ok=True)
    
    await status_msg.edit_text("📥 <b>Обрабатываем через Cobalt API...</b>", parse_mode="HTML")
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "videoQuality": "1080",
        "audioFormat": "mp3",
        "downloadMode": "auto",
        "filenameStyle": "classic"
    }
    
    try:
        api_url = COBALT_INSTANCE
        if not api_url.endswith('/'):
            api_url += '/'
            
        use_curl = False
        try:
            from curl_cffi.requests import AsyncSession
            use_curl = True
        except ImportError:
            pass

        data = None
        if use_curl:
            async with AsyncSession() as session:
                resp = await session.post(api_url, json=payload, headers=headers, impersonate="chrome")
                if resp.status_code == 200:
                    data = resp.json()
                else:
                    raise Exception(f"Cobalt error: status {resp.status_code}")
        else:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post(api_url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    
        media_urls = []
        if data.get("status") == "picker":
            media_urls = [item["url"] for item in data.get("picker", [])]
        elif data.get("url"):
            media_urls = [data["url"]]
            
        if not media_urls:
            raise Exception(data.get("text") or "Не удалось получить ссылки от Cobalt")
            
        await status_msg.edit_text(f"📥 <b>Скачиваем {len(media_urls)} файлов...</b>", parse_mode="HTML")

        async def download_one(session_obj, m_url, idx):
            if use_curl:
                resp_ctx = session_obj.stream("GET", m_url, impersonate="chrome")
            else:
                resp_ctx = session_obj.get(m_url)

            async with resp_ctx as resp:
                status_code = resp.status_code if use_curl else resp.status
                if status_code != 200:
                    return False

                cd = resp.headers.get('Content-Disposition', '')
                filename = None
                filename_match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";\n\r]+)"?', cd, re.IGNORECASE)
                if filename_match:
                    filename = unquote(filename_match.group(1)).strip('"\'')
                    
                if filename:
                    ext = os.path.splitext(filename)[1].lower()
                    # Strip any invalid filesystem characters
                    clean_filename = re.sub(r'[\\/*?:"<>|]', "", filename)
                    file_path = os.path.join(dl_dir, clean_filename)
                else:
                    content_type = resp.headers.get('Content-Type', '')
                    ext = '.mp4'
                    if 'image' in content_type:
                        ext = '.jpg'
                    elif 'audio' in content_type:
                        ext = '.mp3'
                    elif '.jpg' in m_url:
                        ext = '.jpg'
                        
                    if "soundcloud.com" in url or "snd.sc" in url:
                        ext = '.mp3'
                        
                    file_path = os.path.join(dl_dir, f"file_{idx}{ext}")
                
                try:
                    total_size = int(resp.headers.get('Content-Length', 0))
                except Exception:
                    total_size = 0
                    
                downloaded = 0
                start_time = time.time()
                last_update = 0.0
                
                async with aiofiles.open(file_path, 'wb') as f:
                    if use_curl:
                        async for chunk in resp.aiter_content():
                            await f.write(chunk)
                            downloaded += len(chunk)
                            now = time.time()
                            if now - last_update >= 1.5 or (total_size > 0 and downloaded == total_size):
                                last_update = now
                                cur_mb = downloaded / 1048576
                                elapsed = now - start_time
                                speed = cur_mb / elapsed if elapsed > 0 else 0
                                
                                file_info = f" (файл {idx+1}/{len(media_urls)})" if len(media_urls) > 1 else ""
                                
                                if total_size > 0:
                                    percent = (downloaded * 100 / total_size)
                                    filled = min(20, int(percent / 5))
                                    bar = "█" * filled + "▒" * (20 - filled)
                                    tot_mb = total_size / 1048576
                                    text = (
                                        f"📥 <b>Скачиваем с источника...</b>{file_info}\n"
                                        f"<code>[{bar}] {percent:.1f}%</code>\n"
                                        f"📦 <code>{cur_mb:.1f} / {tot_mb:.1f} MB</code>\n"
                                        f"⚡️ <code>{speed:.1f} MB/s</code>"
                                    )
                                else:
                                    text = (
                                        f"📥 <b>Скачиваем с источника...</b>{file_info}\n"
                                        f"📦 <code>Скачано: {cur_mb:.1f} MB</code>\n"
                                        f"⚡️ <code>{speed:.1f} MB/s</code>"
                                    )
                                try:
                                    await status_msg.edit_text(text, parse_mode="HTML")
                                except Exception:
                                    pass
                    else:
                        while True:
                            chunk = await resp.content.read(65536)
                            if not chunk:
                                break
                            await f.write(chunk)
                            downloaded += len(chunk)
                            now = time.time()
                            if now - last_update >= 1.5 or (total_size > 0 and downloaded == total_size):
                                last_update = now
                                cur_mb = downloaded / 1048576
                                elapsed = now - start_time
                                speed = cur_mb / elapsed if elapsed > 0 else 0
                                
                                file_info = f" (файл {idx+1}/{len(media_urls)})" if len(media_urls) > 1 else ""
                                
                                if total_size > 0:
                                    percent = (downloaded * 100 / total_size)
                                    filled = min(20, int(percent / 5))
                                    bar = "█" * filled + "▒" * (20 - filled)
                                    tot_mb = total_size / 1048576
                                    text = (
                                        f"📥 <b>Скачиваем с источника...</b>{file_info}\n"
                                        f"<code>[{bar}] {percent:.1f}%</code>\n"
                                        f"📦 <code>{cur_mb:.1f} / {tot_mb:.1f} MB</code>\n"
                                        f"⚡️ <code>{speed:.1f} MB/s</code>"
                                    )
                                else:
                                    text = (
                                        f"📥 <b>Скачиваем с источника...</b>{file_info}\n"
                                        f"📦 <code>Скачано: {cur_mb:.1f} MB</code>\n"
                                        f"⚡️ <code>{speed:.1f} MB/s</code>"
                                    )
                                try:
                                    await status_msg.edit_text(text, parse_mode="HTML")
                                except Exception:
                                    pass
                return True

        if use_curl:
            async with AsyncSession() as session:
                for i, m_url in enumerate(media_urls):
                    await download_one(session, m_url, i)
        else:
            async with aiohttp.ClientSession() as http_session:
                for i, m_url in enumerate(media_urls):
                    await download_one(http_session, m_url, i)
                    
        files = glob.glob(f"{dl_dir}/*")
        if not files:
            raise Exception("Файлы не скачались")
            
        await status_msg.edit_text("🚀 <b>Локальный сервер загружает в Telegram...</b>", parse_mode="HTML")
        
        safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        caption = f"🔗 {safe_url}" if SEND_LINKS else None
        
        if len(files) == 1:
            start_upload_time = time.time()
            tracker = {}
            upload_callback = await make_upload_callback(status_msg, start_upload_time, tracker)
            try:
                await send_media_file(message.chat.id, files[0], caption=caption, reply_to=message.message_id, progress_callback=upload_callback)
            finally:
                if "task" in tracker:
                    tracker["task"].cancel()
        else:
            await send_multiple_media(message.chat.id, files, caption=caption, reply_to=message.message_id)
            
        await status_msg.delete()
    except Exception as e:
        raise e
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

    domain = urlparse(url).netloc.lower()
    use_cobalt = any(d in domain for d in COBALT_SUPPORTED_DOMAINS)

    if use_cobalt:
        try:
            await download_media_cobalt(message, status_msg, url)
        except Exception as e:
            # Логируем ошибку в консоль
            print(f"⚠️ Cobalt failed for {url}: {e}. Falling back to yt-dlp.")
            try:
                await status_msg.edit_text("⏳ <b>Cobalt не справился, пробуем альтернативный метод (yt-dlp)...</b>", parse_mode="HTML")
            except Exception:
                pass
            await download_media_ytdl(message, status_msg, url)
    else:
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