import os
import logging
import asyncio
import time
import json
from pathlib import Path
from dotenv import load_dotenv
from collections import defaultdict, deque

from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from video_downloader import VideoDownloader

# Load environment variables (expects TELEGRAM_BOT_TOKEN in .env)
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize video downloader
downloader = VideoDownloader()


def _parse_admin_ids(value: str | None) -> set[int]:
    if not value:
        return set()
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            continue
    return result


ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "10"))
MAX_PER_MINUTE = int(os.getenv("MAX_PER_MINUTE", "5"))
SPAM_THRESHOLD = int(os.getenv("SPAM_THRESHOLD", "15"))
SPAM_BAN_MINUTES = int(os.getenv("SPAM_BAN_MINUTES", "10"))


def _is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and user_id in ADMIN_IDS)


STATS = {
    "requests_total": 0,
    "success_total": 0,
    "fail_total": 0,
    "platform": {"tiktok": 0, "youtube": 0},
}

USERS_FILE = Path("users.json")
BANS_FILE = Path("bans.json")


def _load_users() -> dict:
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_users(users: dict) -> None:
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _update_user(user_id: int, first_name: str | None = None) -> None:
    users = _load_users()
    uid = str(user_id)
    now = int(time.time())
    if uid not in users:
        users[uid] = {
            "first_name": first_name or "",
            "request_count": 0,
            "last_seen": now,
        }
    users[uid]["request_count"] += 1
    users[uid]["last_seen"] = now
    if first_name:
        users[uid]["first_name"] = first_name
    _save_users(users)


