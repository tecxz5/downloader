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

# === DOWNLOADER_CORE ===

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
                        vid_attr.supports_streaming = True
                        if duration: vid_attr.duration = duration
                        if width: vid_attr.w = width
                        if height: vid_attr.h = height
                        attributes.append(vid_attr)
                        attributes.append(DocumentAttributeFilename(file_name=os.path.basename(media_files[0])))
                    elif ext in ('.mp3', '.m4a', '.ogg', '.flac'):
                        audio_attr = DocumentAttributeAudio(duration=0, voice=False, title="", performer="")
                        attributes.append(audio_attr)
                        attributes.append(DocumentAttributeFilename(file_name=os.path.basename(media_files[0])))
                    
                    await status_msg.edit(
                        text=caption,
                        file=uploaded_file,
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
            
            
            if len(media_files) > 1:
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
