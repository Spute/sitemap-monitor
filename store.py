"""SQLite 存储：以 slug 为中心，支撑跨站查询与爆发热度。"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class GameStore:
    """三表模型：
    - sightings: 某站收录某 slug（存量，兼做变更基线）
    - events: 某日某站首次新增（爆发窗口用）
    - games: 汇总 site_count / heat_score
    """

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
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
            CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
            CREATE INDEX IF NOT EXISTS idx_events_slug ON events(slug);
            CREATE INDEX IF NOT EXISTS idx_sightings_site ON sightings(site);
            CREATE INDEX IF NOT EXISTS idx_games_heat ON games(heat_score DESC);
            """
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def site_has_sightings(self, site):
        """该站是否已有基线数据。"""
        row = self.conn.execute(
            'SELECT 1 FROM sightings WHERE site = ? LIMIT 1',
            (site,),
        ).fetchone()
        return row is not None

    def upsert_sighting(self, slug, site, url, today):
        """写入/更新收录关系。返回 True 表示该站首次见到此 slug。"""
        row = self.conn.execute(
            'SELECT first_seen FROM sightings WHERE slug = ? AND site = ?',
            (slug, site),
        ).fetchone()
        if row:
            self.conn.execute(
                'UPDATE sightings SET url = ?, last_seen = ? WHERE slug = ? AND site = ?',
                (url, today, slug, site),
            )
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

    def refresh_game(self, slug, burst_window_days):
        """按 sightings + 近窗 events 重算 games 汇总行。

        heat_score = site_count + 2 * 近窗爆发站点数
        （存量覆盖 + 加权近期扩散）
        """
        stats = self.conn.execute(
            """
            SELECT MIN(first_seen) AS first_seen,
                   MAX(last_seen) AS last_seen,
                   COUNT(*) AS site_count
            FROM sightings
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
        if not stats or not stats['site_count']:
            return

        cutoff = (datetime.now() - timedelta(days=burst_window_days)).strftime('%Y-%m-%d')
        burst = self.conn.execute(
            """
            SELECT COUNT(DISTINCT site) AS n
            FROM events
            WHERE slug = ? AND date >= ?
            """,
            (slug, cutoff),
        ).fetchone()['n']

        heat = float(stats['site_count']) + 2.0 * float(burst)
        self.conn.execute(
            """
            INSERT INTO games (slug, first_seen, last_seen, site_count, heat_score)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                first_seen = excluded.first_seen,
                last_seen = excluded.last_seen,
                site_count = excluded.site_count,
                heat_score = excluded.heat_score
            """,
            (slug, stats['first_seen'], stats['last_seen'], stats['site_count'], heat),
        )

    def sync_site(self, site, entries, today, burst_window_days):
        """用当前 sitemap 游戏目录同步某站。

        - 该站尚无 sightings：建立基线，只写存量、不写 events（避免首跑全量告警）
        - 已有基线：首次见到的 slug 记入 events，并返回这些 slug
        """
        baseline = not self.site_has_sightings(site)
        newly_seen = []
        for slug, url in entries:
            is_new = self.upsert_sighting(slug, site, url, today)
            if is_new and not baseline:
                self.record_event(today, slug, site, url)
                newly_seen.append(slug)
            self.refresh_game(slug, burst_window_days)
        self.conn.commit()
        return newly_seen

    def burst_games(self, window_days, threshold):
        """近 window_days 天内，新增站点数 ≥ threshold 的游戏词（爆发列表）。"""
        cutoff = (datetime.now() - timedelta(days=window_days)).strftime('%Y-%m-%d')
        rows = self.conn.execute(
            """
            SELECT e.slug,
                   COUNT(DISTINCT e.site) AS burst_sites,
                   GROUP_CONCAT(DISTINCT e.site) AS sites,
                   g.site_count,
                   g.heat_score
            FROM events e
            LEFT JOIN games g ON g.slug = e.slug
            WHERE e.date >= ?
            GROUP BY e.slug
            HAVING burst_sites >= ?
            ORDER BY burst_sites DESC, g.heat_score DESC, e.slug
            """,
            (cutoff, threshold),
        ).fetchall()
        return [dict(r) for r in rows]

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
