-- 热度监控关键词（与 sitemap 同一 Turso 库，仅多一张表）
-- 改词只需 INSERT / UPDATE / 把 active 设为 0，不必改代码。

CREATE TABLE IF NOT EXISTS interest_keywords (
    keyword    TEXT PRIMARY KEY,                          -- Google Trends 查询词
    geo        TEXT NOT NULL DEFAULT '',                  -- 地区代码，空=全球，如 US、CN
    timeframe  TEXT NOT NULL DEFAULT 'now 1-d',           -- 时间范围，如 now 1-d、now 7-d、today 12-m
    active     INTEGER NOT NULL DEFAULT 1,                -- 1=监控，0=停用
    note       TEXT,                                      -- 备注，可选
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_interest_keywords_active
    ON interest_keywords (active);

-- 示例
INSERT INTO interest_keywords (keyword) VALUES ('kinebox')
ON CONFLICT(keyword) DO UPDATE SET active = 1, updated_at = datetime('now');
