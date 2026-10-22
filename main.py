"""Точка входа фонового сбора новостей (запускается по расписанию в GitHub Actions)."""
import asyncio
import sys

from newsbot import collector

if __name__ == '__main__':
    try:
        asyncio.run(collector.run())
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)
