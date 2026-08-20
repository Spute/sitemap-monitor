"""存储：以 slug 为中心，支撑跨站查询与爆发热度。

生产环境连接 Turso（环境变量 TURSO_DATABASE_URL / TURSO_AUTH_TOKEN）；
测试与离线调试可传入本地 SQLite 路径。
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
_WRITE_CHUNK = 400
_REFRESH_CHUNK = 200

load_dotenv(_ROOT / '.env')


class _NamedRow(dict):
    """让 libsql 的 tuple 行也能用 row['col'] / dict(row)。"""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _LibsqlCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def _wrap(self, row):
        if row is None:
            return None
        desc = self._cursor.description
        if not desc:
            return row
        return _NamedRow((col[0], value) for col, value in zip(desc, row))

    def fetchone(self):
        return self._wrap(self._cursor.fetchone())

    def fetchall(self):
        return [self._wrap(row) for row in self._cursor.fetchall()]


class _LibsqlConn:
    """补齐 libsql 与 sqlite3 的行访问差异。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        return _LibsqlCursor(self._conn.execute(sql, params))

    def executemany(self, sql, seq_of_params):
        return self._conn.executemany(sql, seq_of_params)

    def executescript(self, script):
        return self._conn.executescript(script)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def is_store_auth_error(exc):
    """Turso / Hrana 鉴权或协议层失败（token 无效、会话损坏等）。"""
    text = str(exc).lower()
    return (
        'invalid token' in text
        or 'unauthorized' in text
        or ('hrana' in text and 'protocol error' in text)
        or ('hrana' in text and '401' in text)
    )


def reopen_store(store):
    """关闭坏掉的会话并按原参数重连。"""
    db_path = store.db_path
    url = store._url
    auth_token = store._auth_token
    check_same_thread = store._check_same_thread
    try:
        store.close()
    except Exception:
        pass
    return GameStore(
        db_path,
        url=url,
        auth_token=auth_token,
        check_same_thread=check_same_thread,
    )


def open_store(*, db_path=None, check_same_thread=True):
    """打开存储。显式 db_path 走本地 SQLite；否则读 Turso 环境变量。"""
    if db_path is not None:
        return GameStore(db_path, check_same_thread=check_same_thread)
    url = os.environ.get('TURSO_DATABASE_URL', '').strip()
    token = os.environ.get('TURSO_AUTH_TOKEN', '').strip()
    if url and token:
        return GameStore(
            url=url,
            auth_token=token,
            check_same_thread=check_same_thread,
        )
    raise RuntimeError(
        '未配置数据库。请设置环境变量 TURSO_DATABASE_URL 和 TURSO_AUTH_TOKEN '
        '（可写入项目根目录 .env）'
    )


