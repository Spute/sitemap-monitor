"""API 响应模型：字段说明会进入 OpenAPI / Swagger 文档。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class HealthOut(BaseModel):
    """服务健康状态。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"status": "ok", "db_path": "/app/data/games.db"}]
        }
    )

    status: str = Field(
        description="服务状态：正常为 ok",
        examples=["ok"],
    )
    db_path: str = Field(
        description="当前连接的 SQLite 数据库绝对路径",
        examples=["/home/user/sitemap-monitor/data/games.db"],
    )


class StatsOut(BaseModel):
    """库级数据概览。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"games": 6200, "sightings": 9500, "events": 120, "sites": 80}
            ]
        }
    )

    games: int = Field(
        description="游戏词（slug）去重总数，对应 games 表行数",
        examples=[6200],
    )
    sightings: int = Field(
        description="收录关系数：某站收录某词记一条（slug × site）",
        examples=[9500],
    )
    events: int = Field(
        description="历史新增事件总数：站点首次收录某词时写入",
        examples=[120],
    )
    sites: int = Field(
        description="库中已有 sightings 数据的站点数量",
        examples=[80],
    )


class GameOut(BaseModel):
    """游戏词汇总（热度相关核心字段）。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "slug": "hill-sprint",
                    "first_seen": "2026-07-29",
                    "last_seen": "2026-07-31",
                    "site_count": 5,
                    "heat_score": 13.0,
                }
            ]
        }
    )

    slug: str = Field(
        description="游戏关键词：从页面 URL 路径提取并归一化，如 hill-sprint",
        examples=["hill-sprint"],
    )
    first_seen: str = Field(
        description="该词在任意监控站首次出现的日期（YYYY-MM-DD）",
        examples=["2026-07-29"],
    )
    last_seen: str = Field(
        description="最近一次在任意站见到该词的日期（YYYY-MM-DD）",
        examples=["2026-07-31"],
    )
    site_count: int = Field(
        description="存量热度：当前有多少个站点收录了该词",
        examples=[5],
    )
    heat_score: float = Field(
        description=(
            "综合热度分 = site_count + 2 × 近窗爆发站点数；"
            "爆发站点数为近 N 天（默认 7）内首次新增该词的去重站数"
        ),
        examples=[13.0],
    )


class SightingOut(BaseModel):
    """某游戏词在单个站点上的收录记录。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "site": "1Games",
                    "url": "https://1games.io/hill-sprint",
                    "first_seen": "2026-07-29",
                    "last_seen": "2026-07-31",
                }
            ]
        }
    )

    site: str = Field(
        description="站点名称，与 config.yaml 中 sites[].name 一致",
        examples=["1Games"],
    )
    url: str = Field(
        description="该站上对应游戏页的完整 URL",
        examples=["https://1games.io/hill-sprint"],
    )
    first_seen: str = Field(
        description="该站首次收录此词的日期（YYYY-MM-DD）",
        examples=["2026-07-29"],
    )
    last_seen: str = Field(
        description="该站最近一次同步仍见到此词的日期（YYYY-MM-DD）",
        examples=["2026-07-31"],
    )


class EventOut(BaseModel):
    """站点首次收录某游戏词的事件（爆发统计的原始数据）。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "date": "2026-07-29",
                    "slug": "hill-sprint",
                    "site": "1Games",
                    "url": "https://1games.io/hill-sprint",
                }
            ]
        }
    )

    date: str = Field(
        description="事件日期：该站首次收录该词的当天（YYYY-MM-DD）",
        examples=["2026-07-29"],
    )
    slug: str = Field(
        description="游戏关键词",
        examples=["hill-sprint"],
    )
    site: str = Field(
        description="发生新增的站点名",
        examples=["1Games"],
    )
    url: str = Field(
        description="当时记录的页面 URL",
        examples=["https://1games.io/hill-sprint"],
    )


