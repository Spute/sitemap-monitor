"""对比两个关键词当天 Google Trends 前 N 相关查询词，取交集并飞书通知。

参考 explore 页面：
    https://trends.google.com/trends/explore?date=2026-09-04%202026-09-04&q=codes,tier%20list
当天单日查询：date 形如 "YYYY-MM-DD YYYY-MM-DD"（起止同日）。
"""

import logging
import random
import threading
import time
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TRENDS_TOOL_DIR = Path(__file__).resolve().parent

import sys

sys.path.insert(0, str(_TRENDS_TOOL_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from config_loader import load_config
from notify import build_overlap_card, send_feishu_notification
from querytrends import get_related_queries

DEFAULT_TOP_N = 5
DEFAULT_KEYWORDS = ["codes", "tier list"]
DEFAULT_DELAY_BETWEEN_QUERIES = 5
# 单个关键词查询的硬超时（秒）。querytrends.get_related_queries 遇到配额超限会
# 在 while True 里 sleep 300~360s 反复重试，可能把整个 job 拖到超时。
# 这里用线程兜底，超时就放弃该词、记为无数据并继续下一个。
DEFAULT_QUERY_TIMEOUT_SEC = 480
TRENDS_BASE = "https://trends.google.com/trends/explore"


def today_timeframe():
    """返回当天单日 timeframe，用 Trends 的 'now 1-d' 表示当天。"""
    return "now 1-d"


def _explore_compare_url(keywords, timeframe, geo=""):
    """两个词的 Trends 对比页面 URL。"""
    q = ",".join(quote(k.strip(), safe="") for k in keywords if k and k.strip())
    date_q = quote(timeframe, safe="")
    parts = [f"q={q}", f"date={date_q}"]
    if geo:
        parts.append(f"geo={quote(geo, safe='')}")
    return f"{TRENDS_BASE}?{'&'.join(parts)}"


def _top_queries(related_data, n=DEFAULT_TOP_N):
    """从 related_queries 结果中取 top 前 n 条 query 文本（小写归一）。"""
    if not related_data:
        return []
    top = related_data.get("top")
    if top is None:
        return []
    try:
        if hasattr(top, "to_dict"):
            records = top.to_dict(orient="records")
        else:
            records = list(top)
    except Exception:
        records = []
    queries = []
    for rec in records[:n]:
        q = rec.get("query") if isinstance(rec, dict) else None
        if q:
            queries.append(str(q).strip().lower())
    return queries


def _call_with_timeout(fn, timeout_sec):
    """在 daemon 线程里跑 fn；超时抛 TimeoutError，避免被无限重试循环卡住。"""
    box = {}

    def runner():
        try:
            box["result"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout_sec)
    if thread.is_alive():
        raise TimeoutError(f"超过 {timeout_sec}s 未返回")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _query_with_timeout(keyword, geo, timeframe, timeout_sec):
    """带硬超时地获取相关查询；超时或异常返回 None。"""
    try:
        return _call_with_timeout(
            lambda: get_related_queries(keyword, geo=geo, timeframe=timeframe),
            timeout_sec,
        )
    except TimeoutError as e:
        logging.error("查询 %s 超时，跳过: %s", keyword, e)
        return None


def monitor_overlap(
    keywords=None,
    timeframe=None,
    geo="",
    top_n=DEFAULT_TOP_N,
    notify=True,
    config_path=None,
    delay_between_queries=DEFAULT_DELAY_BETWEEN_QUERIES,
    query_timeout_sec=DEFAULT_QUERY_TIMEOUT_SEC,
):
    """对比两个关键词当天前 N 相关查询词，存在交集则发飞书。

    Args:
        keywords: 两个关键词列表；默认 ['codes', 'tier list']。
        timeframe: Trends 时间范围；默认当天单日。
        geo: 地区代码，空表示全球。
        top_n: 每个词取前 N 条相关查询。
        notify: 是否发送飞书通知。
        query_timeout_sec: 单个关键词查询的硬超时秒数，超时则跳过该词。
    """
    keywords = [k for k in (keywords or DEFAULT_KEYWORDS) if k and k.strip()]
    if len(keywords) != 2:
        raise ValueError("overlap 监控需要恰好两个关键词进行对比")

    timeframe = timeframe or today_timeframe()
    config_file = config_path or str(PROJECT_ROOT / "config.yaml")
    config = load_config(config_file) if notify else None

    logging.info(
        "Overlap monitor: keywords=%s timeframe=%s geo=%s top_n=%d query_timeout=%ss",
        keywords,
        timeframe,
        geo or "全球",
        top_n,
        query_timeout_sec,
    )

    per_keyword = {}
    for i, kw in enumerate(keywords):
        logging.info("查询相关查询: %s", kw)
        data = _query_with_timeout(kw, geo, timeframe, query_timeout_sec)
        per_keyword[kw] = _top_queries(data, top_n)
        logging.info("%s 前 %d 相关查询: %s", kw, top_n, per_keyword[kw])

        if i < len(keywords) - 1:
            wait = delay_between_queries + random.uniform(0, 2)
            logging.info("等待 %.1f 秒后查询下一个词...", wait)
            time.sleep(wait)

    sets = [set(per_keyword[kw]) for kw in keywords]
    common = sorted(set.intersection(*sets)) if all(sets) else []
    logging.info("交集关键词 (%d): %s", len(common), common)

    explore_url = _explore_compare_url(keywords, timeframe, geo)
    result = {
        "keywords": keywords,
        "timeframe": timeframe,
        "geo": geo,
        "top_n": top_n,
        "per_keyword": per_keyword,
        "common": common,
        "explore_url": explore_url,
    }

    if notify and config:
        card = build_overlap_card(result)
        ok = send_feishu_notification(card, config)
        if not ok:
            logging.error("飞书通知发送失败（overlap）")
    else:
        logging.info("未启用飞书通知")

    return result
