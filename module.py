# meta developer: @tecxz5
import os
import re
import time
import asyncio
import shutil
import uuid
import glob
from telethon.tl.types import MessageEntityUrl, MessageEntityTextUrl
from .. import loader, utils
import aiohttp
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, unquote

COBALT_SUPPORTED_DOMAINS = (
    "bilibili.com", "instagram.com", "pinterest.com", "pin.it",
    "reddit.com", "rutube.ru", "snapchat.com", "soundcloud.com",
    "streamable.com", "tiktok.com", "tumblr.com", "twitch.tv",
    "twitter.com", "x.com", "vimeo.com", "vk.com", "vk.video",
    "vine.co", "youtube.com", "youtu.be"
)

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
        status_msg = await utils.answer(message, f"⏳ <b>Парсим:</b> <code>{safe_url}</code>")
        
        await self._download_media(status_msg, url, safe_url, reply_to=message.reply_to_msg_id)

    async def _download_media(self, status_msg, url, safe_url, reply_to=None):
        domain = urlparse(url).netloc.lower()
        use_cobalt = any(d in domain for d in COBALT_SUPPORTED_DOMAINS)

        if use_cobalt:
            try:
                await self._download_media_cobalt(status_msg, url, safe_url, reply_to)
            except Exception as e:
                print(f"⚠️ Cobalt failed for {url}: {e}. Falling back to yt-dlp.")
                try:
                    await utils.answer(status_msg, "⏳ <b>Cobalt не справился, пробуем альтернативный метод (yt-dlp)...</b>")
                except Exception:
                    pass
                await self._download_media_ytdl(status_msg, url, safe_url, reply_to)
        else:
            await self._download_media_ytdl(status_msg, url, safe_url, reply_to)

    async def _download_media_ytdl(self, status_msg, url, safe_url, reply_to=None):
        dl_dir = f"dl_{uuid.uuid4().hex}"
        os.makedirs(dl_dir, exist_ok=True)
            
        await utils.answer(status_msg, "📥 <b>Подключение к источнику...</b>")
        
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
                            await utils.answer(status_msg, progress_text)
                        except Exception:
                            pass
                            
        await process.wait()
        
        files = glob.glob(f"{dl_dir}/*")
        if not files:
            shutil.rmtree(dl_dir, ignore_errors=True)
            return await utils.answer(status_msg, "❌ <b>Ошибка скачивания или нет медиа.</b>")
            
        start_time = time.time()
        last_update = [0]
        
        async def upload_progress(current, total):
            now = time.time()
            if now - last_update[0] >= 1.0 or current == total:
                last_update[0] = now
                text = self._format_progress("🚀 <b>Загружаем в Telegram...</b>", current, total, start_time)
                try:
                    await utils.answer(status_msg, text)
                except Exception:
                    pass

        try:
            media_files = [f for f in files if not f.endswith(('.json', '.description', '.info'))]
            if not media_files:
                media_files = files
                
            caption = f"🔗 {safe_url}" if self.config["SEND_LINKS"] else ""
            
            if len(media_files) == 1:
                await status_msg.client.send_file(status_msg.chat_id, media_files[0], caption=caption, reply_to=reply_to, progress_callback=upload_progress)
            else:
                await utils.answer(status_msg, "🚀 <b>Загружаем медиа в Telegram...</b>")
                await status_msg.client.send_file(status_msg.chat_id, media_files, caption=caption, reply_to=reply_to)
            await status_msg.delete()
        except Exception as e:
            safe_error = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            await utils.answer(status_msg, f"❌ <b>Telegram вернул ошибку:</b> <code>{safe_error}</code>")
        finally:
            shutil.rmtree(dl_dir, ignore_errors=True)

    async def _download_media_cobalt(self, status_msg, url, safe_url, reply_to=None):
        dl_dir = f"dl_{uuid.uuid4().hex}"
        os.makedirs(dl_dir, exist_ok=True)
        
        await utils.answer(status_msg, "📥 <b>Обрабатываем через Cobalt API...</b>")
        
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
                
            await utils.answer(status_msg, f"📥 <b>Скачиваем {len(media_urls)} файлов...</b>")
            
            async with aiohttp.ClientSession() as http_session:
                for i, m_url in enumerate(media_urls):
                    async with http_session.get(m_url) as resp:
                        if resp.status == 200:
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
                                    
                                file_path = os.path.join(dl_dir, f"file_{i}{ext}")
                            
                            try:
                                total_size = int(resp.headers.get('Content-Length', 0))
                            except Exception:
                                total_size = 0
                                
                            downloaded = 0
                            start_time = time.time()
                            last_update = 0.0
                            
                            with open(file_path, 'wb') as f:
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
                                        
                                        file_info = f" (файл {i+1}/{len(media_urls)})" if len(media_urls) > 1 else ""
                                        
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
                                            await utils.answer(status_msg, text)
                                        except Exception:
                                            pass
                                        
            files = glob.glob(f"{dl_dir}/*")
            if not files:
                raise Exception("Файлы не скачались")
                
            start_time = time.time()
            last_update = [0]
            
            async def upload_progress(current, total):
                now = time.time()
                if now - last_update[0] >= 1.0 or current == total:
                    last_update[0] = now
                    text = self._format_progress("🚀 <b>Загружаем в Telegram...</b>", current, total, start_time)
                    try:
                        await utils.answer(status_msg, text)
                    except Exception:
                        pass
                        
            caption = f"🔗 {safe_url}" if self.config["SEND_LINKS"] else ""
            
            if len(files) == 1:
                await status_msg.client.send_file(status_msg.chat_id, files[0], caption=caption, reply_to=reply_to, progress_callback=upload_progress)
            else:
                await utils.answer(status_msg, "🚀 <b>Загружаем медиа в Telegram...</b>")
                await status_msg.client.send_file(status_msg.chat_id, files, caption=caption, reply_to=reply_to)
            await status_msg.delete()
        except Exception as e:
            raise e
        finally:
            shutil.rmtree(dl_dir, ignore_errors=True)
