# Telegram Video Bot

Бот для скачивания видео из TikTok и YouTube Shorts.

## Развертывание на PythonAnywhere

### 1. Создание аккаунта
1. Зарегистрируйтесь на [PythonAnywhere](https://www.pythonanywhere.com/)
2. Подтвердите email

### 2. Создание нового Web App
1. Перейдите в Dashboard → Web tab
2. Нажмите "Add a new web app"
3. Выберите:
   - Framework: **Manual Configuration**
   - Python version: **Python 3.10+**
   - Domain: оставьте по умолчанию

### 3. Загрузка файлов
1. В Dashboard → Files → Upload files
2. Загрузите все файлы проекта:
   - `bot.py`
   - `video_downloader.py`
   - `requirements.txt`
   - `.env` (с токеном бота)

### 4. Установка зависимостей
1. Откройте Bash console (Dashboard → Consoles → Bash)
2. Выполните команды:
```bash
pip install -r requirements.txt
```

### 5. Настройка переменных окружения
1. В Web tab → WSGI configuration file
2. Замените содержимое на:
```python
import os
import sys
from bot import main

# Добавляем путь к проекту
path = '/home/yourusername/mysite'
if path not in sys.path:
    sys.path.append(path)

# Устанавливаем переменные окружения
os.environ['TELEGRAM_BOT_TOKEN'] = 'your_bot_token'
os.environ['ADMIN_IDS'] = 'your_admin_id'

# Запускаем бота
def application(environ, start_response):
    main()
```

### 6. Настройка Background Task
1. Перейдите в Tasks tab
2. Создайте новую задачу:
   - Command: `cd /home/yourusername/mysite && python bot.py`
   - Schedule: `Always on (24x7)`
   - Timer: `Every minute`

### 7. Запуск бота
1. Перезагрузите Web App (Web tab → Reload)
2. Запустите Background Task
3. Проверьте работу бота в Telegram

## Альтернативные варианты

### Render.com
1. Создайте GitHub репозиторий с проектом
2. Зарегистрируйтесь на Render
3. Подключите GitHub репозиторий
4. Создайте Web Service
5. Добавьте переменные окружения в Render Dashboard

### Railway
1. Установите Railway CLI
2. Выполните `railway login`
3. В папке проекта: `railway up`
4. Добавьте переменные окружения в Railway Dashboard

## Проверка работы
После развертывания отправьте боту тестовое сообщение. Бот должен ответить и начать обрабатывать ссылки на видео.