class GameDetailOut(BaseModel):
    """单个游戏词的完整详情：汇总 + 各站收录 + 近窗事件。"""

    game: GameOut = Field(description="该词的汇总热度信息")
    sightings: list[SightingOut] = Field(
        description="各监控站对该词的收录明细（含 URL）",
    )
    recent_events: list[EventOut] = Field(
        description="近窗内的新增事件：哪些站在近期首次上架了该词",
    )


class BurstGameOut(BaseModel):
    """跨站爆发游戏词：短时间内被多个站新增收录。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "slug": "hill-sprint",
                    "burst_sites": 4,
                    "sites": "1Games,AZGames,Sprunki,Wordle2",
                    "site_count": 5,
                    "heat_score": 13.0,
                    "first_seen": "2026-07-29",
                    "first_site": "1Games",
                    "first_url": "https://1games.io/hill-sprint",
                    "today_sites": 2,
                }
            ]
        }
    )

    slug: str = Field(
        description="爆发中的游戏关键词",
        examples=["hill-sprint"],
    )
    burst_sites: int = Field(
        description="近窗内新增站点数（爆发强度）；越大表示扩散越快",
        examples=[4],
    )
    sites: Optional[str] = Field(
        default=None,
        description="近窗内出现过该词新增的站点名列表，逗号分隔",
        examples=["1Games,AZGames,Sprunki,Wordle2"],
    )
    site_count: Optional[int] = Field(
        default=None,
        description="截止今天累计收录站点数（可能大于 burst_sites，含更早收录的站）",
        examples=[5],
    )
    heat_score: Optional[float] = Field(
        default=None,
        description="综合热度分：site_count + 2 × 近窗爆发站点数",
        examples=[13.0],
    )
    first_seen: Optional[str] = Field(
        default=None,
        description="近窗内该词最早新增的日期（YYYY-MM-DD），不含窗外历史",
        examples=["2026-07-29"],
    )
    first_site: Optional[str] = Field(
        default=None,
        description="近窗内最早新增该词的站点名",
        examples=["1Games"],
    )
    first_url: Optional[str] = Field(
        default=None,
        description="近窗内最早新增站上的游戏页 URL，可用于跳转",
        examples=["https://1games.io/hill-sprint"],
    )
    today_sites: Optional[int] = Field(
        default=None,
        description="今天新增收录该词的站点数",
        examples=[2],
    )


class SiteOut(BaseModel):
    """单个监控站点的收录概况。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "site": "1Games",
                    "game_count": 800,
                    "first_seen": "2026-07-01",
                    "last_seen": "2026-07-31",
                }
            ]
        }
    )

    site: str = Field(
        description="站点名称（config.yaml 中的 name）",
        examples=["1Games"],
    )
    game_count: int = Field(
        description="该站当前收录的游戏词数量",
        examples=[800],
    )
    first_seen: str = Field(
        description="该站数据中最早一条收录的日期（YYYY-MM-DD）",
        examples=["2026-07-01"],
    )
    last_seen: str = Field(
        description="该站最近一次同步更新的日期（YYYY-MM-DD）",
        examples=["2026-07-31"],
    )


class SiteGameOut(BaseModel):
    """某站下的一条游戏收录，并附带全局热度字段。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "slug": "hill-sprint",
                    "url": "https://1games.io/hill-sprint",
                    "first_seen": "2026-07-29",
                    "last_seen": "2026-07-31",
                    "site_count": 5,
                    "heat_score": 13.0,
                }
            ]
        }
    )

    slug: str = Field(
        description="游戏关键词",
        examples=["hill-sprint"],
    )
    url: str = Field(
        description="该站上的游戏页 URL",
        examples=["https://1games.io/hill-sprint"],
    )
    first_seen: str = Field(
        description="该站首次收录此词的日期（YYYY-MM-DD）",
        examples=["2026-07-29"],
    )
    last_seen: str = Field(
        description="该站最近见到此词的日期（YYYY-MM-DD）",
        examples=["2026-07-31"],
    )
    site_count: Optional[int] = Field(
        default=None,
        description="全局存量：有多少站收录了该词（跨站视角）",
        examples=[5],
    )
    heat_score: Optional[float] = Field(
        default=None,
        description="全局综合热度分",
        examples=[13.0],
    )
