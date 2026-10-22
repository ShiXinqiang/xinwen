import sqlite3
import json

DB_FILE = 'news.db'

def init_db():
    """Создаёт все таблицы и индексы при первом запуске, добавляет колонку hash если её нет."""
    conn = sqlite3.connect(DB_FILE)
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

    # ---- Добавляем колонку hash, если её нет ----
    try:
        cursor.execute('ALTER TABLE sent_articles ADD COLUMN hash TEXT')
        print("✅ Колонка 'hash' добавлена в sent_articles")
    except sqlite3.OperationalError:
        pass

    # ---- Индексы для sent_articles ----
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_url ON sent_articles (url)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_title ON sent_articles (title)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sent_at ON sent_articles (sent_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hash ON sent_articles (hash)')

    # ---- Таблица кэша эмбеддингов ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS article_embeddings (
            hash TEXT PRIMARY KEY,
            embedding TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON article_embeddings (created_at)')

    # ---- Таблица эталонных векторов ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS topic_embeddings (
            group_name TEXT PRIMARY KEY,
            embedding TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ---- Таблица статистики сессий ----
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

    # ---- Таблица обратной связи (для обучения) ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            response_text TEXT,
            rating INTEGER,   -- 1 = like, -1 = dislike
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ---- Таблица конфигурации (динамические настройки) ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Заполняем значениями по умолчанию (если ещё не заданы)
    defaults = [
        ('keywords', '["Бартер","БРИКС","Китай","Импорт","Санкции","Экономика","ВЭД","ЕАЭС","Логистика","Таможня","Пошлины","Транзит","Параллельный импорт"]'),
        ('excluded_keywords', '["нефть","газ","алюминий","сырьё","металл","добыча","уголь"]'),
        ('semantic_threshold', '0.55'),
        ('max_articles_to_send', '30'),
        ('max_hours_old', '12'),
    ]
    for key, value in defaults:
        cursor.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (key, value))

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована (все таблицы созданы).")


# ============================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ОТПРАВЛЕННЫМИ СТАТЬЯМИ
# ============================================================

def is_hash_sent_today(hash_value: str) -> bool:
    """Проверяет, был ли уже сегодня отправлен хеш."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT 1 FROM sent_articles WHERE hash = ? AND date(sent_at) = date("now")',
        (hash_value,)
    )
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def mark_article_sent(url: str, title: str, source: str = '', hash_value: str = ''):
    """Сохраняет отправленную статью с хешем."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR IGNORE INTO sent_articles (url, title, source, hash) VALUES (?, ?, ?, ?)',
        (url, title, source, hash_value)
    )
    conn.commit()
    conn.close()

def get_total_sent() -> int:
    """Возвращает общее количество отправленных статей."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM sent_articles')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def clear_old_entries(days: int = 7):
    """Удаляет записи старше указанного количества дней."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM sent_articles WHERE sent_at < datetime("now", ?)',
        (f'-{days} days',)
    )
    conn.commit()
    conn.close()


# ============================================================
# ФУНКЦИИ ДЛЯ ЭМБЕДДИНГОВ
# ============================================================

def get_embedding(text_hash: str):
    """Загружает эмбеддинг из кэша по хешу."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT embedding FROM article_embeddings WHERE hash = ?', (text_hash,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

def save_embedding(text_hash: str, embedding: list):
    """Сохраняет эмбеддинг в кэш."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR REPLACE INTO article_embeddings (hash, embedding) VALUES (?, ?)',
        (text_hash, json.dumps(embedding))
    )
    conn.commit()
    conn.close()


# ============================================================
# ФУНКЦИИ ДЛЯ ЭТАЛОННЫХ ВЕКТОРОВ
# ============================================================

def get_all_topic_embeddings():
    """Возвращает все сохранённые эталонные векторы (словарь group_name -> embedding)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT group_name, embedding FROM topic_embeddings')
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for name, emb_json in rows:
        result[name] = json.loads(emb_json)
    return result

def save_topic_embedding(group_name: str, embedding: list):
    """Сохраняет эталонный вектор для группы."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR REPLACE INTO topic_embeddings (group_name, embedding) VALUES (?, ?)',
        (group_name, json.dumps(embedding))
    )
    conn.commit()
    conn.close()

def clear_topic_embeddings():
    """Удаляет все эталонные векторы."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM topic_embeddings')
    conn.commit()
    conn.close()


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
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
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
            json.dumps(extra_data) if extra_data else None
        )
    )
    conn.commit()
    conn.close()


# ============================================================
# ОБРАТНАЯ СВЯЗЬ (ДЛЯ ОБУЧЕНИЯ)
# ============================================================

def save_feedback(user_id: int, response_text: str, rating: int):
    """Сохраняет оценку пользователя в таблицу user_feedback."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO user_feedback (user_id, response_text, rating) VALUES (?, ?, ?)',
        (user_id, response_text[:500], rating)
    )
    conn.commit()
    conn.close()

def get_recent_feedback_stats(days: int = 7):
    """
    Возвращает среднюю оценку и количество оценок за последние N дней.
    Используется для самообучения.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT AVG(rating), COUNT(rating)
        FROM user_feedback
        WHERE created_at > datetime('now', ?)
    ''', (f'-{days} days',))
    avg_rating, count = cursor.fetchone()
    conn.close()
    return avg_rating or 0.0, count or 0

def get_feedback_texts(days: int = 7):
    """
    Возвращает два списка: тексты с положительным рейтингом и с отрицательным.
    Используется для анализа слов в adjust_filters.py.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT response_text, rating
        FROM user_feedback
        WHERE created_at > datetime('now', ?)
        AND rating != 0
    ''', (f'-{days} days',))
    rows = cursor.fetchall()
    conn.close()
    good = [row[0] for row in rows if row[1] > 0]
    bad = [row[0] for row in rows if row[1] < 0]
    return good, bad


# ============================================================
# КОНФИГУРАЦИЯ (ДИНАМИЧЕСКИЕ НАСТРОЙКИ)
# ============================================================

def get_config(key: str, default=None):
    """Возвращает значение настройки из таблицы config."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return default

def set_config(key: str, value):
    """Сохраняет значение настройки в таблицу config."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

# Удобные обёртки для конкретных настроек
def get_keywords():
    val = get_config('keywords', '[]')
    return json.loads(val)

def set_keywords(keywords: list):
    set_config('keywords', json.dumps(keywords, ensure_ascii=False))

def get_excluded_keywords():
    val = get_config('excluded_keywords', '[]')
    return json.loads(val)

def set_excluded_keywords(keywords: list):
    set_config('excluded_keywords', json.dumps(keywords, ensure_ascii=False))

def get_semantic_threshold():
    val = get_config('semantic_threshold', '0.55')
    return float(val)

def set_semantic_threshold(threshold: float):
    set_config('semantic_threshold', str(threshold))

def get_max_articles_to_send():
    val = get_config('max_articles_to_send', '30')
    return int(val)

def set_max_articles_to_send(value: int):
    set_config('max_articles_to_send', str(value))

def get_max_hours_old():
    val = get_config('max_hours_old', '24')
    return int(val)

def set_max_hours_old(value: int):
    set_config('max_hours_old', str(value))
