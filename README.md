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
  → 更新 games 热度 → 实时英译中 → 飞书推「跨站热游」
```

## 功能

### 监控侧（`main.py`）

- 拉取 XML / TEXT sitemap（自动识别 gzip，递归展开 sitemapindex）
- 网络超时 / 连接重置时自动重试 1 次；抓取无 URL 时打 warning
- 提取并过滤游戏 slug，写入 SQLite
- 按站检测新增游戏词，记录每日 events
- 跨站爆发热度评估；达阈值时飞书通知（卡片附中文译名）
- 按配置清理过期 events

### 飞书通知（`notify.py` / `translate.py` / `push_burst.py`）

- 跨站爆发时发互动卡片；游戏词旁附中文译名，如 `hill-sprint（山地冲刺）`
- 译名用免费接口实时翻译，**不写数据库**：先 Google 网页翻译（无需 key），失败再试 MyMemory 官方免费 API
- 只展示含汉字的译文；专有名词译不出来则只显示原文，不影响通知发出
- 卡片最多展示 20 个词；可用 `push_burst.py` 按今天 / 昨天 / 指定日补推或预览

### 查询侧（`api.py` / FastAPI）

- 提供 REST 查询接口，数据来自 `data/games.db`
- 内置 OpenAPI 文档（Swagger / ReDoc），响应字段均有中文说明
- 覆盖：爆发列表、热榜搜索、一词详情、事件流、按站查看

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

translation:
  enabled: true
  providers:
    - google      # Google 网页翻译（无需 key）
    - mymemory    # MyMemory 官方免费 API（无需 key）

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
- `strip_id_suffix` 可选；去掉 slug 末尾 `-数字`（如 Playhop 的 `/app/foosball-96247`）
- `slug_after_marker` 可选；slug 取 `game_path_marker` 后一段（如 Friv 的 `/z/games/{slug}/game.html`）
- `slug_last_segment` 可选；无 marker 时也取 path 最后一段（如 PlayA 的 `/{category}/{slug}/`）
- `translation.enabled` 控制飞书卡片是否给游戏词附中文译名（每次通知时实时翻译，不缓存）。设 `enabled: false` 可关闭
- `translation.providers` 按顺序尝试；默认 `google` → `mymemory`，均可无 key。机翻对游戏名不稳定，译不出则省略中文

## 运行监控

```bash
uv run python main.py
```

## 手动推送飞书（基于当前数据库）

不重新抓取 sitemap，直接读取 `data/games.db` 中的爆发结果并发飞书。候选范围始终是 **近窗爆发词**（默认 7 天、跨站数 ≥ 阈值），再用日期参数收窄「这一天有新增站点」的子集。不加日期参数 = 近窗全部，不是历史所有天。

`--today` / `--yesterday` / `--on` 三选一；`--dry-run` 只打印卡片、不发送，可与日期参数组合。

```bash
# 近窗全部爆发词（会实时翻译后发飞书）
uv run python push_burst.py

# 只推送今天 / 昨天 / 指定日有新增站点的爆发词
uv run python push_burst.py --today
uv run python push_burst.py --yesterday
uv run python push_burst.py --on 2026-08-16

