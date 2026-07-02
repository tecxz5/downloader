import os
import re
import time
import traceback
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.utils.media_group import MediaGroupBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

# === НАСТРОЙКИ ===
BOT_TOKEN = "ТВОЙ_ТОКЕН_ОТ_BOTFATHER"
ALLOWED_USERS = [123456789, 987654321]  # Впиши свой ID и ID друзей через запятую
COBALT_INSTANCE = "http://127.0.0.1:9000/"
LOCAL_TG_API = "http://127.0.0.1:8081"
# =================

session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_TG_API))
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()

def format_progress(action, current, total, start_time):
    """Отрисовка прогресс-бара для скачивания файлов"""
    cur_mb = current / 1048576
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

def extract_url(message: types.Message):
    """Вытаскиваем чистую ссылку из сообщения"""
    text = message.text or message.caption or ""
    if text:
        match = re.search(r"(https?://[^\s]+)", text)
        if match:
            url = match.group(1).strip()
            while url and url[-1] in ".,!?;:\"')}]>":
                url = url[:-1]
            return url
    return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return
    await message.answer("👋 <b>Привет!</b> Отправь мне ссылку на видео (YouTube, TikTok, Instagram), и я его скачаю.", parse_mode="HTML")

@dp.message()
async def handle_message(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return

    url = extract_url(message)
    if not url:
        return

    status_msg = await message.reply(f"⏳ <b>Парсим:</b> <code>{url}</code>", parse_mode="HTML")

    if re.search(r"(?:youtube\.com|youtu\.be)", url):
        await download_youtube(message, status_msg, url)
    else:
        await download_cobalt(message, status_msg, url)

async def download_youtube(message: types.Message, status_msg: types.Message, url: str):
    file_name = f"yt_{message.message_id}.mp4"
    if os.path.exists(file_name):
        os.remove(file_name)
        
    await status_msg.edit_text("📥 <b>Подключение к YouTube...</b>", parse_mode="HTML")
    
    cmd = f'yt-dlp --newline -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" --merge-output-format mp4 -o "{file_name}" "{url}"'
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    
    last_update = time.time()
    
    # Читаем вывод yt-dlp в реальном времени
    while True:
        line = await process.stdout.readline()
        if not line:
            break
            
        text_line = line.decode('utf-8', errors='ignore').strip()
        if "[download]" in text_line and "%" in text_line:
            now = time.time()
            if now - last_update >= 1.0:
                last_update = now
                clean_line = text_line.replace("[download]", "").strip()
                try:
                    await status_msg.edit_text(f"📥 <b>Скачиваем с YouTube:</b>\n📊 <code>{clean_line}</code>", parse_mode="HTML")
                except Exception:
                    pass
                    
    await process.wait()
    
    if not os.path.exists(file_name) or os.path.getsize(file_name) < 1024:
        return await status_msg.edit_text("❌ <b>Ошибка скачивания с YouTube.</b>", parse_mode="HTML")
        
    await status_msg.edit_text("🚀 <b>Локальный сервер загружает в Telegram...</b>\n<i>Ожидайте, это может занять время для больших файлов.</i>", parse_mode="HTML")
    
    try:
        video = FSInputFile(file_name)
        await bot.send_video(chat_id=message.chat.id, video=video, caption=f"🔗 {url}", reply_to_message_id=message.message_id)
        await status_msg.delete()
    except Exception as e:
        safe_error = str(e).replace('<', '&lt;').replace('>', '&gt;')
        await status_msg.edit_text(f"❌ <b>Ошибка отправки:</b> <code>{safe_error}</code>", parse_mode="HTML")
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

async def download_cobalt(message: types.Message, status_msg: types.Message, url: str):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                COBALT_INSTANCE, 
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
                        return await status_msg.edit_text(f"❌ <b>Cobalt RAW Error {resp.status}:</b>\n<code>{raw_text[:250]}</code>", parse_mode="HTML")
                    
                    err_obj = data.get("error", {})
                    if isinstance(err_obj, dict):
                        err_code = err_obj.get("code", data.get("code", "NO_CODE"))
                        err_text = err_obj.get("message", data.get("text", "Unknown error"))
                    else:
                        err_code = data.get("code", "NO_CODE")
                        err_text = data.get("text", "Unknown error")
                        
                    return await status_msg.edit_text(f"❌ <b>Cobalt API Error {resp.status}:</b>\n<code>{err_code}: {err_text}</code>", parse_mode="HTML")

            status = data.get("status")

            if status == "picker":
                media_group = MediaGroupBuilder(caption=f"🔗 {url}")
                for item in data.get("picker", []):
                    img_url = item.get("url") if isinstance(item, dict) else item
                    media_group.add_photo(type="photo", media=img_url)
                
                await bot.send_media_group(chat_id=message.chat.id, media=media_group.build(), reply_to_message_id=message.message_id)
                return await status_msg.delete()

            target_url = data.get("url")
            if not target_url:
                error_text = data.get("text", "Неизвестная ошибка: нет ссылки")
                return await status_msg.edit_text(f"❌ <b>Cobalt:</b> <code>{error_text}</code>", parse_mode="HTML")

            file_name = f"cobalt_{message.message_id}.mp4"
            dl_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                "Accept": "*/*"
            }

            async with session.get(target_url, headers=dl_headers) as media_resp:
                if media_resp.status != 200:
                    return await status_msg.edit_text(f"❌ <b>Ошибка: CDN вернул код {media_resp.status}</b>", parse_mode="HTML")
                
                total_size = int(media_resp.headers.get('Content-Length', 0))
                current_size = 0
                start_dl_time = time.time()
                last_dl_update = 0
                    
                with open(file_name, 'wb') as fd:
                    while True:
                        chunk = await media_resp.content.read(1024 * 1024)
                        if not chunk:
                            break
                        fd.write(chunk)
                        current_size += len(chunk)
                        
                        now = time.time()
                        if now - last_dl_update >= 1.0 or (total_size and current_size == total_size):
                            last_dl_update = now
                            text = format_progress("📥 <b>Скачиваем на сервер...</b>", current_size, total_size, start_dl_time)
                            try:
                                await status_msg.edit_text(text, parse_mode="HTML")
                            except Exception:
                                pass

            if not os.path.exists(file_name) or os.path.getsize(file_name) < 1024:
                if os.path.exists(file_name):
                    os.remove(file_name)
                return await status_msg.edit_text("❌ <b>Файл скачался пустым. Блокировка источника.</b>", parse_mode="HTML")

            await status_msg.edit_text("🚀 <b>Локальный сервер загружает в Telegram...</b>\n<i>Ожидайте, это может занять время для больших файлов.</i>", parse_mode="HTML")
            
            video = FSInputFile(file_name)
            await bot.send_video(chat_id=message.chat.id, video=video, caption=f"🔗 {url}", reply_to_message_id=message.message_id)
            
            if os.path.exists(file_name):
                os.remove(file_name)
            await status_msg.delete()

        except Exception as e:
            full_trace = traceback.format_exc()
            print(f"\n--- ОШИБКА BOT DL ---\n{full_trace}\n------------------------\n")
            safe_error = str(e).replace('<', '&lt;').replace('>', '&gt;')
            await status_msg.edit_text(f"❌ <b>Ошибка выполнения:</b> <code>{safe_error}</code>", parse_mode="HTML")
            if 'file_name' in locals() and os.path.exists(file_name):
                os.remove(file_name)

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