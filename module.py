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

@loader.tds
class UniversalDLMod(loader.Module):
    """Универсальный скачиватель (yt-dlp) с риалтайм скоростью"""
    
    strings = {"name": "UniDL"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            "SEND_LINKS", True, "Прикреплять ссылку на источник"
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

        safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        status_msg = await utils.answer(message, f"⏳ <b>Парсим:</b> <code>{safe_url}</code>")
        
        await self._download_media(status_msg, url, safe_url, reply_to=message.reply_to_msg_id)

    async def _download_media(self, status_msg, url, safe_url, reply_to=None):
        dl_dir = f"dl_{uuid.uuid4().hex}"
        os.makedirs(dl_dir, exist_ok=True)
            
        await utils.answer(status_msg, "📥 <b>Подключение к источнику...</b>")
        
        # Добавляем флаг --newline, чтобы yt-dlp отдавал логи построчно
        cmd = f'yt-dlp --newline -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" -o "{dl_dir}/%(id)s_%(autonumber)s.%(ext)s" "{url}"'
        
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        
        last_update = time.time()
        
        # Читаем консольный вывод yt-dlp в реальном времени
        while True:
            line = await process.stdout.readline()
            if not line:
                break
                
            text_line = line.decode('utf-8', errors='ignore').strip()
            
            # Ищем строчки со статусом скачивания
            if "[download]" in text_line and "%" in text_line:
                now = time.time()
                if now - last_update >= 1.0:
                    last_update = now
                    # Вырезаем мусор от yt-dlp и оставляем только суть (проценты, размер, скорость)
                    clean_line = text_line.replace("[download]", "").strip()
                    safe_line = clean_line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    try:
                        await utils.answer(status_msg, f"📥 <b>Скачиваем:</b>\n📊 <code>{safe_line}</code>")
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
            # Отфильтруем возможный мусор, оставляем только медиа
            media_files = [f for f in files if not f.endswith(('.json', '.description', '.info'))]
            if not media_files:
                media_files = files # фоллбэк
                
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
