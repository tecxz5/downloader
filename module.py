# meta developer: @tecxz5
import os
import re
import time
import traceback
import asyncio
import aiohttp
from telethon.tl.types import MessageEntityUrl, MessageEntityTextUrl
from .. import loader, utils

@loader.tds
class UniversalDLMod(loader.Module):
    """Универсальный скачиватель (yt-dlp + Cobalt) с риалтайм скоростью"""
    
    strings = {"name": "UniDL"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            "COBALT_INSTANCE", "http://127.0.0.1:9000/", "Локальный адрес твоего Кобальта"
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

        status_msg = await utils.answer(message, f"⏳ <b>Парсим:</b> <code>{url}</code>")
        
        if re.search(r"(?:youtube\.com|youtu\.be)", url):
            await self._download_youtube(status_msg, url, reply_to=message.reply_to_msg_id)
        else:
            await self._download_cobalt(status_msg, url, reply_to=message.reply_to_msg_id)

    async def _download_youtube(self, status_msg, url, reply_to=None):
        file_name = "yt_video.mp4"
        if os.path.exists(file_name):
            os.remove(file_name)
            
        await utils.answer(status_msg, "📥 <b>Подключение к YouTube...</b>")
        
        # Добавляем флаг --newline, чтобы yt-dlp отдавал логи построчно
        cmd = f'yt-dlp --newline -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" --merge-output-format mp4 -o "{file_name}" "{url}"'
        
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
                    try:
                        await utils.answer(status_msg, f"📥 <b>Скачиваем с YouTube:</b>\n📊 <code>{clean_line}</code>")
                    except Exception:
                        pass
                        
        await process.wait()
        
        if not os.path.exists(file_name) or os.path.getsize(file_name) < 1024:
            return await utils.answer(status_msg, "❌ <b>Ошибка скачивания с YouTube.</b>")
            
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
            await status_msg.client.send_file(status_msg.chat_id, file_name, caption=f"🔗 {url}", reply_to=reply_to, progress_callback=upload_progress)
            await status_msg.delete()
        except Exception as e:
            await utils.answer(status_msg, f"❌ <b>Telegram вернул ошибку:</b> <code>{str(e)}</code>")
        finally:
            if os.path.exists(file_name):
                os.remove(file_name)

    async def _download_cobalt(self, status_msg, url, reply_to=None):
        async with aiohttp.ClientSession() as session:
            try:
                cobalt_url = self.config["COBALT_INSTANCE"]
                
                async with session.post(
                    cobalt_url, 
                    json={"url": url},
                    headers={"Accept": "application/json", "Content-Type": "application/json"}
                ) as resp:
                    raw_text = await resp.text()
                    try:
                        import json
                        data = json.loads(raw_text)
                    except:
                        data = {}

                    if resp.status != 200:
                        if not data:
                            return await utils.answer(status_msg, f"❌ <b>Cobalt RAW Error {resp.status}:</b>\n<code>{raw_text[:250]}</code>")
                        
                        err_obj = data.get("error", {})
                        if isinstance(err_obj, dict):
                            err_code = err_obj.get("code", data.get("code", "NO_CODE"))
                            err_text = err_obj.get("message", data.get("text", "Unknown error"))
                        else:
                            err_code = data.get("code", "NO_CODE")
                            err_text = data.get("text", "Unknown error")
                            
                        return await utils.answer(
                            status_msg, 
                            f"❌ <b>Cobalt API Error {resp.status}:</b>\n<code>{err_code}: {err_text}</code>"
                        )

                status = data.get("status")

                if status == "picker":
                    photos = [item.get("url") if isinstance(item, dict) else item for item in data.get("picker", [])]
                    await status_msg.client.send_file(status_msg.chat_id, photos, caption=f"🔗 {url}", reply_to=reply_to)
                    return await status_msg.delete()

                target_url = data.get("url")
                if not target_url:
                    error_text = data.get("text", "Неизвестная ошибка: нет ссылки")
                    return await utils.answer(status_msg, f"❌ <b>Cobalt:</b> <code>{error_text}</code>")

                file_name = "cobalt_video.mp4"
                dl_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                    "Accept": "*/*"
                }

                async with session.get(target_url, headers=dl_headers) as media_resp:
                    if media_resp.status != 200:
                        return await utils.answer(status_msg, f"❌ <b>Ошибка: CDN вернул код {media_resp.status}</b>")
                    
                    total_size = int(media_resp.headers.get('Content-Length', 0))
                    current_size = 0
                    start_dl_time = time.time()
                    last_dl_update = [0]
                        
                    with open(file_name, 'wb') as fd:
                        while True:
                            chunk = await media_resp.content.read(1024 * 1024)
                            if not chunk:
                                break
                            fd.write(chunk)
                            current_size += len(chunk)
                            
                            now = time.time()
                            # Обновляем статус раз в секунду или когда докачали до конца
                            if now - last_dl_update[0] >= 1.0 or (total_size and current_size == total_size):
                                last_dl_update[0] = now
                                text = self._format_progress("📥 <b>Скачиваем на сервер...</b>", current_size, total_size, start_dl_time)
                                try:
                                    await utils.answer(status_msg, text)
                                except Exception:
                                    pass

                if not os.path.exists(file_name) or os.path.getsize(file_name) < 1024:
                    if os.path.exists(file_name):
                        os.remove(file_name)
                    return await utils.answer(status_msg, "❌ <b>Файл скачался пустым. Блокировка источника.</b>")

                start_up_time = time.time()
                last_up_update = [0]
                
                async def upload_progress(current, total):
                    now = time.time()
                    if now - last_up_update[0] >= 1.0 or current == total:
                        last_up_update[0] = now
                        text = self._format_progress("🚀 <b>Загружаем в Telegram...</b>", current, total, start_up_time)
                        try:
                            await utils.answer(status_msg, text)
                        except Exception:
                            pass

                try:
                    await status_msg.client.send_file(status_msg.chat_id, file_name, caption=f"🔗 {url}", reply_to=reply_to, progress_callback=upload_progress)
                    await status_msg.delete()
                except Exception as e:
                    await utils.answer(status_msg, f"❌ <b>Telegram не принял файл:</b> <code>{str(e)}</code>")
                finally:
                    if os.path.exists(file_name):
                        os.remove(file_name)

            except Exception as e:
                full_trace = traceback.format_exc()
                print(f"\n--- ОШИБКА DL ---\n{full_trace}\n------------------------\n")
                safe_error = str(e).replace('<', '&lt;').replace('>', '&gt;')
                await utils.answer(status_msg, f"❌ <b>Ошибка модуля:</b> <code>{safe_error}</code>")
                if 'file_name' in locals() and os.path.exists(file_name):
                    os.remove(file_name)
