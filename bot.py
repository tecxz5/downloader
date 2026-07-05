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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("UniDLBot")

def log_info(msg):
    logger.info(f"[UniDL] {msg}")
    print(f"[UniDL] [INFO] {msg}", flush=True)

def log_warning(msg):
    logger.warning(f"[UniDL] {msg}")
    print(f"[UniDL] [WARNING] {msg}", flush=True)

def log_error(msg, exc_info=None):
    if exc_info:
        logger.error(f"[UniDL] {msg}", exc_info=exc_info)
        import traceback
        print(f"[UniDL] [ERROR] {msg}\n{traceback.format_exc()}", flush=True)
    else:
        logger.error(f"[UniDL] {msg}")
        print(f"[UniDL] [ERROR] {msg}", flush=True)

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
    "twitter.com", "x.com", "vimeo.com", "vk.com", "vk.video"
)
# =================

session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_TG_API, is_local=False), timeout=3600)
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
    if tracker_dict is None:
        tracker_dict = {}
    
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
                await update_status_media_and_text(status_msg, "uploading", text, tracker_dict, only_text=True)
                
                if "task" not in tracker_dict:
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
                                await update_status_media_and_text(status_msg, "uploading", updated_text, tracker_dict, only_text=True)
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
                await update_status_media_and_text(status_msg, "uploading", text, tracker_dict, only_text=True)
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

async def check_youtube_track(url):
    # Checks if a YouTube URL is a music track
    if "music.youtube.com" in url:
        log_info("URL is from music.youtube.com, automatically identified as track.")
        return True

    domain = urlparse(url).netloc.lower()
    if not ("youtube.com" in domain or "youtu.be" in domain):
        return False

    log_info(f"Checking if YouTube video is a music track: {url}")
    cmd = f'yt-dlp --skip-download --dump-json --no-check-certificate "{url}"'
    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            data = json.loads(stdout.decode('utf-8', errors='ignore'))
            
            # Check categories
            categories = [c.lower() for c in data.get("categories", [])]
            log_info(f"YouTube video categories: {categories}")
            if "music" in categories:
                log_info("Identified as track via 'Music' category.")
                return True
            
            # Check if official track metadata is present
            track = data.get("track")
            artist = data.get("artist")
            if track or artist:
                log_info(f"Identified as track via official metadata: track={track}, artist={artist}")
                return True
            
            # Check title for keywords
            title = data.get("title", "").lower()
            uploader = data.get("uploader", "").lower()
            if " - topic" in uploader:
                log_info(f"Identified as track via uploader '{uploader}'")
                return True
        else:
            log_warning(f"Metadata extraction exited with code {process.returncode}")
    except Exception as e:
        log_error(f"Error checking YouTube track metadata: {e}", exc_info=True)
        
    return False

