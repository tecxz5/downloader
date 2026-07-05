# meta developer: @tecxz5
# meta dependencies: curl-cffi
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
from telethon.tl.types import MessageEntityUrl, MessageEntityTextUrl, DocumentAttributeVideo
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

# === ANIMATED GIFS CONFIGURATION ===


COBALT_SUPPORTED_DOMAINS = (
    "bilibili.com", "instagram.com", "pinterest.com", "pin.it",
    "reddit.com", "rutube.ru", "snapchat.com", "soundcloud.com",
    "streamable.com", "tiktok.com", "tumblr.com", "twitch.tv",
    "twitter.com", "x.com", "vimeo.com", "vk.com", "vk.video"
)

@loader.tds
class UniversalDLMod(loader.Module):
    """Универсальный скачиватель (yt-dlp) с риалтайм скоростью"""
    
    strings = {"name": "UniDL"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            "SEND_LINKS", True, "Прикреплять ссылку на источник",
            "COBALT_INSTANCE", "http://127.0.0.1:9000/", "URL вашего инстанса Cobalt",
            "GIF_PARSING", "https://raw.githubusercontent.com/tecxz5/downloader/module/assets/parsing.gif", "GIF для стадии парсинга",
            "GIF_DOWNLOADING", "https://raw.githubusercontent.com/tecxz5/downloader/module/assets/downloading.gif", "GIF для стадии скачивания",
            "GIF_UPLOADING", "https://raw.githubusercontent.com/tecxz5/downloader/module/assets/uploading.gif", "GIF для стадии загрузки"
        )
        self._gif_cache = {}

    async def _get_video_metadata(self, file_path):
        import json
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

    def _format_progress(self, action, current, total, start_time):
        """Отрисовка прогресс-бара с умной проверкой размера"""
        cur_mb = current / 1048576
        elapsed = time.time() - start_time
        speed = cur_mb / elapsed if elapsed > 0 else 0
        
        # Если сервер отдал полный размер файла
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
        # Если качаем стримом (размер неизвестен)
        else:
            return (
                f"{action}\n"
                f"📦 <code>Скачано: {cur_mb:.1f} MB</code>\n"
                f"⚡️ <code>{speed:.1f} MB/s</code>"
            )

    def _format_download_progress(self, line):
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

    def _clean_url(self, url):
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

    async def _get_gif_data(self, url, stage_name):
        if not url:
            return None
        import io
        if url in self._gif_cache:
            bio = io.BytesIO(self._gif_cache[url])
            bio.name = f"{stage_name}.gif"
            return bio
        try:
            data = None
            if url.startswith(("http://", "https://")):
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
            elif os.path.exists(url):
                with open(url, "rb") as f:
                    data = f.read()
            if data:
                self._gif_cache[url] = data
                bio = io.BytesIO(data)
                bio.name = f"{stage_name}.gif"
                return bio
        except Exception as e:
            print(f"⚠️ Ошибка загрузки GIF с {url}: {e}")
        return None

    async def _update_status_media_and_text(self, status_msg, stage_name, text, tracker, force_media_update=False):
        if "stage" not in tracker:
            tracker["stage"] = None
            
        if tracker["stage"] != stage_name:
            tracker["stage"] = stage_name
            force_media_update = True
            
        use_inline = tracker.get("use_inline", False)
        
        if use_inline:
            gif_url = None
            if force_media_update:
                if stage_name == "parsing":
                    gif_url = self.config["GIF_PARSING"]
                elif stage_name == "downloading":
                    gif_url = self.config["GIF_DOWNLOADING"]
                elif stage_name == "uploading":
                    gif_url = self.config["GIF_UPLOADING"]
            try:
                if gif_url:
                    await status_msg.edit(text=text, gif=gif_url)
                else:
                    await status_msg.edit(text=text)
                return
            except Exception as e:
                print(f"⚠️ Не удалось обновить инлайн-форму: {e}")
                pass
                
        # Обычный текстовый режим (без гифок, чтобы не засорять вкладку)
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
        """<ссылка> или реплей - Скачать видео/фото (обычный текстовый режим)"""
        log_info(f"Command .dl called by user {message.sender_id} in chat {message.chat_id}")
        await self._run_download(message, use_inline=False)

    async def dlicmd(self, message):
        """<ссылка> или реплей - Скачать видео/фото (инлайн-режим с гифками)"""
        log_info(f"Command .dli called by user {message.sender_id} in chat {message.chat_id}")
        await self._run_download(message, use_inline=True)

    async def _run_download(self, message, use_inline):
        args = utils.get_args_raw(message)
        url = None
        reply = await message.get_reply_message()

        log_info(f"Processing download request: raw_args={args!r}, has_reply={reply is not None}")

        if args:
            match = re.search(r"(https?://[^\s]+)", args)
            if match:
                url = match.group(1).strip()
                while url and url[-1] in ".,!?;:\"')}]>":
                    url = url[:-1]
                log_info(f"Extracted URL from arguments: {url}")

        if not url and reply:
            url = self._extract_url(reply)
            log_info(f"Extracted URL from reply message: {url}")

        if not url:
            log_warning("No URL found in request arguments or reply message")
            return await utils.answer(message, "❌ <b>Ссылка не найдена.</b>")

        url = self._clean_url(url)
        safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        log_info(f"Cleaned and sanitized URL: {url}")
        
        status_msg = None
        if use_inline:
            # Удаляем триггерное сообщение только в инлайн-режиме, так как инлайн-форма шлется отдельно
            if message.out:
                try:
                    log_info("Deleting trigger message for inline form mode")
                    await message.delete()
                except Exception as e:
                    log_warning(f"Failed to delete trigger message: {e}")
                    pass
            try:
                log_info("Initializing inline form...")
                status_msg = await self.inline.form(
                    text=f"⏳ <b>Парсим:</b> <code>{safe_url}</code>",
                    message=message,
                    gif=self.config["GIF_PARSING"]
                )
                log_info(f"Inline form initialized: {status_msg}")
            except Exception as e:
                log_error("Failed to start inline form, switching to standard text mode", exc_info=True)
                use_inline = False
                
        if not use_inline:
            # В обычном режиме НЕ удаляем триггерное сообщение, а редактируем его in-place (всегда одно сообщение)
            log_info("Using standard text status message...")
            status_msg = await utils.answer(message, f"⏳ <b>Парсим:</b> <code>{safe_url}</code>")
            log_info(f"Standard status message initialized: {status_msg}")
            
        tracker = {"stage": "parsing", "use_inline": use_inline, "client": message.client, "chat_id": message.chat_id}
        await self._download_media(status_msg, url, safe_url, tracker, reply_to=message.reply_to_msg_id)

    async def _download_media(self, status_msg, url, safe_url, tracker, reply_to=None):
        domain = urlparse(url).netloc.lower()
        use_cobalt = any(d in domain for d in COBALT_SUPPORTED_DOMAINS)
        log_info(f"Target domain: {domain}, use_cobalt decided: {use_cobalt}")

        if use_cobalt:
            try:
                log_info(f"Delegating to Cobalt downloader for url: {url}")
                await self._download_media_cobalt(status_msg, url, safe_url, tracker, reply_to)
            except Exception as e:
                log_error(f"Cobalt failed for {url}, falling back to yt-dlp", exc_info=True)
                try:
                    await self._update_status_media_and_text(status_msg, "parsing", "⏳ <b>Cobalt не справился, пробуем альтернативный метод (yt-dlp)...</b>", tracker)
                except Exception:
                    pass
                await self._download_media_ytdl(status_msg, url, safe_url, tracker, reply_to)
        else:
            log_info(f"Delegating directly to yt-dlp downloader for url: {url}")
            await self._download_media_ytdl(status_msg, url, safe_url, tracker, reply_to)

    async def _download_media_ytdl(self, status_msg, url, safe_url, tracker, reply_to=None):
        dl_dir = f"dl_{uuid.uuid4().hex}"
        os.makedirs(dl_dir, exist_ok=True)
        log_info(f"Created yt-dlp download directory: {dl_dir}")
            
        await self._update_status_media_and_text(status_msg, "downloading", "📥 <b>Подключение к источнику...</b>", tracker, force_media_update=True)
        
        cmd_base = (
            f'yt-dlp --newline --embed-metadata '
            f'--user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" '
            f'--no-check-certificate '
        )

        if "pornhub.com" in url or "rt.pornhub.com" in url:
            cmd_base += f'--impersonate chrome '
            
        cmd_base += f'-f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" '
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
                    progress_text = self._format_download_progress(text_line)
                    if progress_text:
                        try:
                            await self._update_status_media_and_text(status_msg, "downloading", progress_text, tracker)
                        except Exception:
                            pass
                            
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
            
            safe_error = error_line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            return await self._update_status_media_and_text(status_msg, "downloading", f"❌ <b>yt-dlp вернул ошибку:</b>\n<code>{safe_error}</code>", tracker)
            
        await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Загружаем в Telegram...</b>", tracker, force_media_update=True)
        
        start_time = time.time()
        last_update = [0]
        tracker["stage"] = "uploading"
        
        async def upload_progress(current, total):
            now = time.time()
            if now - last_update[0] >= 1.5 or current == total:
                last_update[0] = now
                text = self._format_progress("🚀 <b>Загружаем в Telegram...</b>", current, total, start_time)
                log_info(f"Telegram upload progress: {current}/{total} bytes ({current/total*100:.1f}%)")
                try:
                    await self._update_status_media_and_text(status_msg, "uploading", text, tracker)
                except Exception:
                    pass

        try:
            media_files = [f for f in files if not f.endswith(('.json', '.description', '.info'))]
            if not media_files:
                media_files = files
            log_info(f"Filtered media files for upload: {media_files}")
                
            caption = f"🔗 {safe_url}" if self.config["SEND_LINKS"] else ""
            
            client = tracker.get("client")
            use_inline = tracker.get("use_inline", False)
            
            if len(media_files) == 1:
                file_path = media_files[0]
                attributes = []
                
                ext = os.path.splitext(file_path)[1].lower()
                log_info(f"Uploading single file. Extension: '{ext}'")
                if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                    try:
                        log_info("Extracting video metadata using ffprobe...")
                        width, height, duration = await self._get_video_metadata(file_path)
                        log_info(f"Video metadata: width={width}, height={height}, duration={duration}")
                        if width and height and duration:
                            attributes.append(DocumentAttributeVideo(
                                duration=duration,
                                w=width,
                                h=height,
                                supports_streaming=True
                            ))
                    except Exception as e:
                        log_warning(f"Failed to extract video attributes: {e}")
                
                log_info(f"Uploading file {file_path} to Telegram...")
                uploaded_file = await client.upload_file(file_path, progress_callback=upload_progress)
                log_info("File upload to Telegram finished.")
                
                chat_id = tracker.get("chat_id")
                if use_inline:
                    try:
                        with open(file_path, "rb") as f:
                            file_bytes = f.read()
                        
                        is_video = ext in ('.mp4', '.mkv', '.mov', '.webm')
                        is_photo = ext in ('.jpg', '.jpeg', '.png', '.webp')
                        is_audio = ext in ('.mp3', '.m4a', '.ogg', '.flac', '.wav')
                        is_gif = ext in ('.gif',)
                        
                        edit_kwargs = {
                            "text": caption,
                            "reply_markup": [],
                            "photo": None,
                            "gif": None,
                            "file": None,
                            "audio": None,
                            "video": None,
                        }
                        if is_video:
                            edit_kwargs["video"] = file_bytes
                        elif is_photo:
                            edit_kwargs["photo"] = file_bytes
                        elif is_audio:
                            edit_kwargs["audio"] = file_bytes
                        elif is_gif:
                            edit_kwargs["gif"] = file_bytes
                        else:
                            import mimetypes
                            mime, _ = mimetypes.guess_type(file_path)
                            edit_kwargs["file"] = file_bytes
                            edit_kwargs["mime_type"] = mime or "application/octet-stream"

                        log_info(f"Attempting direct inline edit on status message. Fields: {list(edit_kwargs.keys())}")
                        edit_success = await status_msg.edit(**edit_kwargs)
                        log_info(f"Inline edit success status: {edit_success}")
                        if not edit_success:
                            raise Exception("Hikka edit returned False")
                    except Exception as e:
                        log_error("Error during direct inline editing. Falling back to sending as new file.", exc_info=True)
                        await client.send_file(
                            chat_id,
                            uploaded_file,
                            caption=caption,
                            attributes=attributes,
                            reply_to=reply_to
                        )
                        try:
                            log_info("Deleting status_msg after fallback send_file")
                            await status_msg.delete()
                        except Exception as del_err:
                            log_warning(f"Failed to delete status message: {del_err}")
                            pass
                else:
                    log_info("Editing status message directly to show the downloaded file...")
                    await status_msg.edit(caption, file=uploaded_file, attributes=attributes)
            else:
                log_info(f"Uploading multiple files: {media_files}")
                await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Загружаем медиа в Telegram...</b>", tracker)
                chat_id = tracker.get("chat_id")
                await client.send_file(chat_id, media_files, caption=caption, reply_to=reply_to)
                try:
                    log_info("Deleting status message after multiple files upload")
                    await status_msg.delete()
                except Exception as del_err:
                    log_warning(f"Failed to delete status message: {del_err}")
                    pass
        except Exception as e:
            log_error("yt-dlp upload/send task exception", exc_info=True)
            safe_error = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            await self._update_status_media_and_text(status_msg, "uploading", f"❌ <b>Telegram вернул ошибку:</b> <code>{safe_error}</code>", tracker)
        finally:
            log_info(f"Cleaning up yt-dlp download directory: {dl_dir}")
            shutil.rmtree(dl_dir, ignore_errors=True)

    async def _download_media_cobalt(self, status_msg, url, safe_url, tracker, reply_to=None):
        dl_dir = f"dl_{uuid.uuid4().hex}"
        os.makedirs(dl_dir, exist_ok=True)
        log_info(f"Created Cobalt download directory: {dl_dir}")
        
        await self._update_status_media_and_text(status_msg, "parsing", "⏳ <b>Обрабатываем через Cobalt API...</b>", tracker)
        
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
            api_url = self.config["COBALT_INSTANCE"]
            if not api_url.endswith('/'):
                api_url += '/'
                
            use_curl = False
            try:
                from curl_cffi.requests import AsyncSession
                use_curl = True
            except ImportError:
                pass

            log_info(f"Cobalt API endpoint URL: {api_url}")
            log_info(f"Cobalt request payload: {payload}")
            log_info(f"Cobalt request headers: {headers}")
            log_info(f"Cobalt HTTP engine: {'curl-cffi' if use_curl else 'aiohttp'}")

            data = None
            if use_curl:
                async with AsyncSession() as session:
                    log_info("Sending POST request to Cobalt API using curl_cffi...")
                    resp = await session.post(api_url, json=payload, headers=headers, impersonate="chrome")
                    log_info(f"Cobalt HTTP Status Code: {resp.status_code}")
                    log_info(f"Cobalt Response Headers: {dict(resp.headers)}")
                    log_info(f"Cobalt Raw Response Body: {resp.text}")
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                        except Exception as json_err:
                            log_error(f"Failed to parse Cobalt response as JSON: {json_err}")
                            raise json_err
                    else:
                        raise Exception(f"Cobalt error (status {resp.status_code}): {resp.text}")
            else:
                async with aiohttp.ClientSession() as http_session:
                    log_info("Sending POST request to Cobalt API using aiohttp...")
                    async with http_session.post(api_url, json=payload, headers=headers) as resp:
                        log_info(f"Cobalt HTTP Status Code: {resp.status}")
                        log_info(f"Cobalt Response Headers: {dict(resp.headers)}")
                        body_text = await resp.text()
                        log_info(f"Cobalt Raw Response Body: {body_text}")
                        if resp.status == 200:
                            try:
                                data = json.loads(body_text)
                            except Exception as json_err:
                                log_error(f"Failed to parse Cobalt response as JSON: {json_err}")
                                raise json_err
                        else:
                            raise Exception(f"Cobalt error (status {resp.status}): {body_text}")
                        
            log_info(f"Cobalt parsed response data: {data}")
            media_urls = []
            if data.get("status") == "picker":
                media_urls = [item["url"] for item in data.get("picker", [])]
                log_info(f"Cobalt returned status 'picker' with {len(media_urls)} item(s)")
            elif data.get("url"):
                media_urls = [data["url"]]
                log_info("Cobalt returned single media URL")
                
            if not media_urls:
                raise Exception(data.get("text") or "Не удалось получить ссылки от Cobalt")
                
            log_info(f"Resolved Cobalt media download URLs: {media_urls}")
            await self._update_status_media_and_text(status_msg, "downloading", f"📥 <b>Скачиваем {len(media_urls)} файлов...</b>", tracker, force_media_update=True)

            async def download_one(session_obj, m_url, idx):
                log_info(f"Downloading file {idx+1}/{len(media_urls)}: {m_url}")
                if use_curl:
                    resp_ctx = session_obj.stream("GET", m_url, impersonate="chrome")
                else:
                    resp_ctx = session_obj.get(m_url)

                async with resp_ctx as resp:
                    status_code = resp.status_code if use_curl else resp.status
                    headers_dict = dict(resp.headers)
                    log_info(f"File {idx+1} download response code: {status_code}")
                    log_info(f"File {idx+1} download headers: {headers_dict}")
                    if status_code != 200:
                        log_warning(f"Failed to get file {idx+1}: HTTP {status_code}")
                        return False

                    cd = resp.headers.get('Content-Disposition', '')
                    filename = None
                    filename_match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";\n\r]+)"?', cd, re.IGNORECASE)
                    if filename_match:
                        filename = unquote(filename_match.group(1)).strip('"\'')
                        log_info(f"Parsed filename from Content-Disposition: {filename}")
                        
                    if filename:
                        ext = os.path.splitext(filename)[1].lower()
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
                        log_info(f"No filename in Content-Disposition. Content-Type is '{content_type}'. Defaulting file path to: {file_path}")
                    
                    try:
                        total_size = int(resp.headers.get('Content-Length', 0))
                    except Exception:
                        total_size = 0
                    log_info(f"File {idx+1} size declared as Content-Length: {total_size} bytes")
                        
                    downloaded = 0
                    start_time = time.time()
                    last_update = 0.0
                    
                    log_info(f"Starting chunk download for file {idx+1} to {file_path}...")
                    with open(file_path, 'wb') as f:
                        if use_curl:
                            async for chunk in resp.aiter_content():
                                f.write(chunk)
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
                                        await self._update_status_media_and_text(status_msg, "downloading", text, tracker)
                                    except Exception:
                                        pass
                        else:
                            while True:
                                chunk = await resp.content.read(65536)
                                if not chunk:
                                    break
                                f.write(chunk)
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
                                        await self._update_status_media_and_text(status_msg, "downloading", text, tracker)
                                    except Exception:
                                        pass
                    log_info(f"Finished downloading file {idx+1}. Path: {file_path}, Size: {downloaded} bytes")
                    if downloaded == 0:
                        log_warning(f"File {idx+1} is empty (0 bytes), removing it.")
                        if os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                            except Exception as rm_err:
                                log_error(f"Failed to remove empty file: {rm_err}")
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
                        log_info(f"Removing empty file from upload list: {f}")
                        os.remove(f)
                    except Exception as e:
                        log_error(f"Failed to remove empty file {f}: {e}")
                        pass
            files = glob.glob(f"{dl_dir}/*")
            log_info(f"Active files selected for upload: {files}")
            if not files:
                raise Exception("Файлы не скачались (папка пуста)")
                
            await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Загружаем в Telegram...</b>", tracker, force_media_update=True)
            
            start_time = time.time()
            last_update = [0]
            tracker["stage"] = "uploading"
            
            async def upload_progress(current, total):
                now = time.time()
                if now - last_update[0] >= 1.5 or current == total:
                    last_update[0] = now
                    text = self._format_progress("🚀 <b>Загружаем в Telegram...</b>", current, total, start_time)
                    log_info(f"Telegram upload progress: {current}/{total} bytes ({current/total*100:.1f}%)")
                    try:
                        await self._update_status_media_and_text(status_msg, "uploading", text, tracker)
                    except Exception:
                        pass
                        
            caption = f"🔗 {safe_url}" if self.config["SEND_LINKS"] else ""
            
            client = tracker.get("client")
            use_inline = tracker.get("use_inline", False)
            
            if len(files) == 1:
                file_path = files[0]
                attributes = []
                
                ext = os.path.splitext(file_path)[1].lower()
                log_info(f"Uploading single file. Extension: '{ext}'")
                if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                    try:
                        log_info("Extracting video metadata using ffprobe...")
                        width, height, duration = await self._get_video_metadata(file_path)
                        log_info(f"Video metadata: width={width}, height={height}, duration={duration}")
                        if width and height and duration:
                            attributes.append(DocumentAttributeVideo(
                                duration=duration,
                                w=width,
                                h=height,
                                supports_streaming=True
                            ))
                    except Exception as e:
                        log_warning(f"Failed to extract video attributes: {e}")
                
                log_info(f"Uploading file {file_path} to Telegram...")
                uploaded_file = await client.upload_file(file_path, progress_callback=upload_progress)
                log_info("File upload to Telegram finished.")
                
                chat_id = tracker.get("chat_id")
                if use_inline:
                    try:
                        with open(file_path, "rb") as f:
                            file_bytes = f.read()
                        
                        is_video = ext in ('.mp4', '.mkv', '.mov', '.webm')
                        is_photo = ext in ('.jpg', '.jpeg', '.png', '.webp')
                        is_audio = ext in ('.mp3', '.m4a', '.ogg', '.flac', '.wav')
                        is_gif = ext in ('.gif',)
                        
                        edit_kwargs = {
                            "text": caption,
                            "reply_markup": [],
                            "photo": None,
                            "gif": None,
                            "file": None,
                            "audio": None,
                            "video": None,
                        }
                        if is_video:
                            edit_kwargs["video"] = file_bytes
                        elif is_photo:
                            edit_kwargs["photo"] = file_bytes
                        elif is_audio:
                            edit_kwargs["audio"] = file_bytes
                        elif is_gif:
                            edit_kwargs["gif"] = file_bytes
                        else:
                            import mimetypes
                            mime, _ = mimetypes.guess_type(file_path)
                            edit_kwargs["file"] = file_bytes
                            edit_kwargs["mime_type"] = mime or "application/octet-stream"

                        log_info(f"Attempting direct inline edit on status message. Fields: {list(edit_kwargs.keys())}")
                        edit_success = await status_msg.edit(**edit_kwargs)
                        log_info(f"Inline edit success status: {edit_success}")
                        if not edit_success:
                            raise Exception("Hikka edit returned False")
                    except Exception as e:
                        log_error("Error during direct inline editing. Falling back to sending as new file.", exc_info=True)
                        await client.send_file(
                            chat_id,
                            uploaded_file,
                            caption=caption,
                            attributes=attributes,
                            reply_to=reply_to
                        )
                        try:
                            log_info("Deleting status_msg after fallback send_file")
                            await status_msg.delete()
                        except Exception as del_err:
                            log_warning(f"Failed to delete status message: {del_err}")
                            pass
                else:
                    log_info("Editing status message directly to show the downloaded file...")
                    await status_msg.edit(caption, file=uploaded_file, attributes=attributes)
            else:
                log_info(f"Uploading multiple files: {files}")
                await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Загружаем медиа в Telegram...</b>", tracker)
                chat_id = tracker.get("chat_id")
                await client.send_file(chat_id, files, caption=caption, reply_to=reply_to)
                try:
                    log_info("Deleting status message after multiple files upload")
                    await status_msg.delete()
                except Exception as del_err:
                    log_warning(f"Failed to delete status message: {del_err}")
                    pass
        except Exception as e:
            log_error("Cobalt downloader task exception", exc_info=True)
            raise e
        finally:
            log_info(f"Cleaning up Cobalt download directory: {dl_dir}")
            shutil.rmtree(dl_dir, ignore_errors=True)