def _load_bans() -> dict:
    if BANS_FILE.exists():
        try:
            with open(BANS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_bans(bans: dict) -> None:
    try:
        with open(BANS_FILE, "w", encoding="utf-8") as f:
            json.dump(bans, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _is_banned(user_id: int) -> bool:
    bans = _load_bans()
    uid = str(user_id)
    if uid not in bans:
        return False
    until = bans[uid].get("until", 0)
    return time.time() < until


def _ban_user(user_id: int, reason: str) -> None:
    bans = _load_bans()
    uid = str(user_id)
    until = int(time.time()) + SPAM_BAN_MINUTES * 60
    bans[uid] = {"until": until, "reason": reason}
    _save_bans(bans)


def _unban_user(user_id: int) -> None:
    bans = _load_bans()
    uid = str(user_id)
    if uid in bans:
        del bans[uid]
        _save_bans(bans)


# Rate limiting: user_id -> deque of timestamps
user_requests: defaultdict[int, deque[int]] = defaultdict(lambda: deque())
# Queue for downloads
download_queue: asyncio.Queue = asyncio.Queue()
# Semaphore for concurrent downloads
download_sem = asyncio.Semaphore(MAX_CONCURRENT)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    welcome_message = (
        "👋 Привет! Я бот для скачивания видео из TikTok и YouTube Shorts.\n\n"
        "Просто отправь мне ссылку на видео, и я пришлю его тебе без водяных знаков.\n\n"
        "Поддерживаемые платформы:\n"
        "• TikTok\n"
        "• YouTube Shorts"
    )
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_message = (
        "📌 Как пользоваться ботом:\n\n"
        "1) Отправьте ссылку на видео из TikTok или YouTube Shorts\n"
        "2) Подождите, пока я его скачаю\n"
        "3) Получите видео в ответ ✅\n\n"
        "Если что-то не работает — пришлите другую ссылку."
    )
    await update.message.reply_text(help_message)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages and process video links."""
    message = update.message
    if not message or not message.text:
        return

    user = message.from_user
    if not user:
        return

    # Ban check
    if _is_banned(user.id):
        await message.reply_text("❌ Вы заблокированы. Свяжитесь с админом.")
        return

    # Rate limiting
    now = int(time.time())
    reqs = user_requests[user.id]
    # Remove old requests (>1 minute)
    while reqs and reqs[0] <= now - 60:
        reqs.popleft()
    if len(reqs) >= MAX_PER_MINUTE:
        await message.reply_text("❌ Слишком много запросов. Попробуйте через минуту.")
        return
    reqs.append(now)

    # Spam detection
    if len(reqs) >= SPAM_THRESHOLD:
        _ban_user(user.id, "spam")
        # Notify admin
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🚨 Пользователь {user.id} ({user.first_name}) забанен за спам на {SPAM_BAN_MINUTES} минут."
                )
            except Exception:
                pass
        await message.reply_text(f"❌ Вы заблокированы на {SPAM_BAN_MINUTES} минут за флуд.")
        return

    # Update user stats
    _update_user(user.id, user.first_name)

    text = message.text.strip()

    # Check if the message is a URL
    if not (text.startswith("http://") or text.startswith("https://")):
        await message.reply_text(
            "Пожалуйста, отправьте валидную ссылку на видео из TikTok или YouTube Shorts."
        )
        return

    # Check if the URL is from a supported platform
    if not (downloader.is_tiktok(text) or downloader.is_youtube_shorts(text)):
        await message.reply_text("Извините, я поддерживаю только ссылки из TikTok и YouTube Shorts.")
        return

    processing_message = await message.reply_text("⏳ Обрабатываю ваше видео, пожалуйста подождите...")

    # Add to queue
    await download_queue.put((update, context, processing_message, text))


async def worker():
    """Background worker to process downloads with concurrency limit."""
    while True:
        task = await download_queue.get()
        update, context, processing_message, url = task
        async with download_sem:
            try:
                await process_download(update, context, processing_message, url)
            except Exception as e:
                logger.exception("Worker error: %s", e)
            finally:
                download_queue.task_done()


async def process_download(update: Update, context: ContextTypes.DEFAULT_TYPE, processing_message, text: str) -> None:
    """Actual download and send logic."""
    video_path = None
    try:
        STATS["requests_total"] += 1
        
        # Обновляем статус для пользователя
        await processing_message.edit_text("🔍 Поиск видео...")
        
        if downloader.is_tiktok(text):
            STATS["platform"]["tiktok"] += 1
            await processing_message.edit_text("⬇️ Скачивание TikTok видео...")
            logger.info("Начало загрузки TikTok: %s", text)
            video_path = await asyncio.to_thread(downloader.download_tiktok, text)
            logger.info("Результат загрузки TikTok: %s", video_path)
        else:
            STATS["platform"]["youtube"] += 1
            await processing_message.edit_text("⬇️ Скачивание YouTube видео...")
            logger.info("Начало загрузки YouTube: %s", text)
            video_path = await asyncio.to_thread(downloader.download_youtube_shorts, text)
            logger.info("Результат загрузки YouTube: %s", video_path)

        if not video_path:
            await processing_message.edit_text("❌ Не удалось загрузить видео (пустой путь)")
            logger.error("Видео_path равен None")
            return
            
        if not os.path.exists(video_path):
            await processing_message.edit_text("❌ Не удалось загрузить видео (файл не найден)")
            logger.error("Файл не существует: %s", video_path)
            return
            
        file_size = os.path.getsize(video_path)
        logger.info("Файл найден: %s, размер: %d bytes", video_path, file_size)
        
        if file_size == 0:
            await processing_message.edit_text("❌ Файл видео пустой")
            logger.error("Файл пустой: %s", video_path)
            return

        await processing_message.edit_text("📤 Отправка видео...")
        
        try:
            with open(video_path, "rb") as video_file:
                input_file = InputFile(video_file, filename=os.path.basename(video_path) or "video.mp4")
                await update.message.reply_video(
                    video=input_file,
                    caption="Вот ваше видео! 🎬\n@tikshorst_dowlonder_bot",
                    supports_streaming=True,
                )
            logger.info("Видео успешно отправлено")
        except Exception as send_error:
            logger.exception("Ошибка при отправке видео: %s", send_error)
            await processing_message.edit_text(f"❌ Ошибка отправки: {send_error}")
            return

        STATS["success_total"] += 1

        await processing_message.delete()

        try:
            os.remove(video_path)
            logger.info("Файл удален: %s", video_path)
        except OSError:
            pass

    except Exception as e:
        STATS["fail_total"] += 1
        logger.exception("Общая ошибка при обработке ссылки: %s", e)
        try:
            await processing_message.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except OSError:
                pass


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🏓 Пинг! Бот жив.")


async def adminhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    text = (
        "🛠️ Админ-команды:\n\n"
        "/stats — статистика бота\n"
        "/topusers — топ пользователей по количеству запросов\n"
        "/users — список всех user_id, кто когда-либо писал боту\n"
        "/info <user_id> — информация по пользователю (сколько запросов, последняя активность)\n"
        "/broadcast <сообщение> — отправить всем пользователям (аккуратно, не спамить)\n"
        "/adminhelp — показать все админ-команды\n"
        "/ping — проверить, что бот жив\n"
        "/ban <user_id> [причина] — забанить пользователя\n"
        "/unban <user_id> — разбанить пользователя (пользователь получит уведомление)\n"
        "/banned — список заблокированных и время до разбана\n"
        "/queue — состояние очереди и активных загрузок\n"
        "/limits — текущие лимиты и пороги"
    )
    await update.message.reply_text(text)


async def topusers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    users = _load_users()
    if not users:
        await update.message.reply_text("Пользователей пока нет.")
        return
    sorted_users = sorted(users.items(), key=lambda kv: kv[1].get("request_count", 0), reverse=True)[:10]
    lines = ["👥 Топ пользователей (по запросам):\n"]
    for uid, data in sorted_users:
        name = data.get("first_name", "")
        count = data.get("request_count", 0)
        lines.append(f"{uid}: {name} — {count} запросов")
    await update.message.reply_text("\n".join(lines))


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    users = _load_users()
    if not users:
        await update.message.reply_text("Пользователей пока нет.")
        return
    lines = ["📋 Все пользователи:"]
    for uid, data in users.items():
        name = data.get("first_name", "")
        lines.append(f"{uid}: {name}")
    await update.message.reply_text("\n".join(lines))


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /info <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный user_id.")
        return
    users = _load_users()
    uid = str(target_id)
    data = users.get(uid)
    if not data:
        await update.message.reply_text("Пользователь не найден.")
        return
    last_seen = data.get("last_seen", 0)
    last_seen_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_seen)) if last_seen else "нет"
    text = (
        f"ℹ️ Информация о пользователе {uid}:\n\n"
        f"Имя: {data.get('first_name', '')}\n"
        f"Запросов: {data.get('request_count', 0)}\n"
        f"Последняя активность: {last_seen_str}"
    )
    await update.message.reply_text(text)


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /ban <user_id> [причина]")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный user_id.")
        return
    reason = " ".join(context.args[1:]) or "админ"
    _ban_user(target_id, reason)
    await update.message.reply_text(f"✅ Пользователь {target_id} забанен. Причина: {reason}")


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /unban <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный user_id.")
        return
    _unban_user(target_id)
    await update.message.reply_text(f"✅ Пользователь {target_id} разбанен.")
    # Notify user
    try:
        await context.bot.send_message(chat_id=target_id, text="✅ Ваш бан снят. Вы снова можете пользоваться ботом.")
    except Exception:
        pass


async def banned_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    bans = _load_bans()
    if not bans:
        await update.message.reply_text("Заблокированных нет.")
        return
    now = int(time.time())
    lines = ["🚨 Заблокированные:"]
    for uid, data in bans.items():
        until = data.get("until", 0)
        reason = data.get("reason", "")
        if until > now:
            remaining = int((until - now) // 60)
            lines.append(f"{uid}: {reason} (осталось {remaining} мин)")
    await update.message.reply_text("\n".join(lines))


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    qsize = download_queue.qsize()
    active = MAX_CONCURRENT - download_sem._value
    await update.message.reply_text(f"📦 Очередь: {qsize} задач\n🔧 Активных загрузок: {active}/{MAX_CONCURRENT}")


async def limits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    text = (
        f"⚙️ Текущие лимиты:\n\n"
        f"MAX_CONCURRENT: {MAX_CONCURRENT}\n"
        f"MAX_PER_MINUTE: {MAX_PER_MINUTE}\n"
        f"SPAM_THRESHOLD: {SPAM_THRESHOLD}\n"
        f"SPAM_BAN_MINUTES: {SPAM_BAN_MINUTES}"
    )
    await update.message.reply_text(text)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /broadcast <сообщение>")
        return
    message_text = " ".join(context.args)
    users = _load_users()
    if not users:
        await update.message.reply_text("Нет пользователей для рассылки.")
        return
    success = 0
    fail = 0
    for uid in users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=message_text)
            success += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"✅ Рассылка завершена.\nУспешно: {success}\nОшибок: {fail}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else None
    if not _is_admin(user_id):
        return

    downloads_dir = Path("downloads")
    files_count = 0
    bytes_total = 0
    if downloads_dir.exists() and downloads_dir.is_dir():
        for p in downloads_dir.iterdir():
            if p.is_file():
                files_count += 1
                bytes_total += p.stat().st_size

    size_mb = bytes_total / (1024 * 1024)
    stats_text = (
        f"📊 Статистика бота\n\n"
        f"Всего запросов: {STATS['requests_total']}\n"
        f"Успешно: {STATS['success_total']}\n"
        f"Ошибок: {STATS['fail_total']}\n\n"
        f"TikTok: {STATS['platform']['tiktok']}\n"
        f"YouTube: {STATS['platform']['youtube']}\n\n"
        f"Файлов в downloads: {files_count}\n"
        f"Размер downloads: {size_mb:.1f} MB"
    )
    await update.message.reply_text(stats_text)


async def cleanup_downloads_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    downloads_dir = Path("downloads")
    if not downloads_dir.exists() or not downloads_dir.is_dir():
        return

    now = time.time()
    cutoff = now - 60 * 60  # 1 час

    removed = 0
    for p in downloads_dir.iterdir():
        if not p.is_file():
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue

    if removed:
        logger.info("Автоочистка downloads: удалено файлов: %s", removed)


async def cleanup_task():
    """Фоновая задача: раз в 30 минут чистить downloads."""
    await asyncio.sleep(60)  # первый запуск через 1 минуту
    while True:
        await cleanup_downloads_job(None)
        await asyncio.sleep(60 * 30)  # каждые 30 минут


def main() -> None:
    """Start the bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("No TELEGRAM_BOT_TOKEN found in environment variables!")
        return

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("adminhelp", adminhelp_command))
    app.add_handler(CommandHandler("topusers", topusers_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("banned", banned_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("limits", limits_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запускается...")
    
    # Запускаем фоновые задачи
    async def start_background_tasks():
        loop = asyncio.get_running_loop()
        loop.create_task(worker())
        loop.create_task(cleanup_task())
    
    # Создаем и запускаем event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Запускаем фоновые задачи
    loop.run_until_complete(start_background_tasks())
    
    # Запускаем бота
    app.run_polling()


if __name__ == "__main__":
    main()
