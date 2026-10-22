"""Работа с SQLite: отправленные статьи, эмбеддинги, статистика, оценки, динамические настройки."""
import sqlite3
import json
from contextlib import contextmanager

from newsbot.config import db_path

DEFAULT_CONFIG = {
    'keywords': '["Бартер","БРИКС","Китай","Импорт","Санкции","Экономика","ВЭД","ЕАЭС","Логистика","Таможня","Пошлины","Транзит","Параллельный импорт","КНР"]',
    'excluded_keywords': '["нефть","газ","алюминий","сырьё","металл","добыча","уголь"]',
    'semantic_threshold': '0.55',
    'max_articles_to_send': '30',
    'max_hours_old': '24',
}


@contextmanager
def connect():
    """Соединение с БД: коммит при успешном выходе, закрытие всегда."""
    conn = sqlite3.connect(db_path())
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Создаёт все таблицы и индексы при первом запуске, добавляет колонку hash если её нет."""
    with connect() as conn:
        cursor = conn.cursor()

        # ---- Таблица отправленных статей ----
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                source TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        columns = {row[1] for row in cursor.execute('PRAGMA table_info(sent_articles)')}
        if 'hash' not in columns:
            cursor.execute('ALTER TABLE sent_articles ADD COLUMN hash TEXT')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_url ON sent_articles (url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_title ON sent_articles (title)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sent_at ON sent_articles (sent_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_hash ON sent_articles (hash)')

        # ---- Кэш эмбеддингов ----
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS article_embeddings (
                hash TEXT PRIMARY KEY,
                embedding TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON article_embeddings (created_at)')

        # ---- Эталонные векторы ----
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS topic_embeddings (
                group_name TEXT PRIMARY KEY,
                embedding TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ---- Статистика сессий ----
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_found INTEGER,
                total_filtered INTEGER,
                total_sent INTEGER,
                semantic_passed INTEGER,
                semantic_failed INTEGER,
                avg_similarity REAL,
                threshold REAL,
                extra_data TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON session_stats (timestamp)')

        # ---- Обратная связь ----
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                response_text TEXT,
                rating INTEGER,   -- 1 = like, -1 = dislike
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ---- Динамические настройки ----
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        cursor.executemany('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', DEFAULT_CONFIG.items())
        _migrate_config(cursor)


# Слова, которые раньше отсеивались исключением «газ» как подстрокой.
# Фильтр по леммам их не ловит (и не ловит «газету»), поэтому добавляем явно — один раз.
_EXCLUDED_ADDED_V2 = ["Газпром", "газовый", "газопровод"]
# Ключевые слова, добавленные по запросу редакции.
_KEYWORDS_ADDED_V3 = ["КНР"]


def _append_missing(cursor, key: str, words: list):
    row = cursor.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    current = json.loads(row[0])
    present = {w.lower() for w in current}
    current += [w for w in words if w.lower() not in present]
    cursor.execute("REPLACE INTO config (key, value) VALUES (?, ?)", (key, json.dumps(current, ensure_ascii=False)))


def _migrate_config(cursor):
    row = cursor.execute("SELECT value FROM config WHERE key = 'config_version'").fetchone()
    version = int(row[0]) if row else 1
    if version < 2:
        row = cursor.execute("SELECT value FROM config WHERE key = 'excluded_keywords'").fetchone()
        if any(w.lower() == 'газ' for w in json.loads(row[0])):
            _append_missing(cursor, 'excluded_keywords', _EXCLUDED_ADDED_V2)
    if version < 3:
        _append_missing(cursor, 'keywords', _KEYWORDS_ADDED_V3)
        cursor.execute("REPLACE INTO config (key, value) VALUES ('config_version', '3')")


# ============================================================
# ОТПРАВЛЕННЫЕ СТАТЬИ
# ============================================================

def is_url_sent(*urls: str) -> bool:
    """Проверяет, отправлялась ли статья с такой ссылкой когда-либо."""
    urls = [u for u in urls if u]
    if not urls:
        return False
    with connect() as conn:
        row = conn.execute(
            f'SELECT 1 FROM sent_articles WHERE url IN ({",".join("?" * len(urls))}) LIMIT 1',
            urls
        ).fetchone()
    return row is not None

def is_hash_sent_recently(hash_value: str, hours: int = 48) -> bool:
    """Проверяет, отправлялся ли такой хеш заголовка за последние N часов (окно скользящее, а не «сегодня»)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_articles WHERE hash = ? AND sent_at >= datetime('now', ?) LIMIT 1",
            (hash_value, f'-{hours} hours')
        ).fetchone()
    return row is not None

def mark_article_sent(url: str, title: str, source: str = '', hash_value: str = ''):
    """Сохраняет отправленную статью с хешем."""
    with connect() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO sent_articles (url, title, source, hash) VALUES (?, ?, ?, ?)',
            (url, title, source, hash_value)
        )

