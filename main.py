"""
Точка входа для запуска бота из корня проекта.
Использование: python main.py
"""
import asyncio
from bot.main import main

if __name__ == "__main__":
    asyncio.run(main())

