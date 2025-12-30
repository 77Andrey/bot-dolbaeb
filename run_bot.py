#!/usr/bin/env python3
"""
Запуск бота для продакшена
"""
import os
import sys
import asyncio
from bot import main

if __name__ == "__main__":
    # Устанавливаем переменные окружения если не установлены
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        print("Ошибка: TELEGRAM_BOT_TOKEN не найден!")
        sys.exit(1)
    
    print("Запуск Telegram Video Bot...")
    main()
