# Sitemap Monitor

监控多个游戏站的 sitemap，从 URL 提取游戏关键词（slug），用跨站出现次数与近期扩散速度评估热度，并在发现跨站爆发时通过飞书通知。

定时任务由 GitHub Actions 每天执行（UTC 22:00 / 北京时间次日 06:00），也可手动触发。

## 目标

- 关心的不是完整 URL，而是 **URL 路径中的子页面名称（slug）**，即游戏关键词
- 同一游戏出现在多个站点 → 热度更高
- 重点是 **及时发现**：短时间内被多个站收录的新词，优先于早已铺开的老热游

## 数据与热度方案（核心）

### 主键：slug

```text
https://1games.io/hill-sprint              → hill-sprint
https://www.crazygames.com/en/game/foo     → foo   （站点配置 game_path_marker）
https://azgames.io/category/io-games       → 丢弃（噪音）
https://1games.io/action.games             → 丢弃（分类页）
```

噪音过滤包括：导航页（`new-games` / `hot-games` 等）、静态页（`about-us` 等）、`tag/` / `category/` 前缀、`*.games` 后缀，以及站点连载页等。

### 存储：SQLite（slug 中心）

| 表 | 作用 |
|---|---|
| `sightings` | `(slug, site)` → url / first_seen / last_seen |
| `events` | 每日新增事件 `(date, slug, site)`，用于爆发计算 |
| `games` | 汇总：`site_count`、`heat_score`、首末出现日 |

变更检测也走 `sightings`：某站首次出现的 slug 才记入 `events`；新站首跑只建基线、不告警。

### 热度：存量 + 爆发

1. **存量热度** `site_count`：当前有多少站收录该词（流行面）
2. **爆发热度**（告警主信号）：近 N 天内新增站点数；短窗口内跨站扩散越快越值得推送

告警只推爆发：窗口内（默认 7 天）出现站点数 ≥ 阈值（默认 2）。老词长期高覆盖但不扩散，不重复打扰。

### 流水线

```text
抓 sitemap → 过滤噪音 → 提取 slug
  → 与 sightings 同步（新 slug 写 events）
  → 更新 games 热度 → 飞书推「跨站热游」
```

## 功能

- 拉取 XML / TXT sitemap（自动识别 gzip，递归展开 sitemapindex）
- 提取并过滤游戏 slug，写入 SQLite
- 按站检测新增游戏词，记录每日事件
- 跨站爆发热度评估与飞书通知
- 按配置清理过期 events

## 环境要求

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/)

## 安装

会默认安装开发依赖：
```bash
uv sync
```

仅安装运行依赖（不含开发依赖）：

```bash
uv sync --no-dev
```

## 配置

编辑 `config.yaml`：

```yaml
sites:
  - name: "Example"
    sitemap_urls:
      - "https://example.com/sitemap.xml"
    active: true

  - name: "CrazyGames"
    sitemap_urls:
      - "https://www.crazygames.com/sitemap-index.xml"
    include_sitemap_patterns:
      - "https://www.crazygames.com/en/"
    # 仅将含该标记的 URL 视为游戏页，slug 取 path 最后一段
    game_path_marker: "/game/"
    active: true

feishu:
  webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/..."
  secret: "YOUR_SECRET"

storage:
  db_path: "./data/games.db"

heat:
  burst_window_days: 7       # 爆发统计窗口
  alert_site_threshold: 2    # 窗口内站点数 ≥ 此值则告警
  events_retention_days: 90  # events 表保留天数
```

- `active: false` 可暂时跳过某个站点
- `include_sitemap_patterns` 可选；过滤 sitemapindex 中要继续抓取的子 sitemap
- `game_path_marker` 可选；用于 CrazyGames 这类路径较深的站点

## 运行

```bash
uv run python main.py
```

查询示例（安装 sqlite3 后）：

```bash
sqlite3 data/games.db "
  SELECT slug, COUNT(DISTINCT site) AS n
  FROM events
  WHERE date >= date('now', '-7 day')
  GROUP BY slug
  HAVING n >= 2
  ORDER BY n DESC;
"
```

## 测试

```bash
uv sync
uv run pytest
```

## 目录结构

```text
.
├── main.py                 # 入口编排
├── slug.py                 # URL → 游戏词提取与噪音过滤
├── sitemap.py              # sitemap 拉取与解析
├── store.py                # SQLite（sightings / events / games）
├── notify.py               # 飞书跨站爆发通知
├── config_loader.py        # 配置加载
├── config.yaml             # 站点 / 热度 / 通知配置
├── test_main.py
├── data/games.db           # SQLite（唯一数据存储）
└── .github/workflows/      # GitHub Actions 定时监控
```

## GitHub Actions

工作流：`.github/workflows/sitemap-check.yml`

- 触发：`main` 上相关文件变更、每日定时、手动 `workflow_dispatch`
- 流程：`uv sync --frozen` → 运行监控 → 有变更则提交并推送
- 需在仓库 Secrets 中配置 `GH_TOKEN`（用于回写数据）

## 常用命令

```bash
uv add <package>           # 添加运行依赖
uv add --dev <package>     # 添加开发依赖
uv lock                    # 更新锁文件
uv run pytest              # 运行测试
uv run pytest -v -s        # 运行测试详情
uv run python main.py      # 运行监控
```
