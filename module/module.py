# meta developer: @tecxz5
# meta dependencies: curl-cffi telethon-tgcrypto
import os
import io
import re
import time
import json
import asyncio
import shutil
import uuid
import glob
import logging
from telethon.tl.types import MessageEntityUrl, MessageEntityTextUrl, DocumentAttributeVideo, DocumentAttributeAudio, DocumentAttributeFilename
from .. import loader, utils
import aiohttp
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, unquote

logger = logging.getLogger(__name__)

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

from telethon import utils as telethon_utils
from telethon.tl.alltlobjects import LAYER
from telethon.tl.functions import InvokeWithLayerRequest
from telethon.tl.functions.auth import ExportAuthorizationRequest, ImportAuthorizationRequest
from telethon.tl.functions.upload import SaveFilePartRequest, SaveBigFilePartRequest
from telethon.tl.types import InputFileBig, InputFile
from telethon.network import MTProtoSender

import os
import re
import time
import json
import asyncio
import aiohttp
import uuid
import shutil
import glob
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, unquote
import logging

logger = logging.getLogger("UniDLCore")

def log_info(msg):
    logger.info(f"[UniDL] {msg}")

def log_warning(msg):
    logger.warning(f"[UniDL] {msg}")

def log_error(msg, exc_info=None):
    logger.error(f"[UniDL] {msg}", exc_info=exc_info)

COBALT_SUPPORTED_DOMAINS = (
    "bilibili.com", "instagram.com", "pinterest.com", "pin.it",
    "reddit.com", "rutube.ru", "snapchat.com", "soundcloud.com",
    "streamable.com", "tiktok.com", "tumblr.com", "twitch.tv",
    "twitter.com", "x.com", "vimeo.com", "vk.com", "vk.video"
)

MUSIC_DOMAINS = ("spotify.com", "deezer.com", "music.apple.com", "tidal.com", "musicbrainz.org")

def clean_url(url):
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

def _slugify(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"['\"'`\u201c\u201d]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")

async def resolve_spotify_metadata(url):
    try:
        track_id = url.split("/track/")[-1].split("?")[0]
        embed_url = f"https://open.spotify.com/embed/track/{track_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
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
                                return ", ".join(artist_names), title
    except Exception as e:
        log_warning(f"Error resolving Spotify metadata: {e}")
    return None, None

async def resolve_deezer_metadata(url):
    try:
        track_id = url.split("/track/")[-1].split("?")[0]
        api_url = f"https://api.deezer.com/track/{track_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    artist = data.get("artist", {}).get("name")
                    title = data.get("title")
                    if artist and title:
                        return artist, title
    except Exception as e:
        log_warning(f"Error resolving Deezer metadata: {e}")
    return None, None