def get_total_sent() -> int:
    """Возвращает общее количество отправленных статей."""
    with connect() as conn:
        return conn.execute('SELECT COUNT(*) FROM sent_articles').fetchone()[0]


# ============================================================
# ЭМБЕДДИНГИ
# ============================================================

def get_embedding(text_hash: str):
    """Загружает эмбеддинг из кэша по хешу."""
    with connect() as conn:
        row = conn.execute('SELECT embedding FROM article_embeddings WHERE hash = ?', (text_hash,)).fetchone()
    return json.loads(row[0]) if row else None

def save_embedding(text_hash: str, embedding: list):
    """Сохраняет эмбеддинг в кэш."""
    with connect() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO article_embeddings (hash, embedding) VALUES (?, ?)',
            (text_hash, json.dumps(embedding))
        )

def get_all_topic_embeddings():
    """Возвращает все эталонные векторы (словарь group_name -> embedding)."""
    with connect() as conn:
        rows = conn.execute('SELECT group_name, embedding FROM topic_embeddings').fetchall()
    return {name: json.loads(emb_json) for name, emb_json in rows}

def save_topic_embedding(group_name: str, embedding: list):
    """Сохраняет эталонный вектор для группы."""
    with connect() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO topic_embeddings (group_name, embedding) VALUES (?, ?)',
            (group_name, json.dumps(embedding))
        )


# ============================================================
# СТАТИСТИКА СЕССИЙ
# ============================================================

def save_session_stats(
    total_found: int,
    total_filtered: int,
    total_sent: int,
    semantic_passed: int,
    semantic_failed: int,
    avg_similarity: float,
    threshold: float,
    extra_data: dict = None
):
    """Сохраняет статистику сессии в БД."""
    with connect() as conn:
        conn.execute(
            '''
            INSERT INTO session_stats (
                total_found, total_filtered, total_sent,
                semantic_passed, semantic_failed, avg_similarity,
                threshold, extra_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                total_found,
                total_filtered,
                total_sent,
                semantic_passed,
                semantic_failed,
                avg_similarity,
                threshold,
                json.dumps(extra_data, ensure_ascii=False) if extra_data else None
            )
        )


# ============================================================
# ОБРАТНАЯ СВЯЗЬ
# ============================================================

def save_feedback(user_id: int, response_text: str, rating: int):
    """Сохраняет оценку пользователя (1 — like, -1 — dislike)."""
    with connect() as conn:
        conn.execute(
            'INSERT INTO user_feedback (user_id, response_text, rating) VALUES (?, ?, ?)',
            (user_id, response_text[:500], rating)
        )

def get_recent_feedback_stats(days: int = 7):
    """Средняя оценка (от -1 до 1) и количество оценок за последние N дней."""
    with connect() as conn:
        avg_rating, count = conn.execute(
            "SELECT AVG(rating), COUNT(rating) FROM user_feedback WHERE created_at > datetime('now', ?)",
            (f'-{days} days',)
        ).fetchone()
    return avg_rating or 0.0, count or 0


# ============================================================
# ДИНАМИЧЕСКИЕ НАСТРОЙКИ
# ============================================================

def get_config(key: str, default=None):
    """Возвращает значение настройки из таблицы config."""
    with connect() as conn:
        row = conn.execute('SELECT value FROM config WHERE key = ?', (key,)).fetchone()
    return row[0] if row else default

def set_config(key: str, value):
    """Сохраняет значение настройки в таблицу config."""
    with connect() as conn:
        conn.execute('REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))

def get_keywords():
    return json.loads(get_config('keywords', DEFAULT_CONFIG['keywords']))

def set_keywords(keywords: list):
    set_config('keywords', json.dumps(keywords, ensure_ascii=False))

def get_excluded_keywords():
    return json.loads(get_config('excluded_keywords', DEFAULT_CONFIG['excluded_keywords']))

def set_excluded_keywords(keywords: list):
    set_config('excluded_keywords', json.dumps(keywords, ensure_ascii=False))

def get_semantic_threshold():
    return float(get_config('semantic_threshold', DEFAULT_CONFIG['semantic_threshold']))

def set_semantic_threshold(threshold: float):
    set_config('semantic_threshold', str(threshold))

def get_max_articles_to_send():
    return int(get_config('max_articles_to_send', DEFAULT_CONFIG['max_articles_to_send']))

def set_max_articles_to_send(value: int):
    set_config('max_articles_to_send', str(value))

def get_max_hours_old():
    return int(get_config('max_hours_old', DEFAULT_CONFIG['max_hours_old']))

def set_max_hours_old(value: int):
    set_config('max_hours_old', str(value))
