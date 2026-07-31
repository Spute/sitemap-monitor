# Sitemap Monitor

监控多个站点的 sitemap 变更，保存最新快照与每日增量，并在发现新增 URL 时通过飞书机器人通知。

定时任务由 GitHub Actions 每天执行（UTC 22:00 / 北京时间次日 06:00），也可手动触发。

## 功能

- 拉取 XML / TXT sitemap（自动识别 gzip，递归展开 sitemapindex）
- 与 `latest/` 快照对比，找出新增 URL
- 写入 `diff/YYYYMMDD/` 增量记录
- 通过飞书 Webhook 发送上新通知
- 按配置清理过期 diff 数据

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
    # 展开 sitemapindex 时，只跟进匹配的子 sitemap（子串匹配）
    include_sitemap_patterns:
      - "https://www.crazygames.com/en/"
    active: true

feishu:
  webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/..."
  secret: "YOUR_SECRET"

storage:
  retention_days: 7
```

- `active: false` 可暂时跳过某个站点
- `include_sitemap_patterns` 可选；用于过滤 `sitemapindex` 中要继续抓取的子 sitemap
- 自动识别并递归展开 `sitemapindex` / `urlset` / 文本 sitemap（含 gzip）
- `retention_days` 控制 `diff/` 目录保留天数

## 运行

```bash
uv run python main.py
```

## 测试

开发依赖包含 `pytest`：

```bash
uv sync
uv run pytest
```

## 目录结构

```text
.
├── main.py                 # 主脚本
├── config.yaml             # 站点与通知配置
├── pyproject.toml          # 项目与依赖声明
├── uv.lock                 # 锁定版本
├── test_main.py            # pytest 测试
├── latest/                 # 各站点最新 URL 快照
├── diff/YYYYMMDD/          # 按日增量
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
uv run pytest -v -s             # 运行测试, -s 打印print, -v显示详情
uv run python main.py      # 运行监控
```