async def resolve_apple_music_metadata(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    match = re.search(r'<script[^>]+id="serialized-server-data"[^>]*>\s*({.*?})\s*</script>', html, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
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
                            return None, None
                        url_path = urlparse(url).path.lower()
                        url_path_slugs = [_slugify(p) for p in url_path.split('/') if p]
                        for track in tracks:
                            title = track.get("title") or track.get("name")
                            artist = track.get("artistName")
                            track_slug = _slugify(title)
                            if track_slug and any(track_slug in slug for slug in url_path_slugs):
                                return artist, title
                        first = tracks[0]
                        return first.get("artistName"), first.get("title") or first.get("name")
    except Exception as e:
        log_warning(f"Error resolving Apple Music metadata: {e}")
    return None, None

async def resolve_tidal_metadata(url):
    try:
        track_id = url.split("/track/")[-1].split("?")[0]
        oembed_url = f"https://oembed.tidal.com/?url=https://tidal.com/track/{track_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(oembed_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title_raw = data.get("title", "")
                    if title_raw and " by " in title_raw:
                        parts = title_raw.rsplit(" by ", 1)
                        return parts[1].strip(), parts[0].strip()
                    elif title_raw:
                        return None, title_raw
    except Exception as e:
        log_warning(f"Error resolving Tidal metadata: {e}")
    return None, None

async def resolve_musicbrainz_metadata(url):
    try:
        mb_match = re.search(r'/recording/([0-9a-f-]{36})', url)
        if not mb_match:
            return None, None
        mbid = mb_match.group(1)
        api_url = f"https://musicbrainz.org/ws/2/recording/{mbid}?inc=artists&fmt=json"
        headers = {
            "User-Agent": "UniDLBot/1.0 (https://github.com/tecxz5/downloader)",
            "Accept": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title = data.get("title")
                    artists = data.get("artist-credit", [])
                    artist_names = [a.get("artist", {}).get("name") for a in artists if a.get("artist", {}).get("name")]
                    if title and artist_names:
                        return ", ".join(artist_names), title
    except Exception as e:
        log_warning(f"Error resolving MusicBrainz metadata: {e}")
    return None, None

async def resolve_music_metadata(url):
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

async def check_youtube_track(url):
    if "music.youtube.com" in url:
        return True
    domain = urlparse(url).netloc.lower()
    if not ("youtube.com" in domain or "youtu.be" in domain):
        return False
    cmd = f'yt-dlp --skip-download --dump-json --no-check-certificate "{url}"'
    try:
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            data = json.loads(stdout.decode('utf-8', errors='ignore'))
            categories = [c.lower() for c in data.get("categories", [])]
            uploader = data.get("uploader", "")
            if not uploader:
                uploader = ""
            if "music" in categories or data.get("track") or data.get("artist") or " - topic" in uploader.lower():
                return True
    except Exception as e:
        log_warning(f"Error checking YouTube track metadata: {e}")
    return False

def format_download_progress(line):
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

async def download_url_ytdl(url, dl_dir, force_audio, status_callback):
    await status_callback("downloading", "📥 <b>Подключение к источнику...</b>")
    cmd_base = (
        f'yt-dlp --newline --embed-metadata --write-thumbnail --concurrent-fragments 10 '
        f'--user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" '
        f'--no-check-certificate '
    )
    if "pornhub.com" in url or "rt.pornhub.com" in url:
        cmd_base += f'--impersonate chrome '
    if force_audio:
        cmd_base += f'-f "bestaudio[ext=m4a]/bestaudio/best" -x --audio-format mp3 '
    else:
        cmd_base += f'-f "b[ext=mp4]/b/best" '
        
    cmd_base += f'-o "{dl_dir}/%(id)s_%(autonumber)s.%(ext)s" "{url}"'
    log_info(f"Running yt-dlp: {cmd_base}")
    process = await asyncio.create_subprocess_shell(
        cmd_base, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
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
                    await status_callback("downloading", progress_text)
    await process.wait()
    if process.returncode != 0:
        stderr_data = await process.stderr.read()
        stderr_text = stderr_data.decode('utf-8', errors='ignore').strip()
        log_error(f"yt-dlp failed: {stderr_text}")
        error_line = "Неизвестная ошибка скачивания"
        if stderr_text:
            for line in reversed(stderr_text.splitlines()):
                if "ERROR:" in line or "error" in line.lower():
                    error_line = line
                    break
            else:
                error_line = stderr_text.splitlines()[-1]
        raise Exception(error_line)

async def download_url_cobalt(url, dl_dir, force_audio, status_callback, cobalt_instance):
    await status_callback("parsing", "⏳ <b>Обрабатываем через Cobalt API...</b>")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = {
        "url": url,
        "videoQuality": "1080",
        "audioFormat": "mp3",
        "downloadMode": "audio" if force_audio else "auto",
        "filenameStyle": "classic"
    }
    
    use_curl = False
    try:
        from curl_cffi.requests import AsyncSession
        use_curl = True
    except ImportError:
        pass

    data = None
    api_url = cobalt_instance
    if not api_url.endswith('/'):
        api_url += '/'

    if use_curl:
        async with AsyncSession() as session:
            resp = await session.post(api_url, json=payload, headers=headers, impersonate="chrome")
            if resp.status_code == 200:
                data = resp.json()
            else:
                raise Exception(f"Cobalt error (status {resp.status_code}): {resp.text}")
    else:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                body_text = await resp.text()
                if resp.status == 200:
                    data = json.loads(body_text)
                else:
                    raise Exception(f"Cobalt error (status {resp.status}): {body_text}")

    media_urls = []
    if data.get("status") == "picker":
        media_urls = [item["url"] for item in data.get("picker", [])]
    elif data.get("url"):
        media_urls = [data["url"]]
    if not media_urls:
        raise Exception(data.get("text") or "Не удалось получить ссылки от Cobalt")

    await status_callback("downloading", f"📥 <b>Скачиваем {len(media_urls)} файлов...</b>")

    async def download_one(session_obj, m_url, idx):
        resp_ctx = session_obj.stream("GET", m_url, impersonate="chrome") if use_curl else session_obj.get(m_url)
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
                clean_filename = re.sub(r'[\\/*?:"<>|]', "", filename)
                file_path = os.path.join(dl_dir, clean_filename)
            else:
                content_type = resp.headers.get('Content-Type', '')
                ext = '.mp4'
                if 'image' in content_type: ext = '.jpg'
                elif 'audio' in content_type: ext = '.mp3'
                elif '.jpg' in m_url: ext = '.jpg'
                if "soundcloud.com" in url or "snd.sc" in url or force_audio:
                    ext = '.mp3'
                file_path = os.path.join(dl_dir, f"file_{idx}{ext}")
            
            try:
                total_size = int(resp.headers.get('Content-Length', 0))
            except Exception:
                total_size = 0
            
            downloaded = 0
            start_time = None
            last_update = 0.0
            last_bytes = 0
            
            import aiofiles
            async with aiofiles.open(file_path, 'wb') as f:
                if use_curl:
                    async for chunk in resp.aiter_content():
                        await f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if start_time is None:
                            start_time = now
                            last_update = now
                            last_bytes = downloaded
                            continue
                        if now - last_update >= 1.0 or (total_size > 0 and downloaded == total_size):
                            elapsed = now - last_update
                            bytes_sent = downloaded - last_bytes
                            speed = (bytes_sent / 1048576) / elapsed if elapsed > 0 else 0
                            last_update = now
                            last_bytes = downloaded
                            cur_mb = downloaded / 1048576
                            file_info = f" (файл {idx+1}/{len(media_urls)})" if len(media_urls) > 1 else ""
                            if total_size > 0:
                                percent = (downloaded * 100 / total_size)
                                bar = "█" * min(20, int(percent / 5)) + "▒" * (20 - min(20, int(percent / 5)))
                                text = (
                                    f"📥 <b>Скачиваем с источника...</b>{file_info}\n"
                                    f"<code>[{bar}] {percent:.1f}%</code>\n"
                                    f"📦 <code>{cur_mb:.1f} / {total_size / 1048576:.1f} MB</code>\n"
                                    f"⚡️ <code>{speed:.1f} MB/s</code>"
                                )
                            else:
                                text = (
                                    f"📥 <b>Скачиваем с источника...</b>{file_info}\n"
                                    f"📦 <code>Скачано: {cur_mb:.1f} MB</code>\n"
                                    f"⚡️ <code>{speed:.1f} MB/s</code>"
                                )
                            await status_callback("downloading", text)
                else:
                    while True:
                        chunk = await resp.content.read(65536)
                        if not chunk:
                            break
                        await f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if start_time is None:
                            start_time = now
                            last_update = now
                            last_bytes = downloaded
                            continue
                        if now - last_update >= 1.0 or (total_size > 0 and downloaded == total_size):
                            elapsed = now - last_update
                            bytes_sent = downloaded - last_bytes
                            speed = (bytes_sent / 1048576) / elapsed if elapsed > 0 else 0
                            last_update = now
                            last_bytes = downloaded
                            cur_mb = downloaded / 1048576
                            file_info = f" (файл {idx+1}/{len(media_urls)})" if len(media_urls) > 1 else ""
                            if total_size > 0:
                                percent = (downloaded * 100 / total_size)
                                bar = "█" * min(20, int(percent / 5)) + "▒" * (20 - min(20, int(percent / 5)))
                                text = (
                                    f"📥 <b>Скачиваем с источника...</b>{file_info}\n"
                                    f"<code>[{bar}] {percent:.1f}%</code>\n"
                                    f"📦 <code>{cur_mb:.1f} / {total_size / 1048576:.1f} MB</code>\n"
                                    f"⚡️ <code>{speed:.1f} MB/s</code>"
                                )
                            else:
                                text = (
                                    f"📥 <b>Скачиваем с источника...</b>{file_info}\n"
                                    f"📦 <code>Скачано: {cur_mb:.1f} MB</code>\n"
                                    f"⚡️ <code>{speed:.1f} MB/s</code>"
                                )
                            await status_callback("downloading", text)
            if downloaded == 0 and os.path.exists(file_path):
                try: os.remove(file_path)
                except Exception: pass

    if use_curl:
        async with AsyncSession() as session:
            for i, m_url in enumerate(media_urls):
                await download_one(session, m_url, i)
    else:
        async with aiohttp.ClientSession() as session:
            for i, m_url in enumerate(media_urls):
                await download_one(session, m_url, i)

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
        log_warning(f"Error checking video metadata via ffprobe: {e}")
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
        log_warning(f"Error resizing thumbnail via ffmpeg: {e}")
    return None

async def generate_thumbnail_from_video(video_path):
    out_path = video_path + ".thumb.jpg"
    cmd = f'ffmpeg -y -v error -ss 00:00:01 -i "{video_path}" -vframes 1 -vf "scale=\'if(gt(iw,ih),320,-1)\':\'if(gt(iw,ih),-1,320)\'" "{out_path}"'
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
        log_warning(f"Error generating thumbnail via ffmpeg: {e}")
    return None

async def _postprocess_audio(filepath, tracker, dl_dir):
    artist = tracker.get("music_artist", "")
    title = tracker.get("music_title", "")
    if not artist and not title:
        return
    log_info(f"Post-processing audio: artist='{artist}', title='{title}', file='{filepath}'")
    thumb_path = None
    for ext in ('.jpg', '.jpeg', '.png', '.webp'):
        candidates = glob.glob(f"{dl_dir}/*{ext}")
        if candidates:
            thumb_path = candidates[0]
            break
    resized_thumb = None
    if thumb_path:
        resized_thumb = os.path.join(dl_dir, "_cover_768.jpg")
        crop_cmd = (
            f'ffmpeg -y -i "{thumb_path}" '
            f'-vf "crop=min(iw\\,ih):min(iw\\,ih),scale=768:768" '
            f'-q:v 2 "{resized_thumb}"'
        )
        proc = await asyncio.create_subprocess_shell(
            crop_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.wait()
        if proc.returncode != 0 or not os.path.exists(resized_thumb):
            resized_thumb = None
    tmp_out = filepath + ".tagged.mp3"
    if resized_thumb:
        meta_cmd = (
            f'ffmpeg -y -i "{filepath}" -i "{resized_thumb}" '
            f'-map 0:a -map 1:v -c:a copy -c:v mjpeg '
            f'-disposition:v attached_pic '
        )
    else:
        meta_cmd = f'ffmpeg -y -i "{filepath}" -c copy '
    if artist:
        safe_artist = artist.replace('"', '\\"')
        meta_cmd += f'-metadata artist="{safe_artist}" -metadata album_artist="{safe_artist}" '
    if title:
        safe_title = title.replace('"', '\\"')
        meta_cmd += f'-metadata title="{safe_title}" '
    meta_cmd += f'-id3v2_version 3 "{tmp_out}"'
    proc = await asyncio.create_subprocess_shell(
        meta_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.wait()
    if proc.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
        os.replace(tmp_out, filepath)
    else:
        if os.path.exists(tmp_out):
            try: os.remove(tmp_out)
            except Exception: pass
    if resized_thumb and os.path.exists(resized_thumb):
        try: os.remove(resized_thumb)
        except Exception: pass

async def run_download_flow(url, status_callback, cobalt_instance, tracker=None):
    if tracker is None:
        tracker = {}
        
    url = clean_url(url)
    tracker["original_url"] = url
    domain = urlparse(url).netloc.lower()
    
    is_music_link = any(d in domain for d in MUSIC_DOMAINS)
    if is_music_link:
        log_info(f"Detected music link from domain: {domain}")
        try:
            await status_callback("parsing", "🎵 <b>Определяем трек...</b>", tracker)
            artist, title = await resolve_music_metadata(url)
            if artist and title:
                log_info(f"Music metadata resolved: {artist} - {title}")
                url = f"ytsearch1:{artist} - {title}"
                tracker["force_audio"] = True
                tracker["music_artist"] = artist
                tracker["music_title"] = title
                await status_callback("parsing", f"🎵 <b>Нашли:</b> {artist} — {title}\\n<i>Ищем на YouTube...</i>", tracker)
            else:
                log_warning(f"Could not resolve music metadata for {url}")
                await status_callback("parsing", "⚠️ <b>Не удалось определить трек, пробуем скачать напрямую...</b>", tracker)
        except Exception as e:
            log_warning(f"Music resolver error: {e}")

    if await check_youtube_track(url):
        tracker["force_audio"] = True

    dl_dir = f"dl_{uuid.uuid4().hex}"
    os.makedirs(dl_dir, exist_ok=True)
    log_info(f"Created download directory: {dl_dir}")
    
    download_success = False
    use_cobalt = any(d in urlparse(url).netloc.lower() for d in COBALT_SUPPORTED_DOMAINS)

    if use_cobalt:
        try:
            await download_url_cobalt(url, dl_dir, tracker.get("force_audio"), lambda stage, text: status_callback(stage, text, tracker), cobalt_instance)
            download_success = True
        except Exception as e:
            log_warning(f"Cobalt failed for {url}: {e}. Falling back to yt-dlp.")
            try:
                await status_callback("parsing", "⏳ <b>Cobalt не справился, пробуем альтернативный метод (yt-dlp)...</b>", tracker)
            except Exception:
                pass
            
    if not download_success:
        try:
            await download_url_ytdl(url, dl_dir, tracker.get("force_audio"), lambda stage, text: status_callback(stage, text, tracker))
            download_success = True
        except Exception as e:
            shutil.rmtree(dl_dir, ignore_errors=True)
            err_msg = str(e)
            if "drm protected" in err_msg.lower() or "drm" in err_msg.lower():
                await status_callback("downloading", "❌ <b>Медиа не скачать, оно под DRM</b>", tracker)
            else:
                safe_error = err_msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                await status_callback("downloading", f"❌ <b>yt-dlp вернул ошибку:</b>\\n<code>{safe_error}</code>", tracker)
            return None
            
    files = glob.glob(f"{dl_dir}/*")
    for f in list(files):
        if os.path.exists(f) and os.path.getsize(f) == 0:
            try:
                os.remove(f)
            except Exception:
                pass
                
    files = glob.glob(f"{dl_dir}/*")
    if not files:
        shutil.rmtree(dl_dir, ignore_errors=True)
        await status_callback("downloading", "❌ <b>Файлы не скачались (папка пуста)</b>", tracker)
        return None
        
    if tracker.get("force_audio") and (tracker.get("music_artist") or tracker.get("music_title")):
        audio_files_to_tag = [f for f in files if os.path.splitext(f)[1].lower() in ('.mp3', '.m4a', '.ogg', '.flac')]
        for af in audio_files_to_tag:
            try:
                await _postprocess_audio(af, tracker, dl_dir)
            except Exception as tag_err:
                log_warning(f"Audio post-processing failed for {af}: {tag_err}")
        files = glob.glob(f"{dl_dir}/*")

    await status_callback("processing", "⚙️ <b>Обработка медиа...</b>", tracker)
    
    all_files = [f for f in files if not f.endswith(('.json', '.description', '.info'))]
    video_files = [f for f in all_files if os.path.splitext(f)[1].lower() in ('.mp4', '.mkv', '.mov', '.webm')]
    audio_files = [f for f in all_files if os.path.splitext(f)[1].lower() in ('.mp3', '.m4a', '.ogg', '.wav', '.flac')]
    
    if video_files or audio_files:
        image_extensions = ('.jpg', '.jpeg', '.png', '.webp')
        media_files = [f for f in all_files if not f.endswith(image_extensions)]
        official_thumb = next((f for f in all_files if f.endswith(image_extensions)), None)
    else:
        media_files = all_files
        official_thumb = None
        
    if not media_files:
        media_files = files
        
    width, height, duration = None, None, None
    processed_thumb_path = None
    
    if len(media_files) == 1:
        ext = os.path.splitext(media_files[0])[1].lower()
        if ext in ('.mp4', '.mkv', '.mov', '.webm'):
            width, height, duration = await get_video_metadata(media_files[0])
            if official_thumb:
                processed_thumb_path = await process_official_thumbnail(official_thumb)
            else:
                processed_thumb_path = await generate_thumbnail_from_video(media_files[0])
                
    return {
        "media_files": media_files,
        "official_thumb": processed_thumb_path,
        "width": width,
        "height": height,
        "duration": duration,
        "dl_dir": dl_dir,
        "force_audio": tracker.get("force_audio", False),
        "tracker": tracker
    }


class ParallelUploadTransferrer:
    def __init__(self, client, connection_count: int = 4) -> None:
        self.client = client
        self.loop = client.loop
        self.dc_id = client.session.dc_id
        self.auth_key = client.session.auth_key
        self.senders = []
        self.connection_count = connection_count

    async def _create_sender(self) -> MTProtoSender:
        dc = await self.client._get_dc(self.dc_id)
        sender = MTProtoSender(self.auth_key, loggers=self.client._log)
        await sender.connect(self.client._connection(dc.ip_address, dc.port, dc.id,
                                                     loggers=self.client._log,
                                                     proxy=self.client._proxy))
        if not self.auth_key:
            auth = await self.client(ExportAuthorizationRequest(self.dc_id))
            self.client._init_request.query = ImportAuthorizationRequest(id=auth.id, bytes=auth.bytes)
            req = InvokeWithLayerRequest(LAYER, self.client._init_request)
            await sender.send(req)
            self.auth_key = sender.auth_key
        return sender

    async def init_upload(self) -> None:
        if self.auth_key:
            self.senders = await asyncio.gather(*[
                self._create_sender()
                for _ in range(self.connection_count)
            ])
        else:
            first = await self._create_sender()
            self.senders = [
                first,
                *await asyncio.gather(*[
                    self._create_sender()
                    for _ in range(1, self.connection_count)
                ])
            ]

    async def finish_upload(self) -> None:
        await asyncio.gather(*[sender.disconnect() for sender in self.senders])
        self.senders = []

@loader.tds
class UniversalDLMod(loader.Module):
    """Универсальный скачиватель (yt-dlp) с риалтайм скоростью"""
    
    strings = {"name": "UniDL"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            "SEND_LINKS", True, "Прикреплять ссылку на источник",
            "COBALT_INSTANCE", "http://127.0.0.1:9000/", "URL вашего инстанса Cobalt"
        )

    def _extract_url(self, message):
        """Парсинг ссылок через ядро Telethon"""
        if not message:
            return None
            
        if hasattr(message, 'get_entities_text'):
            try:
                for ent, text in message.get_entities_text():
                    if isinstance(ent, MessageEntityTextUrl):
                        return ent.url.strip() 
                    elif isinstance(ent, MessageEntityUrl):
                        return text.strip() 
            except:
                pass

        text = getattr(message, 'raw_text', getattr(message, 'text', ''))
        if not text:
            text = getattr(message, 'caption', '')
            
        if text:
            match = re.search(r"(https?://[^\s]+)", text)
            if match:
                url = match.group(1).strip()
                while url and url[-1] in ".,!?;:\"')}]>":
                    url = url[:-1]
                return url
        return None

    def _format_progress(self, action, current, total, start_time, inst_speed=None):
        cur_mb = current / 1048576
        if inst_speed is not None:
            speed = inst_speed
        else:
            elapsed = time.time() - start_time
            speed = cur_mb / elapsed if elapsed > 0 else 0
        
        if total and total > 0:
            tot_mb = total / 1048576
            percent = current * 100 / total
            filled = min(20, int(percent / 5))
            bar = "█" * filled + "▒" * (20 - filled)
            return (
                f"{action}\n"
                f"<code>[{bar}] {percent:.1f}%</code>\n"
                f"📦 <code>{cur_mb:.1f} / {tot_mb:.1f} MB</code>\n"
                f"⚡️ <code>{speed:.1f} MB/s</code>"
            )
        else:
            return (
                f"{action}\n"
                f"📦 <code>Скачано: {cur_mb:.1f} MB</code>\n"
                f"⚡️ <code>{speed:.1f} MB/s</code>"
            )

    def _clean_url(self, url):
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

    async def _preheat_keep_alive(self, client):
        import random
        from telethon.tl.functions import PingRequest
        while hasattr(self, '_uploader') and self._uploader and self._uploader.senders:
            senders = self._uploader.senders
            if not senders:
                break
            async def ping_one(s):
                try:
                    ping_id = random.randint(0, 2**31 - 1)
                    future = s.send(PingRequest(ping_id=ping_id))
                    await asyncio.wait_for(future, timeout=3.0)
                except Exception as ex:
                    log_warning(f"Keep-alive ping failed for a preheated connection: {ex}")
                    
            await asyncio.gather(*[ping_one(sender) for sender in senders])
            await asyncio.sleep(5)

    async def _preheat_upload(self, client):
        try:
            self._uploader = ParallelUploadTransferrer(client, connection_count=16)
            await self._uploader.init_upload()
            self._preheat_ping_task = asyncio.create_task(self._preheat_keep_alive(client))
        except Exception as e:
            log_error(f"Failed to preheat upload connections: {e}")
            self._uploader = None

    async def _fast_upload(self, client, file_path, progress_callback=None):
        import os
        import asyncio
        from telethon import helpers
        from telethon.tl.types import InputFileBig
        from telethon.tl.functions.upload import SaveBigFilePartRequest, SaveFilePartRequest

        file_size = os.path.getsize(file_path)
        
        if file_size < 10 * 1024 * 1024:
            if hasattr(self, '_uploader') and self._uploader:
                await self._uploader.finish_upload()
                self._uploader = None
            return await client.upload_file(file_path, part_size_kb=512, progress_callback=progress_callback)
            
        file_id = helpers.generate_random_long()
        
        if hasattr(self, '_upload_preheat_task') and self._upload_preheat_task:
            await self._upload_preheat_task
            self._upload_preheat_task = None
            
        if hasattr(self, '_preheat_ping_task') and self._preheat_ping_task:
            self._preheat_ping_task.cancel()
            self._preheat_ping_task = None
            
        if hasattr(self, '_uploader') and self._uploader and self._uploader.senders:
            uploader = self._uploader
            connection_count = len(uploader.senders)
            self._uploader = None
        else:
            connection_count = 16
            uploader = ParallelUploadTransferrer(client, connection_count=connection_count)
            await uploader.init_upload()
        
        part_size_kb = telethon_utils.get_appropriated_part_size(file_size)
        part_size = part_size_kb * 1024
        part_count = (file_size + part_size - 1) // part_size
        is_large = file_size > 10 * 1024 * 1024
        
        uploaded_size = [0]
        queue = asyncio.Queue(maxsize=connection_count * 2)
        
        async def upload_worker(sender):
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    break
                part_index, part_data = item
                
                if is_large:
                    req = SaveBigFilePartRequest(file_id, part_index, part_count, part_data)
                else:
                    req = SaveFilePartRequest(file_id, part_index, part_data)
                    
                for attempt in range(5):
                    try:
                        await client._call(sender, req)
                        break
                    except Exception as ex:
                        log_warning(f"Upload part {part_index} failed (attempt {attempt+1}): {ex}")
                        if attempt == 4:
                            raise ex
                        await asyncio.sleep(1)
                        
                uploaded_size[0] += len(part_data)
                if progress_callback:
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(uploaded_size[0], file_size)
                    else:
                        progress_callback(uploaded_size[0], file_size)
                queue.task_done()

        workers = []
        for sender in uploader.senders:
            workers.append(asyncio.create_task(upload_worker(sender)))
            
        with open(file_path, 'rb') as f:
            for i in range(part_count):
                chunk = f.read(part_size)
                if not chunk:
                    break
                await queue.put((i, chunk))
                
        await queue.join()
        
        for _ in range(len(uploader.senders)):
            await queue.put(None)
        await asyncio.gather(*workers)
        
        await uploader.finish_upload()
        
        name = os.path.basename(file_path)
        return InputFileBig(id=file_id, parts=part_count, name=name)

    async def _update_status_media_and_text(self, status_msg, stage_name, text, tracker, force_media_update=False):
        if "stage" not in tracker:
            tracker["stage"] = None
            
        if tracker["stage"] != stage_name:
            tracker["stage"] = stage_name
            
        try:
            if hasattr(status_msg, 'edit'):
                try:
                    await status_msg.edit(text)
                except TypeError:
                    await status_msg.edit(text=text)
            else:
                await utils.answer(status_msg, text)
        except Exception:
            pass

    async def dlcmd(self, message):
        """<ссылка> или реплей - Скачать видео/фото"""
        await self._run_download(message)

    async def _run_download(self, message):
        args = utils.get_args_raw(message)
        url = None
        reply = await message.get_reply_message()
        reply_to = message.reply_to_msg_id

        if args:
            match = re.search(r"(https?://[^\s]+)", args)
            if match:
                url = match.group(1).strip()
                while url and url[-1] in ".,!?;:\"')}]>":
                    url = url[:-1]

        if not url and reply:
            url = self._extract_url(reply)

        if not url:
            return await utils.answer(message, "❌ <b>Ссылка не найдена.</b>")

        url = self._clean_url(url)
        safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        status_msg = await utils.answer(message, f"⏳ <b>Парсим:</b> <code>{safe_url}</code>")
            
        try:
            self._uploader = None
            self._upload_preheat_task = asyncio.create_task(self._preheat_upload(message.client))
            
            tracker = {"stage": "parsing", "client": message.client, "chat_id": message.chat_id}
            
            async def status_callback(stage, text, tracker_ref):
                await self._update_status_media_and_text(status_msg, stage, text, tracker_ref)

            cobalt_instance = self.config["COBALT_INSTANCE"]
            result = await run_download_flow(url, status_callback, cobalt_instance, tracker)
            
            if not result:
                return

            media_files = result["media_files"]
            official_thumb = result.get("official_thumb")
            width = result.get("width")
            height = result.get("height")
            duration = result.get("duration")
            
            caption = f"🔗 {safe_url}" if self.config["SEND_LINKS"] else None

            if len(media_files) == 1:
                start_upload_time = time.time()
                upload_tracker = {"stage": "uploading"}
                await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Локальный сервер загружает в Telegram...</b>\n<i>Ожидайте, это может занять время для больших файлов.</i>", upload_tracker, force_media_update=True)
                
                last_upload_update = 0
                def upload_progress(current, total):
                    nonlocal last_upload_update
                    now = time.time()
                    if now - last_upload_update >= 2.0:
                        last_upload_update = now
                        progress_text = self._format_progress("🚀 <b>Отправка в Telegram...</b>", current, total, start_upload_time)
                        asyncio.create_task(self._update_status_media_and_text(status_msg, "uploading", progress_text, upload_tracker))

                try:
                    uploaded_file = await self._fast_upload(message.client, media_files[0], progress_callback=upload_progress)
                    
                    thumb_to_upload = None
                    if official_thumb and os.path.exists(official_thumb):
                        thumb_to_upload = await message.client.upload_file(official_thumb)

                    attributes = []
                    ext = os.path.splitext(media_files[0])[1].lower()
                    if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                        vid_attr = DocumentAttributeVideo(0, 0, 0)
                        if duration: vid_attr.duration = duration
                        if width: vid_attr.w = width
                        if height: vid_attr.h = height
                        attributes.append(vid_attr)
                        attributes.append(DocumentAttributeFilename(file_name=os.path.basename(media_files[0])))
                    elif ext in ('.mp3', '.m4a', '.ogg', '.flac'):
                        audio_attr = DocumentAttributeAudio(duration=0, voice=False, title="", performer="")
                        attributes.append(audio_attr)
                        attributes.append(DocumentAttributeFilename(file_name=os.path.basename(media_files[0])))
                    
                    await message.client.send_file(
                        message.chat_id,
                        uploaded_file,
                        caption=caption,
                        reply_to=reply_to or message.id,
                        thumb=thumb_to_upload,
                        attributes=attributes,
                        force_document=False
                    )
                finally:
                    pass
            else:
                await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Локальный сервер загружает в Telegram...</b>\n<i>Ожидайте, это может занять время для больших файлов.</i>", tracker, force_media_update=True)
                await message.client.send_file(
                    message.chat_id,
                    media_files,
                    caption=caption,
                    reply_to=reply_to or message.id
                )
            
            try:
                await status_msg.delete()
            except Exception:
                pass

        except Exception as e:
            log_error("Exception in _run_download:", exc_info=True)
            safe_error = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            try:
                await self._update_status_media_and_text(status_msg, "error", f"❌ <b>Telegram вернул ошибку:</b> <code>{safe_error}</code>", tracker)
            except Exception:
                pass
        finally:
            if 'result' in locals() and result and result.get("dl_dir"):
                log_info(f"Cleaning up directory: {result['dl_dir']}")
                shutil.rmtree(result["dl_dir"], ignore_errors=True)
            if hasattr(self, '_preheat_ping_task') and self._preheat_ping_task:
                self._preheat_ping_task.cancel()
                self._preheat_ping_task = None
            if hasattr(self, '_upload_preheat_task') and self._upload_preheat_task:
                self._upload_preheat_task.cancel()
                self._upload_preheat_task = None
            if hasattr(self, '_uploader') and self._uploader:
                try:
                    await self._uploader.finish_upload()
                except Exception:
                    pass
                self._uploader = None
