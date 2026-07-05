# meta developer: @tecxz5
# meta dependencies: curl-cffi
import os
import io
import re
import time
import asyncio
import shutil
import uuid
import glob
from telethon.tl.types import MessageEntityUrl, MessageEntityTextUrl, DocumentAttributeVideo
from .. import loader, utils
import aiohttp
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, unquote

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
        """<ссылка> или реплей - Скачать видео/фото"""
        args = utils.get_args_raw(message)
        url = None
        reply = await message.get_reply_message()

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
        
        # Delete triggering message if it is outgoing to keep chat clean
        if message.out:
            try:
                await message.delete()
            except Exception:
                pass
                
        status_msg = None
        use_inline = bool(self.inline)
        
        if use_inline:
            try:
                status_msg = await self.inline.form(
                    text=f"⏳ <b>Парсим:</b> <code>{safe_url}</code>",
                    message=message,
                    gif=self.config["GIF_PARSING"]
                )
            except Exception as e:
                print(f"⚠️ Не удалось запустить инлайн-форму: {e}")
                use_inline = False
                
        if not use_inline:
            # В обычном режиме НЕ шлем гифки, чтобы не засорять Saved GIFs
            status_msg = await utils.answer(message, f"⏳ <b>Парсим:</b> <code>{safe_url}</code>")
            
        tracker = {"stage": "parsing", "use_inline": use_inline, "client": message.client}
        await self._download_media(status_msg, url, safe_url, tracker, reply_to=message.reply_to_msg_id)

    async def _download_media(self, status_msg, url, safe_url, tracker, reply_to=None):
        domain = urlparse(url).netloc.lower()
        use_cobalt = any(d in domain for d in COBALT_SUPPORTED_DOMAINS)

        if use_cobalt:
            try:
                await self._download_media_cobalt(status_msg, url, safe_url, tracker, reply_to)
            except Exception as e:
                print(f"⚠️ Cobalt failed for {url}: {e}. Falling back to yt-dlp.")
                try:
                    await self._update_status_media_and_text(status_msg, "parsing", "⏳ <b>Cobalt не справился, пробуем альтернативный метод (yt-dlp)...</b>", tracker)
                except Exception:
                    pass
                await self._download_media_ytdl(status_msg, url, safe_url, tracker, reply_to)
        else:
            await self._download_media_ytdl(status_msg, url, safe_url, tracker, reply_to)

    async def _download_media_ytdl(self, status_msg, url, safe_url, tracker, reply_to=None):
        dl_dir = f"dl_{uuid.uuid4().hex}"
        os.makedirs(dl_dir, exist_ok=True)
            
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
                    progress_text = self._format_download_progress(text_line)
                    if progress_text:
                        try:
                            await self._update_status_media_and_text(status_msg, "downloading", progress_text, tracker)
                        except Exception:
                            pass
                            
        await process.wait()
        
        files = glob.glob(f"{dl_dir}/*")
        if not files:
            shutil.rmtree(dl_dir, ignore_errors=True)
            return await self._update_status_media_and_text(status_msg, "downloading", "❌ <b>Ошибка скачивания или нет медиа.</b>", tracker)
            
        await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Загружаем в Telegram...</b>", tracker, force_media_update=True)
        
        start_time = time.time()
        last_update = [0]
        upload_tracker = {"stage": "uploading"}
        
        async def upload_progress(current, total):
            now = time.time()
            if now - last_update[0] >= 1.5 or current == total:
                last_update[0] = now
                text = self._format_progress("🚀 <b>Загружаем в Telegram...</b>", current, total, start_time)
                try:
                    await self._update_status_media_and_text(status_msg, "uploading", text, upload_tracker)
                except Exception:
                    pass

        try:
            media_files = [f for f in files if not f.endswith(('.json', '.description', '.info'))]
            if not media_files:
                media_files = files
                
            caption = f"🔗 {safe_url}" if self.config["SEND_LINKS"] else ""
            
            client = tracker.get("client", status_msg.client)
            use_inline = tracker.get("use_inline", False)
            
            if len(media_files) == 1:
                file_path = media_files[0]
                attributes = []
                
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                    try:
                        width, height, duration = await self._get_video_metadata(file_path)
                        if width and height and duration:
                            attributes.append(DocumentAttributeVideo(
                                duration=duration,
                                w=width,
                                h=height,
                                supports_streaming=True
                            ))
                    except Exception as e:
                        print(f"⚠️ Не удалось извлечь атрибуты видео: {e}")
                
                uploaded_file = await client.upload_file(file_path, progress_callback=upload_progress)
                
                if use_inline:
                    await client.send_file(
                        status_msg.chat_id,
                        uploaded_file,
                        caption=caption,
                        attributes=attributes,
                        reply_to=reply_to
                    )
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                else:
                    await status_msg.edit(caption, file=uploaded_file, attributes=attributes)
            else:
                await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Загружаем медиа в Telegram...</b>", upload_tracker)
                await client.send_file(status_msg.chat_id, media_files, caption=caption, reply_to=reply_to)
                try:
                    await status_msg.delete()
                except Exception:
                    pass
        except Exception as e:
            safe_error = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            await self._update_status_media_and_text(status_msg, "uploading", f"❌ <b>Telegram вернул ошибку:</b> <code>{safe_error}</code>", upload_tracker)
        finally:
            shutil.rmtree(dl_dir, ignore_errors=True)

    async def _download_media_cobalt(self, status_msg, url, safe_url, tracker, reply_to=None):
        dl_dir = f"dl_{uuid.uuid4().hex}"
        os.makedirs(dl_dir, exist_ok=True)
        
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
                
            await self._update_status_media_and_text(status_msg, "downloading", f"📥 <b>Скачиваем {len(media_urls)} файлов...</b>", tracker, force_media_update=True)

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
                    if downloaded == 0:
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
            for f in list(files):
                if os.path.exists(f) and os.path.getsize(f) == 0:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            files = glob.glob(f"{dl_dir}/*")
            if not files:
                raise Exception("Файлы не скачались")
                
            await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Загружаем в Telegram...</b>", tracker, force_media_update=True)
            
            start_time = time.time()
            last_update = [0]
            upload_tracker = {"stage": "uploading"}
            
            async def upload_progress(current, total):
                now = time.time()
                if now - last_update[0] >= 1.5 or current == total:
                    last_update[0] = now
                    text = self._format_progress("🚀 <b>Загружаем в Telegram...</b>", current, total, start_time)
                    try:
                        await self._update_status_media_and_text(status_msg, "uploading", text, upload_tracker)
                    except Exception:
                        pass
                        
            caption = f"🔗 {safe_url}" if self.config["SEND_LINKS"] else ""
            
            client = tracker.get("client", status_msg.client)
            use_inline = tracker.get("use_inline", False)
            
            if len(files) == 1:
                file_path = files[0]
                attributes = []
                
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ('.mp4', '.mkv', '.mov', '.webm'):
                    try:
                        width, height, duration = await self._get_video_metadata(file_path)
                        if width and height and duration:
                            attributes.append(DocumentAttributeVideo(
                                duration=duration,
                                w=width,
                                h=height,
                                supports_streaming=True
                            ))
                    except Exception as e:
                        print(f"⚠️ Не удалось извлечь атрибуты видео: {e}")
                
                uploaded_file = await client.upload_file(file_path, progress_callback=upload_progress)
                
                if use_inline:
                    await client.send_file(
                        status_msg.chat_id,
                        uploaded_file,
                        caption=caption,
                        attributes=attributes,
                        reply_to=reply_to
                    )
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                else:
                    await status_msg.edit(caption, file=uploaded_file, attributes=attributes)
            else:
                await self._update_status_media_and_text(status_msg, "uploading", "🚀 <b>Загружаем медиа в Telegram...</b>", upload_tracker)
                await client.send_file(status_msg.chat_id, files, caption=caption, reply_to=reply_to)
                try:
                    await status_msg.delete()
                except Exception:
                    pass
        except Exception as e:
            raise e
        finally:
            shutil.rmtree(dl_dir, ignore_errors=True)
