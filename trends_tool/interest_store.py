"""从 Turso 读取热度监控关键词（与 sitemap 同一库，表 interest_keywords）。

连接：TURSO_DATABASE_URL / TURSO_AUTH_TOKEN
表结构见 schema.sql。
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env')

_SELECT_ACTIVE = """
SELECT keyword, geo, timeframe
FROM interest_keywords
WHERE active = 1
ORDER BY keyword
"""


def _connect(url, auth_token, db_path=None):
    if db_path is not None:
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn, 'sqlite'

    import libsql

    raw = libsql.connect(database=url, auth_token=auth_token)
    return raw, 'turso'


def _row_keyword(row):
    if isinstance(row, dict):
        return {
            'keyword': (row.get('keyword') or '').strip(),
            'geo': (row.get('geo') or '').strip(),
            'timeframe': (row.get('timeframe') or '').strip(),
        }
    desc = getattr(row, 'keys', None)
    if callable(desc):
        data = {k: row[k] for k in row.keys()}
        return _row_keyword(data)
    return {
        'keyword': (row[0] or '').strip(),
        'geo': (row[1] or '').strip() if len(row) > 1 else '',
        'timeframe': (row[2] or '').strip() if len(row) > 2 else '',
    }


def load_interest_keywords(db_path=None):
    """返回启用中的监控目标：[{keyword, geo, timeframe}, ...]。"""
    url = os.environ.get('TURSO_DATABASE_URL', '').strip()
    token = os.environ.get('TURSO_AUTH_TOKEN', '').strip()
    if db_path is None and not (url and token):
        raise RuntimeError(
            '未配置数据库。请设置 TURSO_DATABASE_URL 和 TURSO_AUTH_TOKEN '
            '（可写入项目根目录 .env）'
        )

    conn, backend = _connect(url, token, db_path=db_path)
    try:
        rows = conn.execute(_SELECT_ACTIVE).fetchall()
    finally:
        conn.close()

    targets = []
    for row in rows:
        item = _row_keyword(row)
        if item['keyword']:
            targets.append(item)

    logging.info(
        "Loaded %s active interest keywords from %s",
        len(targets),
        db_path or url,
    )
    return targets
