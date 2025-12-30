# 🚀 Развертывание на Render.com

## Подготовка

1. **Зарегистрируйся** на [render.com](https://render.com)
2. **Подключи GitHub** аккаунт
3. **Убедись** что репозиторий `77Andrey/bot-dolbaeb` публичный

## Создание Background Worker

### 1. Новый Web Service
- Нажми **New +** → **Web Service**
- Выбери репозиторий: `77Andrey/bot-dolbaeb`
- Имя: `tiktok-video-bot`
- Environment: **Docker**

### 2. Настройки сборки
```
Build Context: /
Dockerfile Path: ./Dockerfile
Instance Type: Free
```

### 3. Настройки запуска
```
Start Command: python run_bot.py
Health Check Path: / (не нужно для background worker)
```

### 4. Переключение на Background Worker
После создания Web Service:
- Нажми на сервис → **Settings**
- Измени **Type** на **Background Worker**
- Нажми **Save Changes**

## Переменные окружения (Environment Variables)

В **Settings → Environment** добавь:

```
TELEGRAM_BOT_TOKEN=8504400803:AAGLJpgD1l043FFBodiCVlCFMfvtlN0tFGs
ADMIN_IDS=2089005500
MAX_CONCURRENT=5
MAX_PER_MINUTE=3
SPAM_THRESHOLD=10
SPAM_BAN_MINUTES=5
PYTHONUNBUFFERED=1
```

## Регион
Выбери **Oregon (US West)** - ближе к Telegram API.

## Проверка работы

### 1. Логи
- Зайди в **Logs** вкладку
- Ищи сообщения:
```
Бот запускается...
Пробуем скачать TikTok через yt-dlp: ...
Успешно загружено через yt-dlp: ...
```

### 2. Тестирование
Отправь боту в Telegram:
```
/start
https://vt.tiktok.com/ZS5FVSwBo/
```

## Если не работает

### Проверь логи на ошибки:
```
ModuleNotFoundError - установи зависимости
TELEGRAM_BOT_TOKEN не найден - добавь переменную
Event loop error - проблема с asyncio
```

### Пересборка:
```bash
# В локальном терминале
git add .
git commit -m "fix: update for render"
git push origin main
```

Render автоматически пересоберет сервис.

## Оптимизация для производительности

### В Environment Variables добавь:
```
MAX_CONCURRENT=3
MAX_PER_MINUTE=2
```

### Для стабильности:
- Используй **Paid tier** если высокая нагрузка
- Мониторь **Usage** в Dashboard
- Проверь **Cron jobs** для автоочистки

## Альтернатива: Manual Deploy

Если автоматический деплой не работает:

1. **Manual Build**:
```bash
# В Render Console
git clone https://github.com/77Andrey/bot-dolbaeb.git
cd bot-dolbaeb
docker build -t tiktok-bot .
docker run -d --name bot \
  -e TELEGRAM_BOT_TOKEN="8504400803:AAGLJpgD1l043FFBodiCVlCFMfvtlN0tFGs" \
  -e ADMIN_IDS="2089005500" \
  tiktok-bot
```

## Мониторинг

### В Render Dashboard:
- **Metrics** - CPU, Memory usage
- **Logs** - реальное время
- **Events** - деплои и перезапуски

### В Telegram:
- `/stats` - статистика бота
- `/queue` - состояние очереди

## Резервное копирование

Данные бота:
- `users.json` - пользователи
- `bans.json` - баны

Автоматически сохраняются в GitHub, но можно добавить backup:
```python
# В bot.py добавить
import shutil
shutil.copy2('users.json', f'users_backup_{int(time.time())}.json')
```

---

**Готово!** После этих настроек бот будет работать 24/7 на Render.com.