class GameStore:
    """三表模型：
    - sightings: 某站收录某 slug（存量，兼做变更基线）
    - events: 某日某站首次新增（爆发窗口用）
    - games: 汇总 site_count / heat_score
    """

    def __init__(
        self,
        db_path=None,
        *,
        url=None,
        auth_token=None,
        check_same_thread=True,
    ):
        self._url = url
        self._auth_token = auth_token
        self._check_same_thread = check_same_thread
        if url:
            if not auth_token:
                raise ValueError('Turso 连接需要 auth_token')
            import libsql

            raw = libsql.connect(
                database=url,
                auth_token=auth_token,
                _check_same_thread=check_same_thread,
            )
            self.conn = _LibsqlConn(raw)
            self.location = url
            self.backend = 'turso'
            self.db_path = None
        elif db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(
                path,
                check_same_thread=check_same_thread,
            )
            self.conn.row_factory = sqlite3.Row
            self.location = str(path.resolve())
            self.backend = 'sqlite'
            self.db_path = path
        else:
            raise ValueError('需要本地 db_path 或 Turso url / auth_token')
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sightings (
                slug TEXT NOT NULL,
                site TEXT NOT NULL,
                url TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (slug, site)
            );
            CREATE TABLE IF NOT EXISTS events (
                date TEXT NOT NULL,
                slug TEXT NOT NULL,
                site TEXT NOT NULL,
                url TEXT NOT NULL,
                PRIMARY KEY (date, slug, site)
            );
            CREATE TABLE IF NOT EXISTS games (
                slug TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                site_count INTEGER NOT NULL DEFAULT 0,
                heat_score REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS site_sync (
                site TEXT PRIMARY KEY,
                last_sync TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
            CREATE INDEX IF NOT EXISTS idx_events_slug ON events(slug);
            CREATE INDEX IF NOT EXISTS idx_sightings_site ON sightings(site);
            CREATE INDEX IF NOT EXISTS idx_games_heat ON games(heat_score DESC);
            """
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def _executemany_chunked(self, sql, rows, chunk_size=_WRITE_CHUNK):
        if not rows:
            return
        for i in range(0, len(rows), chunk_size):
            self.conn.executemany(sql, rows[i : i + chunk_size])

    def site_has_sightings(self, site):
        """该站是否已有基线数据。"""
        row = self.conn.execute(
            'SELECT 1 FROM sightings WHERE site = ? LIMIT 1',
            (site,),
        ).fetchone()
        return row is not None

    def _slugs_for_site(self, site):
        rows = self.conn.execute(
            'SELECT slug FROM sightings WHERE site = ?',
            (site,),
        ).fetchall()
        return {row['slug'] for row in rows}

    def upsert_sighting(self, slug, site, url, today):
        """写入/更新收录关系。返回 True 表示该站首次见到此 slug。

        已存在的行不改 last_seen，避免每天全表更新（托管库额度）。
        """
        row = self.conn.execute(
            'SELECT first_seen FROM sightings WHERE slug = ? AND site = ?',
            (slug, site),
        ).fetchone()
        if row:
            return False
        self.conn.execute(
            'INSERT INTO sightings (slug, site, url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)',
            (slug, site, url, today, today),
        )
        return True

    def record_event(self, date, slug, site, url):
        """记录每日新增事件（用于爆发统计）。"""
        self.conn.execute(
            'INSERT OR IGNORE INTO events (date, slug, site, url) VALUES (?, ?, ?, ?)',
            (date, slug, site, url),
        )

    @staticmethod
    def window_cutoff(window_days):
        """近 window_days 个自然日（含今天）的起始日期 YYYY-MM-DD。"""
        days = max(int(window_days), 1)
        return (datetime.now() - timedelta(days=days - 1)).strftime('%Y-%m-%d')

    def refresh_game(self, slug, burst_window_days):
        """按 sightings + 近窗 events 重算单个 games 汇总行。"""
        self._refresh_games([slug], burst_window_days)

    def _refresh_games(self, slugs, burst_window_days):
        """批量重算 games 汇总行。"""
        unique = list(dict.fromkeys(slug for slug in slugs if slug))
        if not unique:
            return
        cutoff = self.window_cutoff(burst_window_days)
        for i in range(0, len(unique), _REFRESH_CHUNK):
            chunk = unique[i : i + _REFRESH_CHUNK]
            placeholders = ','.join('?' for _ in chunk)
            stats_rows = self.conn.execute(
                f"""
                SELECT slug,
                       MIN(first_seen) AS first_seen,
                       MAX(last_seen) AS last_seen,
                       COUNT(*) AS site_count
                FROM sightings
                WHERE slug IN ({placeholders})
                GROUP BY slug
                """,
                chunk,
            ).fetchall()
            burst_rows = self.conn.execute(
                f"""
                SELECT slug, COUNT(DISTINCT site) AS n
                FROM events
                WHERE slug IN ({placeholders}) AND date >= ?
                GROUP BY slug
                """,
                (*chunk, cutoff),
            ).fetchall()
            burst_map = {row['slug']: row['n'] for row in burst_rows}
            payload = []
            for stats in stats_rows:
                if not stats['site_count']:
                    continue
                heat = float(stats['site_count']) + 2.0 * float(
                    burst_map.get(stats['slug'], 0)
                )
                payload.append(
                    (
                        stats['slug'],
                        stats['first_seen'],
                        stats['last_seen'],
                        stats['site_count'],
                        heat,
                    )
                )
            self._executemany_chunked(
                """
                INSERT INTO games (slug, first_seen, last_seen, site_count, heat_score)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    first_seen = excluded.first_seen,
                    last_seen = excluded.last_seen,
                    site_count = excluded.site_count,
                    heat_score = excluded.heat_score
                """,
                payload,
            )

    def sync_site(self, site, entries, today, burst_window_days):
        """用当前 sitemap 游戏目录同步某站。

        - 该站尚无 sightings：建立基线，只写存量、不写 events（避免首跑全量告警）
        - 已有基线：首次见到的 slug 记入 events，并返回这些 slug
        - 已存在的收录不再每天改 last_seen
        """
        existing = self._slugs_for_site(site)
        baseline = not existing
        new_rows = []
        seen_new = set()
        for slug, url in entries:
            if slug in existing or slug in seen_new:
                continue
            seen_new.add(slug)
            new_rows.append((slug, site, url, today, today))

        if new_rows:
            self._executemany_chunked(
                """
                INSERT OR IGNORE INTO sightings
                    (slug, site, url, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                """,
                new_rows,
            )
            if not baseline:
                self._executemany_chunked(
                    """
                    INSERT OR IGNORE INTO events (date, slug, site, url)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (today, slug, site, url)
                        for slug, site, url, _, _ in new_rows
                    ],
                )
            self._refresh_games([row[0] for row in new_rows], burst_window_days)

        self.conn.execute(
            """
            INSERT INTO site_sync (site, last_sync) VALUES (?, ?)
            ON CONFLICT(site) DO UPDATE SET last_sync = excluded.last_sync
            """,
            (site, today),
        )
        self.conn.commit()
        return [] if baseline else [row[0] for row in new_rows]

    def burst_games(self, window_days, threshold):
        """近 window_days 个自然日（含今天）内，新增站点数 ≥ threshold 的游戏词。

        额外附带关键词维度信息（飞书/API 共用，均只看近窗 events）：
        - first_site / first_seen / first_url：近窗内最早新增的站点、日期与 URL
        - today_sites：今天新增的站点数
        - site_count：截止今天累计收录站点数（全量）
        """
        today = datetime.now().strftime('%Y-%m-%d')
        cutoff = self.window_cutoff(window_days)
        rows = self.conn.execute(
            """
            SELECT e.slug,
                   COUNT(DISTINCT e.site) AS burst_sites,
                   GROUP_CONCAT(DISTINCT e.site) AS sites,
                   g.site_count,
                   g.heat_score,
                   MIN(e.date) AS first_seen,
                   (
                       SELECT e2.site
                       FROM events e2
                       WHERE e2.slug = e.slug AND e2.date >= ?
                       ORDER BY e2.date, e2.site
                       LIMIT 1
                   ) AS first_site,
                   (
                       SELECT e2.url
                       FROM events e2
                       WHERE e2.slug = e.slug AND e2.date >= ?
                       ORDER BY e2.date, e2.site
                       LIMIT 1
                   ) AS first_url,
                   (
                       SELECT COUNT(DISTINCT ev.site)
                       FROM events ev
                       WHERE ev.slug = e.slug AND ev.date = ?
                   ) AS today_sites
            FROM events e
            LEFT JOIN games g ON g.slug = e.slug
            WHERE e.date >= ?
            GROUP BY e.slug
            HAVING burst_sites >= ?
            ORDER BY burst_sites DESC, g.heat_score DESC, e.slug
            """,
            (cutoff, cutoff, today, cutoff, threshold),
        ).fetchall()
        result = [dict(r) for r in rows]
        self._attach_burst_site_links(result, cutoff)
        return result

    def _attach_burst_site_links(self, burst_games, cutoff):
        """为爆发列表附带近窗各站游戏页 URL，供飞书卡片跳转。"""
        if not burst_games:
            return
        slugs = [g['slug'] for g in burst_games]
        placeholders = ','.join('?' for _ in slugs)
        rows = self.conn.execute(
            f"""
            SELECT slug, site, url
            FROM events
            WHERE date >= ? AND slug IN ({placeholders})
            ORDER BY date, site
            """,
            (cutoff, *slugs),
        ).fetchall()
        urls = {}
        for r in rows:
            urls.setdefault(r['slug'], {})
            # 同一站取最早一条事件 URL
            urls[r['slug']].setdefault(r['site'], r['url'])
        for g in burst_games:
            by_site = urls.get(g['slug'], {})
            site_names = [s for s in (g.get('sites') or '').split(',') if s]
            g['site_links'] = [
                {'site': name, 'url': by_site.get(name)}
                for name in site_names
            ]

    def slugs_with_events_on(self, date):
        """某日有新增收录事件的 slug 集合。"""
        rows = self.conn.execute(
            "SELECT DISTINCT slug FROM events WHERE date = ?",
            (date,),
        ).fetchall()
        return {r["slug"] for r in rows}

    def burst_games_involving(self, slugs, window_days, threshold):
        """爆发列表中与本次 touched slugs 有交集的子集（避免每次全量告警）。"""
        if not slugs:
            return []
        burst = self.burst_games(window_days, threshold)
        wanted = set(slugs)
        return [g for g in burst if g['slug'] in wanted]

    def cleanup_events(self, retention_days):
        cutoff = (datetime.now() - timedelta(days=retention_days)).strftime('%Y-%m-%d')
        self.conn.execute('DELETE FROM events WHERE date < ?', (cutoff,))
        self.conn.commit()

    # --- 查询接口（API 用） ---

    def list_games(self, *, q=None, min_site_count=1, limit=50, offset=0):
        """按热度分页列出游戏词；q 对 slug 做子串模糊匹配。"""
        clauses = ['site_count >= ?']
        params = [min_site_count]
        if q:
            clauses.append('slug LIKE ?')
            params.append(f'%{q.lower()}%')
        where = ' AND '.join(clauses)
        params.extend([limit, offset])
        rows = self.conn.execute(
            f"""
            SELECT slug, first_seen, last_seen, site_count, heat_score
            FROM games
            WHERE {where}
            ORDER BY heat_score DESC, site_count DESC, slug
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_game(self, slug):
        """单个游戏词汇总；不存在返回 None。"""
        row = self.conn.execute(
            """
            SELECT slug, first_seen, last_seen, site_count, heat_score
            FROM games
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
        return dict(row) if row else None

    def list_sightings(self, slug):
        """某游戏词在各站的收录详情。"""
        rows = self.conn.execute(
            """
            SELECT site, url, first_seen, last_seen
            FROM sightings
            WHERE slug = ?
            ORDER BY first_seen, site
            """,
            (slug,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_events(
        self,
        *,
        slug=None,
        site=None,
        since=None,
        window_days=None,
        limit=100,
        offset=0,
    ):
        """近期新增事件；可按 slug / site / 日期窗口过滤。"""
        clauses = []
        params = []
        if slug:
            clauses.append('slug = ?')
            params.append(slug)
        if site:
            clauses.append('site = ?')
            params.append(site)
        if since:
            clauses.append('date >= ?')
            params.append(since)
        elif window_days is not None:
            clauses.append('date >= ?')
            params.append(self.window_cutoff(window_days))
        where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
        params.extend([limit, offset])
        rows = self.conn.execute(
            f"""
            SELECT date, slug, site, url
            FROM events
            {where}
            ORDER BY date DESC, slug, site
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def list_sites(self):
        """各站收录游戏数与最近更新日。"""
        rows = self.conn.execute(
            """
            SELECT s.site,
                   COUNT(*) AS game_count,
                   MIN(s.first_seen) AS first_seen,
                   COALESCE(MAX(ss.last_sync), MAX(s.last_seen)) AS last_seen
            FROM sightings s
            LEFT JOIN site_sync ss ON ss.site = s.site
            GROUP BY s.site
            ORDER BY game_count DESC, s.site
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def list_site_games(self, site, *, limit=100, offset=0):
        """某站收录的游戏列表（按 first_seen 倒序，便于看新上架）。"""
        rows = self.conn.execute(
            """
            SELECT s.slug, s.url, s.first_seen, s.last_seen,
                   g.site_count, g.heat_score
            FROM sightings s
            LEFT JOIN games g ON g.slug = s.slug
            WHERE s.site = ?
            ORDER BY s.first_seen DESC, s.slug
            LIMIT ? OFFSET ?
            """,
            (site, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self):
        """库级概览。"""
        games = self.conn.execute('SELECT COUNT(*) AS n FROM games').fetchone()['n']
        sightings = self.conn.execute('SELECT COUNT(*) AS n FROM sightings').fetchone()['n']
        events = self.conn.execute('SELECT COUNT(*) AS n FROM events').fetchone()['n']
        sites = self.conn.execute(
            'SELECT COUNT(DISTINCT site) AS n FROM sightings'
        ).fetchone()['n']
        return {
            'games': games,
            'sightings': sightings,
            'events': events,
            'sites': sites,
        }
