#!/usr/bin/env python3
"""Точка входа ежедневного отчёта по оценкам (GitHub Actions)."""
import logging

from newsbot.learning import adjust_filters

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    adjust_filters()
