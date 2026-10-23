import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from newsbot import app as newsbot_app
from newsbot import storage
from newsbot.backup import backup_db
from newsbot.config import Settings
from conftest import FakeBot

SETTINGS = Settings(
    telegram_bot_token='123:abc', telegram_chat_id='-100', admin_chat_id='42',
    allowed_user_ids=frozenset({42}), yandex_folder_id=None, yandex_api_key=None, gnews_api_key=None,
    collect_interval_minutes=15,
)


def test_build_schedules_collect_and_backup():
    application = newsbot_app.build(SETTINGS)
    jobs = {j.name: j for j in application.job_queue.jobs()}
    assert set(jobs) == {'collect', 'backup'}
    assert jobs['collect'].job.trigger.interval.total_seconds() == 15 * 60
    assert jobs['collect'].job.max_instances == 1
    assert application.bot_data['allowed_user_ids'] == frozenset({42})


def test_build_requires_channel():
    with pytest.raises(ValueError):
        newsbot_app.build(Settings('123:abc', None, None, frozenset(), None, None, None))


def test_collect_job_reports_failure_to_admin(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError('лента сломалась')
    monkeypatch.setattr(newsbot_app.collector, 'run', boom)
    bot = FakeBot()
    asyncio.run(newsbot_app.collect_job(SimpleNamespace(bot=bot, bot_data={'settings': SETTINGS})))
    assert bot.sent == [{'chat_id': '42', 'text': '❌ Сбор новостей упал: лента сломалась'}]


def test_backup_copies_db_and_rotates(tmp_path):
    storage.mark_article_sent('https://ex.ru/1', 'T', 'S', 'h')
    dest = tmp_path / 'backups'
    for i in range(3):
        (dest).mkdir(exist_ok=True)
        (dest / f'news-2026010{i}-000000.db').write_bytes(b'old')
    path = backup_db(str(dest), keep=2)
    files = sorted(p.name for p in dest.glob('news-*.db'))
    assert len(files) == 2 and path.name in files
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT url FROM sent_articles').fetchall() == [('https://ex.ru/1',)]


def test_weekly_backup_sent_to_admin(monkeypatch, tmp_path):
    monkeypatch.setenv('BACKUP_DIR', str(tmp_path / 'b'))
    monkeypatch.setattr(newsbot_app, 'WEEKLY_BACKUP_DAY', newsbot_app.datetime.datetime.now(newsbot_app.MSK).isoweekday() % 7)
    sent = []

    class DocBot(FakeBot):
        async def send_document(self, **kwargs):
            sent.append((kwargs['chat_id'], kwargs['filename'], kwargs['document'].read(16)))

    asyncio.run(newsbot_app.backup_job(SimpleNamespace(bot=DocBot(), bot_data={'settings': SETTINGS})))
    assert len(sent) == 1 and sent[0][0] == '42' and sent[0][2].startswith(b'SQLite format 3')


def test_default_collect_interval_is_two_hours():
    from newsbot.config import load_settings
    assert load_settings().collect_interval_minutes == 120
