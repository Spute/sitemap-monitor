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

    def __init__(self, db_path, *, check_same_thread=True):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=check_same_thread,
        )
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
        """近 window_days 天内，新增站点数 ≥ threshold 的游戏词（爆发列表）。

        额外附带关键词维度信息：
        - first_site / first_seen：最早收录该词的站点与日期
        - today_sites：今天新增的站点数
        - site_count：截止今天累计收录站点数
        """
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        cutoff = (now - timedelta(days=window_days)).strftime('%Y-%m-%d')
        rows = self.conn.execute(
            """
            SELECT e.slug,
                   COUNT(DISTINCT e.site) AS burst_sites,
                   GROUP_CONCAT(DISTINCT e.site) AS sites,
                   g.site_count,
                   g.heat_score,
                   g.first_seen,
                   (
                       SELECT s.site
                       FROM sightings s
                       WHERE s.slug = e.slug
                       ORDER BY s.first_seen, s.site
                       LIMIT 1
                   ) AS first_site,
                   (
                       SELECT s.url
                       FROM sightings s
                       WHERE s.slug = e.slug
                       ORDER BY s.first_seen, s.site
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
            (today, cutoff, threshold),
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
            cutoff = (datetime.now() - timedelta(days=window_days)).strftime('%Y-%m-%d')
            clauses.append('date >= ?')
            params.append(cutoff)
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
            SELECT site,
                   COUNT(*) AS game_count,
                   MIN(first_seen) AS first_seen,
                   MAX(last_seen) AS last_seen
            FROM sightings
            GROUP BY site
            ORDER BY game_count DESC, site
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
