"""FastAPI 查询服务：跨站热游 / 爆发 / 站点收录。

启动：
    uv run uvicorn api:app --reload --host 0.0.0.0 --port 8001

文档：
    Swagger UI  → http://127.0.0.1:8001/docs
    ReDoc       → http://127.0.0.1:8001/redoc
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from config_loader import load_config
from schemas import (
    BurstGameOut,
    EventOut,
    GameDetailOut,
    GameOut,
    HealthOut,
    SightingOut,
    SiteGameOut,
    SiteOut,
    StatsOut,
)
from store import GameStore, open_store

_CONFIG_PATH = Path(__file__).resolve().parent / 'config.yaml'
_store: GameStore | None = None
_heat_defaults: dict = {}


def _open_store() -> GameStore:
    return open_store(check_same_thread=False)


def get_store() -> GameStore:
    if _store is None:
        raise RuntimeError('GameStore 未初始化')
    return _store


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store, _heat_defaults
    config = load_config(_CONFIG_PATH)
    _heat_defaults = config.get('heat', {})
    _store = _open_store()
    try:
        yield
    finally:
        _store.close()
        _store = None


app = FastAPI(
    title="Sitemap Monitor API",
    description=(
        "游戏 sitemap 跨站热度查询服务。\n\n"
        "**核心概念**\n"
        "- `slug`：从游戏页 URL 提取的关键词（如 `hill-sprint`）\n"
        "- `site_count`：存量热度，有多少站收录该词\n"
        "- `burst`：近 N 天内新增站点数，用于**及时发现**扩散中的游戏\n"
        "- `heat_score`：`site_count + 2 × 近窗爆发站点数`\n\n"
        "**常用路径**\n"
        "- 看爆发 → `GET /games/burst`\n"
        "- 看热榜 → `GET /games`\n"
        "- 查一词 → `GET /games/{slug}`\n"
        "- 看某站 → `GET /sites/{site}/games`\n"
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "系统",
            "description": "健康检查与库概览",
        },
        {
            "name": "游戏词",
            "description": "以 slug 为中心的热度 / 爆发 / 详情查询",
        },
        {
            "name": "事件",
            "description": "各站每日新增收录（爆发计算的原始数据）",
        },
        {
            "name": "站点",
            "description": "按监控站点查看收录情况",
        },
    ],
)


@app.get(
    "/health",
    response_model=HealthOut,
    tags=["系统"],
    summary="健康检查",
)
def health():
    return HealthOut(status="ok", db_path=get_store().location)


@app.get(
    "/stats",
    response_model=StatsOut,
    tags=["系统"],
    summary="数据概览",
    description="返回 games / sightings / events / sites 数量，便于确认库是否已回填。",
)
def stats():
    return StatsOut(**get_store().stats())


@app.get(
    "/games/burst",
    response_model=list[BurstGameOut],
    tags=["游戏词"],
    summary="跨站爆发列表（及时发现）",
    description=(
        "统计近 `window_days` 天内，新增站点数 ≥ `threshold` 的游戏词。\n"
        "这是「多站短时间同时上线」的主信号，优先于老热游的存量覆盖。"
    ),
)
def list_burst_games(
    window_days: Optional[int] = Query(
        None,
        ge=1,
        le=90,
        description="爆发统计窗口（天）。默认取 config.heat.burst_window_days",
    ),
    threshold: Optional[int] = Query(
        None,
        ge=1,
        le=50,
        description="窗口内最少站点数。默认取 config.heat.alert_site_threshold",
    ),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限"),
):
    store = get_store()
    window = window_days or int(_heat_defaults.get('burst_window_days', 7))
    thr = threshold or int(_heat_defaults.get('alert_site_threshold', 2))
    rows = store.burst_games(window, thr)[:limit]
    return [BurstGameOut(**r) for r in rows]


@app.get(
    "/games",
    response_model=list[GameOut],
    tags=["游戏词"],
    summary="游戏热榜 / 搜索",
    description="按 heat_score 降序分页；可用 `q` 模糊搜 slug，`min_site_count` 过滤低覆盖词。",
)
def list_games(
    q: Optional[str] = Query(None, description="slug 子串搜索，如 sprint"),
    min_site_count: int = Query(
        1, ge=1, description="最少跨站数；设为 2+ 可只看多站游戏"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = get_store().list_games(
        q=q, min_site_count=min_site_count, limit=limit, offset=offset
    )
    return [GameOut(**r) for r in rows]


@app.get(
    "/games/{slug}",
    response_model=GameDetailOut,
    tags=["游戏词"],
    summary="游戏词详情",
    description="返回汇总热度、各站收录 URL，以及近窗新增事件。",
    responses={404: {"description": "未找到该 slug"}},
)
def get_game(
    slug: str,
    event_window_days: Optional[int] = Query(
        None,
        ge=1,
        le=90,
        description="详情中附带的近期事件窗口。默认 burst_window_days",
    ),
):
    store = get_store()
    game = store.get_game(slug)
    if not game:
        raise HTTPException(status_code=404, detail=f"未找到游戏词: {slug}")
    window = event_window_days or int(_heat_defaults.get('burst_window_days', 7))
    sightings = store.list_sightings(slug)
    events = store.list_events(slug=slug, window_days=window, limit=100)
    return GameDetailOut(
        game=GameOut(**game),
        sightings=[SightingOut(**s) for s in sightings],
        recent_events=[EventOut(**e) for e in events],
    )


@app.get(
    "/events",
    response_model=list[EventOut],
    tags=["事件"],
    summary="新增事件流",
    description="各站首次收录某 slug 的记录，可按站点 / 游戏词 / 天数窗口筛选。",
)
def list_events(
    slug: Optional[str] = Query(None, description="游戏词精确匹配"),
    site: Optional[str] = Query(None, description="站点名精确匹配，如 1Games"),
    window_days: int = Query(
        7, ge=1, le=365, description="只返回近 N 天事件"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows = get_store().list_events(
        slug=slug,
        site=site,
        window_days=window_days,
        limit=limit,
        offset=offset,
    )
    return [EventOut(**r) for r in rows]


@app.get(
    "/sites",
    response_model=list[SiteOut],
    tags=["站点"],
    summary="站点列表",
    description="已写入 DB 的监控站点及其收录数量。",
)
def list_sites():
    return [SiteOut(**r) for r in get_store().list_sites()]


@app.get(
    "/sites/{site}/games",
    response_model=list[SiteGameOut],
    tags=["站点"],
    summary="某站游戏列表",
    description="按该站 first_seen 倒序，方便查看该站最近上新。",
)
def list_site_games(
    site: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows = get_store().list_site_games(site, limit=limit, offset=offset)
    if not rows and not any(
        s['site'] == site for s in get_store().list_sites()
    ):
        raise HTTPException(status_code=404, detail=f"未找到站点数据: {site}")
    return [SiteGameOut(**r) for r in rows]