async def resolve_spotify_metadata(url):
    try:
        track_id = url.split("/track/")[-1].split("?")[0]
        embed_url = f"https://open.spotify.com/embed/track/{track_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        log_info(f"Resolving Spotify via embed: {embed_url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(embed_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>\s*({.*?})\s*</script>', html, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                        if entity:
                            title = entity.get("name") or entity.get("title")
                            artists = entity.get("artists", [])
                            artist_names = [a.get("name") for a in artists if a.get("name")]
                            if title and artist_names:
                                artist = ", ".join(artist_names)
                                log_info(f"Spotify resolved: {artist} - {title}")
                                return artist, title
                    log_warning(f"Spotify embed page did not contain track entity data")
                else:
                    log_warning(f"Spotify embed returned status {resp.status}")
    except Exception as e:
        log_warning(f"Error resolving Spotify metadata: {e}")
    return None, None

async def resolve_deezer_metadata(url):
    """Резолв метаданных Deezer через публичный API."""
    try:
        track_id = url.split("/track/")[-1].split("?")[0]
        api_url = f"https://api.deezer.com/track/{track_id}"
        log_info(f"Resolving Deezer track ID {track_id} via API: {api_url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    artist = data.get("artist", {}).get("name")
                    title = data.get("title")
                    if artist and title:
                        log_info(f"Deezer resolved: {artist} - {title}")
                        return artist, title
    except Exception as e:
        log_warning(f"Error resolving Deezer metadata: {e}")
    return None, None

def _slugify(text):
    """Превращает текст в URL-slug для сравнения."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"['\"'`\u201c\u201d]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")

async def resolve_apple_music_metadata(url):
    """Резолв метаданных Apple Music через serialized-server-data JSON."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        log_info(f"Resolving Apple Music URL: {url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    match = re.search(r'<script[^>]+id="serialized-server-data"[^>]*>\s*({.*?})\s*</script>', html, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        # Собираем все треки из JSON
                        tracks = []
                        def collect_tracks(d):
                            if isinstance(d, dict):
                                if "artistName" in d and ("title" in d or "name" in d):
                                    tracks.append(d)
                                for v in d.values():
                                    collect_tracks(v)
                            elif isinstance(d, list):
                                for v in d:
                                    collect_tracks(v)
                        collect_tracks(data)
                        
                        if not tracks:
                            log_warning("Apple Music: no tracks found in serialized-server-data")
                            return None, None
                        
                        # Пытаемся найти конкретный трек по slug из URL
                        url_path = urlparse(url).path.lower()
                        url_path_slugs = [_slugify(p) for p in url_path.split('/') if p]
                        
                        for track in tracks:
                            title = track.get("title") or track.get("name")
                            artist = track.get("artistName")
                            track_slug = _slugify(title)
                            if track_slug and any(track_slug in slug for slug in url_path_slugs):
                                log_info(f"Apple Music resolved via slug match: {artist} - {title}")
                                return artist, title
                        
                        # Fallback: первый трек из списка
                        first = tracks[0]
                        title = first.get("title") or first.get("name")
                        artist = first.get("artistName")
                        log_info(f"Apple Music resolved (first track fallback): {artist} - {title}")
                        return artist, title
    except Exception as e:
        log_warning(f"Error resolving Apple Music metadata: {e}")
    return None, None

async def resolve_tidal_metadata(url):
    """Резолв метаданных Tidal через oEmbed endpoint."""
    try:
        track_id = url.split("/track/")[-1].split("?")[0]
        # Tidal oEmbed: https://oembed.tidal.com/?url=https://tidal.com/track/{id}
        oembed_url = f"https://oembed.tidal.com/?url=https://tidal.com/track/{track_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        log_info(f"Resolving Tidal via oEmbed: {oembed_url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(oembed_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # oEmbed title обычно: "Track Name by Artist Name"
                    title_raw = data.get("title", "")
                    if title_raw and " by " in title_raw:
                        parts = title_raw.rsplit(" by ", 1)
                        song = parts[0].strip()
                        artist = parts[1].strip()
                        log_info(f"Tidal resolved via oEmbed: {artist} - {song}")
                        return artist, song
                    elif title_raw:
                        log_info(f"Tidal oEmbed title (no artist split): {title_raw}")
                        return None, title_raw
                else:
                    log_warning(f"Tidal oEmbed returned status {resp.status}")
    except Exception as e:
        log_warning(f"Error resolving Tidal metadata via oEmbed: {e}")
    return None, None

async def resolve_musicbrainz_metadata(url):
    """Резолв метаданных MusicBrainz через публичный API."""
    try:
        # Извлекаем MBID из URL: /recording/{uuid}
        mb_match = re.search(r'/recording/([0-9a-f-]{36})', url)
        if not mb_match:
            return None, None
        mbid = mb_match.group(1)
        api_url = f"https://musicbrainz.org/ws/2/recording/{mbid}?inc=artists&fmt=json"
        headers = {
            "User-Agent": "UniDLBot/1.0 (https://github.com/tecxz5/downloader)",
            "Accept": "application/json"
        }
        log_info(f"Resolving MusicBrainz recording {mbid} via API: {api_url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title = data.get("title")
                    artists = data.get("artist-credit", [])
                    artist_names = [a.get("artist", {}).get("name") for a in artists if a.get("artist", {}).get("name")]
                    if title and artist_names:
                        artist = ", ".join(artist_names)
                        log_info(f"MusicBrainz resolved: {artist} - {title}")
                        return artist, title
                else:
                    log_warning(f"MusicBrainz API returned status {resp.status}")
    except Exception as e:
        log_warning(f"Error resolving MusicBrainz metadata: {e}")
    return None, None

MUSIC_DOMAINS = ("spotify.com", "deezer.com", "music.apple.com", "tidal.com", "musicbrainz.org")

async def resolve_music_metadata(url):
    """Центральный роутер: определяет платформу по домену и вызывает соответствующий резолвер."""
    if not url:
        return None, None
    domain = urlparse(url).netloc.lower()
    if "spotify.com" in domain and "/track/" in url:
        return await resolve_spotify_metadata(url)
    elif "deezer.com" in domain and "/track/" in url:
        return await resolve_deezer_metadata(url)
    elif "music.apple.com" in domain and ("/album/" in url or "/song/" in url):
        return await resolve_apple_music_metadata(url)
    elif "tidal.com" in domain and "/track/" in url:
        return await resolve_tidal_metadata(url)
    elif "musicbrainz.org" in domain and "/recording/" in url:
        return await resolve_musicbrainz_metadata(url)
    return None, None

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

async def get_video_metadata(file_path):
    cmd = f'ffprobe -v error -select_streams v:0 -show_entries stream=width,height,duration -of json "{file_path}"'
    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            data = json.loads(stdout.decode('utf-8', errors='ignore'))
            if "streams" in data and len(data["streams"]) > 0:
                stream = data["streams"][0]
                width = stream.get("width")
                height = stream.get("height")
                duration_str = stream.get("duration")
                duration = None
                if duration_str:
                    try:
                        duration = int(float(duration_str))
                    except ValueError:
                        pass
                return width, height, duration
    except Exception as e:
        print(f"⚠️ Ошибка при извлечении метаданных через ffprobe: {e}")
    return None, None, None

async def process_official_thumbnail(existing_image_path):
    if not existing_image_path or not os.path.exists(existing_image_path):
        return None
        
    out_path = existing_image_path + ".thumb.jpg"
    cmd = f'ffmpeg -y -v error -i "{existing_image_path}" -vf "scale=\'if(gt(iw,ih),320,-1)\':\'if(gt(iw,ih),-1,320)\'" "{out_path}"'
    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        if process.returncode == 0 and os.path.exists(out_path):
            return out_path
    except Exception as e:
        print(f"⚠️ Ошибка при сжатии превью через ffmpeg: {e}")
    return None

async def edit_status_message(status_msg, text):
    try:
        if status_msg.photo or status_msg.document or status_msg.video or status_msg.animation:
            await status_msg.edit_caption(caption=text, parse_mode="HTML")
        else:
            await status_msg.edit_text(text, parse_mode="HTML")
    except Exception:
        pass

async def update_status_media_and_text(status_msg, stage_name, text, tracker, force_media_update=False):
    if "stage" not in tracker:
        tracker["stage"] = None
        
    if tracker["stage"] != stage_name:
        tracker["stage"] = stage_name
        force_media_update = True
        
    if force_media_update:
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

async def send_media_file(chat_id, file_path, caption=None, reply_to=None, progress_callback=None, status_msg=None, official_thumb_path=None):
    ext = os.path.splitext(file_path)[1].lower()
    input_file = ProgressFSInputFile(file_path, callback=progress_callback)
    
    width, height, duration = None, None, None
    thumbnail_input = None
    processed_thumb_path = None
    
    if ext in ('.mp4', '.mkv', '.mov', '.webm'):
        width, height, duration = await get_video_metadata(file_path)
        if official_thumb_path:
            processed_thumb_path = await process_official_thumbnail(official_thumb_path)
            if processed_thumb_path and os.path.exists(processed_thumb_path):
                thumbnail_input = FSInputFile(processed_thumb_path)
                
    try:
        edited = False
        if status_msg:
            try:
                if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                    media_obj = types.InputMediaVideo(
                        media=input_file,
                        caption=caption,
                        supports_streaming=True,
                        width=width,
                        height=height,
                        duration=duration,
                        thumbnail=thumbnail_input
                    )
                elif ext in ('.jpg', '.jpeg', '.png', '.webp'):
                    media_obj = types.InputMediaPhoto(media=input_file, caption=caption)
                elif ext in ('.mp3', '.m4a', '.ogg', '.wav', '.flac'):
                    media_obj = types.InputMediaAudio(media=input_file, caption=caption)
                elif ext in ('.gif',):
                    media_obj = types.InputMediaAnimation(media=input_file, caption=caption)
                else:
                    media_obj = types.InputMediaDocument(media=input_file, caption=caption)
                
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
                    thumbnail=thumbnail_input,
                    request_timeout=3600
                )
            elif ext in ('.jpg', '.jpeg', '.png', '.webp'):
                sent_msg = await bot.send_photo(chat_id=chat_id, photo=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
            elif ext in ('.mp3', '.m4a', '.ogg', '.wav', '.flac'):
                sent_msg = await bot.send_audio(chat_id=chat_id, audio=input_file, caption=caption, reply_to_message_id=reply_to, parse_mode="HTML", request_timeout=3600)
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
        if processed_thumb_path and os.path.exists(processed_thumb_path):
            try:
                os.remove(processed_thumb_path)
            except Exception:
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

async def download_media_ytdl(message: types.Message, status_msg: types.Message, url: str, tracker: dict):
    dl_dir = f"dl_{uuid.uuid4().hex}"
    os.makedirs(dl_dir, exist_ok=True)
    log_info(f"Created yt-dlp download directory: {dl_dir}")
        
    await update_status_media_and_text(status_msg, "downloading", "📥 <b>Подключение к источнику...</b>", tracker, force_media_update=True)
    
    cmd_base = (
        f'yt-dlp --newline --embed-metadata '
        f'--user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" '
        f'--no-check-certificate '
    )

    if "pornhub.com" in url or "rt.pornhub.com" in url:
        cmd_base += f'--impersonate chrome '
        
    if tracker.get("force_audio"):
        cmd_base += f'-f "bestaudio[ext=m4a]/bestaudio/best" -x --audio-format mp3 --embed-thumbnail '
    else:
        cmd_base += f'-f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" '
        cmd_base += f'--write-thumbnail --convert-thumbnails jpg '

    cmd_base += f'-o "{dl_dir}/%(id)s_%(autonumber)s.%(ext)s" "{url}"'
    
    log_info(f"Running yt-dlp command: {cmd_base}")
    
    process = await asyncio.create_subprocess_shell(
        cmd_base, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    
    last_update = time.time()
    
    while True:
        line = await process.stdout.readline()
        if not line:
            break
            
        text_line = line.decode('utf-8', errors='ignore').strip()
        log_info(f"yt-dlp stdout: {text_line}")
        
        if "[download]" in text_line and "%" in text_line:
            now = time.time()
            if now - last_update >= 1.0:
                last_update = now
                progress_text = format_download_progress(text_line)
                if progress_text:
                    await update_status_media_and_text(status_msg, "downloading", progress_text, tracker)
                        
    await process.wait()
    log_info(f"yt-dlp subprocess exited with return code {process.returncode}")
    
    files = glob.glob(f"{dl_dir}/*")
    log_info(f"Files found in yt-dlp download directory: {files}")
    if not files:
        shutil.rmtree(dl_dir, ignore_errors=True)
        stderr_data = await process.stderr.read()
        stderr_text = stderr_data.decode('utf-8', errors='ignore').strip()
        log_error(f"yt-dlp failed download. Full stderr:\n{stderr_text}")
        
        error_line = "Неизвестная ошибка скачивания"
        if stderr_text:
            for line in reversed(stderr_text.splitlines()):
                if "ERROR:" in line or "error" in line.lower():
                    error_line = line
                    break
            else:
                error_line = stderr_text.splitlines()[-1]
        
        raise Exception(error_line)
        
    await update_status_media_and_text(status_msg, "uploading", "🚀 <b>Локальный сервер загружает в Telegram...</b>\n<i>Ожидайте, это может занять время для больших файлов.</i>", tracker, force_media_update=True)
    
    try:
        # Исключаем файлы метаданных
        all_files = [f for f in files if not f.endswith(('.json', '.description', '.info'))]
        
        # Разделяем на видео, аудио и остальные файлы
        video_files = [f for f in all_files if os.path.splitext(f)[1].lower() in ('.mp4', '.mkv', '.mov', '.webm')]
        audio_files = [f for f in all_files if os.path.splitext(f)[1].lower() in ('.mp3', '.m4a', '.ogg', '.wav', '.flac')]
        
        # Если есть видео или аудио, то все файлы изображений в папке считаются превьюшками и исключаются из списка отправки
        if video_files or audio_files:
            image_extensions = ('.jpg', '.jpeg', '.png', '.webp')
            media_files = [f for f in all_files if not f.endswith(image_extensions)]
            official_thumb = next((f for f in all_files if f.endswith(image_extensions)), None)
        else:
            media_files = all_files
            official_thumb = None
            
        if not media_files:
            media_files = files
            
        log_info(f"Filtered media files for upload: {media_files}")
        display_url = tracker.get("original_url", url)
        safe_url = display_url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        caption = f"🔗 {safe_url}" if SEND_LINKS else None
        
        if len(media_files) == 1:
            start_upload_time = time.time()
            upload_tracker = {"stage": "uploading"}
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
                    official_thumb_path=official_thumb
                )
                log_info(f"Single file upload finished: {media_files[0]}")
            finally:
                if "task" in upload_tracker:
                    upload_tracker["task"].cancel()
        else:
            log_info(f"Uploading multiple files {media_files} to Telegram...")
            await send_multiple_media(message.chat.id, media_files, caption=caption, reply_to=message.message_id)
            log_info("Multiple files upload finished.")
            try:
                await status_msg.delete()
            except Exception:
                pass
    except Exception as e:
        log_error("Exception in uploading files downloaded by yt-dlp:", exc_info=True)
        safe_error = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        await edit_status_message(status_msg, f"❌ <b>Telegram вернул ошибку:</b> <code>{safe_error}</code>")
    finally:
        log_info(f"Cleaning up yt-dlp directory: {dl_dir}")
        shutil.rmtree(dl_dir, ignore_errors=True)

async def download_media_cobalt(message: types.Message, status_msg: types.Message, url: str, tracker: dict):
    dl_dir = f"dl_{uuid.uuid4().hex}"
    os.makedirs(dl_dir, exist_ok=True)
    log_info(f"Created Cobalt download directory: {dl_dir}")
    
    await update_status_media_and_text(status_msg, "parsing", "📥 <b>Обрабатываем через Cobalt API...</b>", tracker)
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    download_mode = "audio" if tracker.get("force_audio") else "auto"
    payload = {
        "url": url,
        "videoQuality": "1080",
        "audioFormat": "mp3",
        "downloadMode": download_mode,
        "filenameStyle": "classic"
    }
    
    log_info(f"Cobalt request payload: {json.dumps(payload)}")
    
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
            log_info(f"Posting request to Cobalt using curl_cffi: {api_url}")
            async with AsyncSession() as session:
                resp = await session.post(api_url, json=payload, headers=headers, impersonate="chrome")
                log_info(f"Cobalt response status: {resp.status_code}")
                log_info(f"Cobalt response headers: {dict(resp.headers)}")
                log_info(f"Cobalt response body: {resp.text}")
                if resp.status_code == 200:
                    data = resp.json()
                else:
                    raise Exception(f"Cobalt error: status {resp.status_code}")
        else:
            log_info(f"Posting request to Cobalt using aiohttp: {api_url}")
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post(api_url, json=payload, headers=headers) as resp:
                    resp_text = await resp.text()
                    log_info(f"Cobalt response status: {resp.status}")
                    log_info(f"Cobalt response headers: {dict(resp.headers)}")
                    log_info(f"Cobalt response body: {resp_text}")
                    data = json.loads(resp_text)
                    
        media_urls = []
        if data.get("status") == "picker":
            media_urls = [item["url"] for item in data.get("picker", [])]
        elif data.get("url"):
            media_urls = [data["url"]]
            
        if not media_urls:
            raise Exception(data.get("text") or "Не удалось получить ссылки от Cobalt")
            
        log_info(f"Parsed media URLs from Cobalt: {media_urls}")
        await update_status_media_and_text(status_msg, "downloading", f"📥 <b>Скачиваем {len(media_urls)} файлов...</b>", tracker, force_media_update=True)

        async def download_one(session_obj, m_url, idx):
            log_info(f"Downloading file {idx+1}/{len(media_urls)} from: {m_url}")
            if use_curl:
                resp_ctx = session_obj.stream("GET", m_url, impersonate="chrome")
            else:
                resp_ctx = session_obj.get(m_url)

            async with resp_ctx as resp:
                status_code = resp.status_code if use_curl else resp.status
                headers_dict = dict(resp.headers)
                log_info(f"Download stream response status: {status_code}")
                log_info(f"Download stream response headers: {headers_dict}")
                if status_code != 200:
                    log_error(f"Failed to download stream: status {status_code}")
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
                    if tracker.get("force_audio"):
                        clean_filename = os.path.splitext(clean_filename)[0] + ".mp3"
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
                        
                    if "soundcloud.com" in url or "snd.sc" in url or tracker.get("force_audio"):
                        ext = '.mp3'
                        
                    file_path = os.path.join(dl_dir, f"file_{idx}{ext}")
                
                try:
                    total_size = int(resp.headers.get('Content-Length', 0))
                except Exception:
                    total_size = 0
                log_info(f"Target file path: {file_path}. Total size: {total_size} bytes.")
                    
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
                                log_info(f"Chunk progress (curl): {downloaded}/{total_size} bytes downloaded ({speed:.1f} MB/s)")
                                
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
                                await update_status_media_and_text(status_msg, "downloading", text, tracker)
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
                                log_info(f"Chunk progress (aiohttp): {downloaded}/{total_size} bytes downloaded ({speed:.1f} MB/s)")
                                
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
                                await update_status_media_and_text(status_msg, "downloading", text, tracker)
                log_info(f"Finished downloading {file_path}. Total downloaded: {downloaded} bytes.")
                if downloaded == 0:
                    log_warning(f"File {file_path} is empty, removing it.")
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass
                    return False
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
        log_info(f"Files found in download directory: {files}")
        for f in list(files):
            if os.path.exists(f) and os.path.getsize(f) == 0:
                try:
                    log_info(f"Removing 0-byte file: {f}")
                    os.remove(f)
                except Exception as e:
                    log_error(f"Failed to remove empty file {f}: {e}")
                    pass
        files = glob.glob(f"{dl_dir}/*")
        log_info(f"Active files for upload: {files}")
        if not files:
            raise Exception("Файлы не скачались")
            
        await update_status_media_and_text(status_msg, "uploading", "🚀 <b>Локальный сервер загружает в Telegram...</b>", tracker, force_media_update=True)
        
        safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        caption = f"🔗 {safe_url}" if SEND_LINKS else None
        
        if len(files) == 1:
            start_upload_time = time.time()
            upload_tracker = {"stage": "uploading"}
            upload_callback = await make_upload_callback(status_msg, start_upload_time, upload_tracker)
            try:
                log_info(f"Uploading single file {files[0]} to Telegram...")
                await send_media_file(message.chat.id, files[0], caption=caption, reply_to=message.message_id, progress_callback=upload_callback, status_msg=status_msg)
                log_info(f"Single file upload finished: {files[0]}")
            finally:
                if "task" in upload_tracker:
                    upload_tracker["task"].cancel()
        else:
            log_info(f"Uploading multiple files {files} to Telegram...")
            await send_multiple_media(message.chat.id, files, caption=caption, reply_to=message.message_id)
            log_info("Multiple files upload finished.")
            try:
                await status_msg.delete()
            except Exception:
                pass
    except Exception as e:
        log_error("Exception in download_media_cobalt:", exc_info=True)
        raise e
    finally:
        log_info(f"Cleaning up Cobalt directory: {dl_dir}")
        shutil.rmtree(dl_dir, ignore_errors=True)

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

    tracker = {
        "stage": "parsing"
    }

    # === Проверяем музыкальные ссылки (Spotify, Deezer, Apple Music, Tidal, MusicBrainz) ===
    domain = urlparse(url).netloc.lower()
    is_music_link = any(d in domain for d in MUSIC_DOMAINS)
    if is_music_link:
        log_info(f"Detected music link from domain: {domain}")
        try:
            await update_status_media_and_text(status_msg, "parsing", "🎵 <b>Определяем трек...</b>", tracker)
            artist, title = await resolve_music_metadata(url)
            if artist and title:
                log_info(f"Music metadata resolved: {artist} - {title}")
                search_query = f"ytsearch1:{artist} - {title}"
                tracker["force_audio"] = True
                tracker["original_url"] = url
                await update_status_media_and_text(status_msg, "parsing", f"🎵 <b>Нашли:</b> {artist} — {title}\n<i>Ищем на YouTube...</i>", tracker)
                try:
                    await download_media_ytdl(message, status_msg, search_query, tracker)
                except Exception as yt_err:
                    err_msg = str(yt_err)
                    safe_error = err_msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    await update_status_media_and_text(status_msg, "downloading", f"❌ <b>Не удалось скачать трек:</b>\n<code>{safe_error}</code>", tracker)
                return
            else:
                log_warning(f"Could not resolve music metadata for {url}")
                await update_status_media_and_text(status_msg, "parsing", "⚠️ <b>Не удалось определить трек, пробуем скачать напрямую...</b>", tracker)
        except Exception as e:
            log_warning(f"Music resolver error: {e}")

    # Check if YouTube url is a track
    is_track = await check_youtube_track(url)
    if is_track:
        tracker["force_audio"] = True

    use_cobalt = any(d in domain for d in COBALT_SUPPORTED_DOMAINS)

    if use_cobalt:
        try:
            await download_media_cobalt(message, status_msg, url, tracker)
        except Exception as e:
            log_warning(f"Cobalt failed for {url}: {e}. Falling back to yt-dlp.")
            try:
                await update_status_media_and_text(status_msg, "parsing", "⏳ <b>Cobalt не справился, пробуем альтернативный метод (yt-dlp)...</b>", tracker)
            except Exception:
                pass
            try:
                await download_media_ytdl(message, status_msg, url, tracker)
            except Exception as ytdl_err:
                err_msg = str(ytdl_err)
                if "drm protected" in err_msg.lower() or "drm" in err_msg.lower():
                    await update_status_media_and_text(status_msg, "downloading", "❌ <b>Медиа не скачать, оно под DRM</b>", tracker)
                else:
                    safe_error = err_msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    await update_status_media_and_text(status_msg, "downloading", f"❌ <b>yt-dlp вернул ошибку:</b>\n<code>{safe_error}</code>", tracker)
    else:
        try:
            await download_media_ytdl(message, status_msg, url, tracker)
        except Exception as ytdl_err:
            err_msg = str(ytdl_err)
            if "drm protected" in err_msg.lower() or "drm" in err_msg.lower():
                await update_status_media_and_text(status_msg, "downloading", "❌ <b>Медиа не скачать, оно под DRM</b>", tracker)
            else:
                safe_error = err_msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                await update_status_media_and_text(status_msg, "downloading", f"❌ <b>yt-dlp вернул ошибку:</b>\n<code>{safe_error}</code>", tracker)

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