# 只预览卡片，不发送
uv run python push_burst.py --dry-run
uv run python push_burst.py --today --dry-run
uv run python push_burst.py --yesterday --dry-run
uv run python push_burst.py --on 2026-08-16 --dry-run
```

| 参数 | 含义 |
|---|---|
| （无日期） | 近窗内全部爆发词 |
| `--today` | 近窗爆发词里，**今天**有新增站点的 |
| `--yesterday` | 近窗爆发词里，**昨天**有新增站点的 |
| `--on YYYY-MM-DD` | 近窗爆发词里，**该日**有新增站点的 |
| `--dry-run` | 打印卡片内容，不调用飞书 Webhook |
| `--config` | 配置文件路径，默认 `config.yaml` |

## 查询 API

先确保已跑过监控、库中有数据，再启动服务：

```bash
uv run uvicorn api:app --reload --host 0.0.0.0 --port 8001
```

| 文档 | 地址 |
|---|---|
| Swagger UI | http://127.0.0.1:8001/docs |
| ReDoc | http://127.0.0.1:8001/redoc |

在 `/docs` 中可展开每个接口的 **Schema**，查看返回字段的中文说明与示例。

### 接口一览

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 健康检查，确认服务与 DB 路径 |
| GET | `/stats` | 库概览：游戏词 / 收录关系 / 事件 / 站点数 |
| GET | `/games/burst` | **跨站爆发**（及时发现主入口） |
| GET | `/games` | 热榜；可按 slug 模糊搜索、按最少站点数过滤 |
| GET | `/games/{slug}` | 一词详情：热度汇总 + 各站 URL + 近窗事件 |
| GET | `/events` | 新增事件流（某站首次收录某词） |
| GET | `/sites` | 已有数据的站点列表及收录量 |
| GET | `/sites/{site}/games` | 某站游戏列表（按该站上新时间倒序） |

### 常用查询参数

| 接口 | 参数 | 说明 |
|---|---|---|
| `/games/burst` | `window_days` | 爆发窗口天数，默认 `config.heat.burst_window_days`（7） |
| `/games/burst` | `threshold` | 窗口内最少站点数，默认 `alert_site_threshold`（2） |
| `/games` | `q` | slug 子串搜索，如 `sprint` |
| `/games` | `min_site_count` | 最少跨站数；`2` 表示只看多站游戏 |
| `/games/{slug}` | `event_window_days` | 详情里附带近窗事件的天数 |
| `/events` | `slug` / `site` / `window_days` | 按词、站、天数筛选事件 |
| 多数列表接口 | `limit` / `offset` | 分页 |

### 返回字段说明（核心）

**游戏汇总（`GameOut`，见于 `/games`、`/games/{slug}`）**

| 字段 | 含义 |
|---|---|
| `slug` | 游戏关键词（URL 路径归一化结果） |
| `first_seen` / `last_seen` | 全局首次 / 最近见到日期（YYYY-MM-DD） |
| `site_count` | 存量热度：当前有多少站收录 |
| `heat_score` | 综合热度 = `site_count + 2 × 近窗爆发站点数` |

**爆发项（`BurstGameOut`，见于 `/games/burst`）**

| 字段 | 含义 |
|---|---|
| `slug` | 爆发中的游戏词 |
| `burst_sites` | 近窗内新增站点数（爆发强度） |
| `sites` | 近窗内相关站点名，逗号分隔 |
| `site_count` | 截止今天累计收录站点数（可大于 `burst_sites`） |
| `heat_score` | 综合热度分 |
| `first_site` | 最早收录该词的站点 |
| `first_url` | 最早收录站上的游戏页 URL |
| `first_seen` | 该词最早被收录的日期 |
| `today_sites` | 今天新增收录该词的站点数 |

**收录明细（`SightingOut`）**

| 字段 | 含义 |
|---|---|
| `site` | 站点名（与 `config.yaml` 中 `name` 一致） |
| `url` | 该站游戏页完整 URL |
| `first_seen` / `last_seen` | 该站首次 / 最近见到日期 |

**事件（`EventOut`，见于 `/events`、详情中的 `recent_events`）**

| 字段 | 含义 |
|---|---|
| `date` | 该站首次收录该词的日期 |
| `slug` / `site` / `url` | 游戏词、站点、当时记录的 URL |

**站点概况（`SiteOut`）**

| 字段 | 含义 |
|---|---|
| `site` | 站点名 |
| `game_count` | 该站收录的游戏词数量 |
| `first_seen` / `last_seen` | 该站数据最早 / 最近更新日期 |

### 调用示例

```bash
# 近 7 天跨站爆发（≥2 站）
curl "http://127.0.0.1:8001/games/burst"

# 热榜：至少 3 站收录
curl "http://127.0.0.1:8001/games?min_site_count=3&limit=20"

# 查某个游戏词
curl "http://127.0.0.1:8001/games/hill-sprint"

# 某站最近上新
curl "http://127.0.0.1:8001/sites/1Games/games?limit=20"
```

## 测试

```bash
uv sync
uv run pytest
```

## 目录结构

```text
.
├── main.py                 # 监控入口编排
├── push_burst.py           # 基于当前 DB 手动推送飞书
├── api.py                  # FastAPI 查询服务
├── schemas.py              # API 响应模型（OpenAPI）
├── slug.py                 # URL → 游戏词提取与噪音过滤
├── sitemap.py              # sitemap 拉取与解析
├── store.py                # SQLite（sightings / events / games）
├── notify.py               # 飞书跨站爆发通知
├── translate.py            # 游戏词免费英译中（飞书卡片用）
├── config_loader.py        # 配置加载
├── config.yaml             # 站点 / 热度 / 通知配置
├── test_main.py / test_api.py
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
uv run python push_burst.py                 # 推送近窗全部爆发词
uv run python push_burst.py --today         # 只推今天有新增的词
uv run python push_burst.py --yesterday     # 只推昨天有新增的词
uv run python push_burst.py --on 2026-08-16 # 只推指定日有新增的词
uv run python push_burst.py --yesterday --dry-run  # 预览昨天的卡片，不发送
uv run uvicorn api:app --reload --port 8001   # 启动查询 API
```
