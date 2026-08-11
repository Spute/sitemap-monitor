#!/usr/bin/env python3
"""将游戏标题转为 Google Trends 查询链接。

每批 3～4 个游戏名 + 1 个锚定词（最多 5 个词）。
关键词按 encodeURIComponent 编码（空格 → %20），词之间的逗号不编码。
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import quote


TRENDS_BASE = "https://trends.google.com/trends/explore"
DEFAULT_ANCHOR = "casual games"  # 锚定词, 休闲游戏
# 默认美国；设为空字符串 "" 表示全球（URL 不带 geo 参数）
# DEFAULT_GEO = "US"
DEFAULT_GEO = ""
DEFAULT_DATE = "now 7-d"
# 每批游戏数；再加上 1 个锚定词 ⇒ 总词数 ≤ 5（Trends 对比上限）
DEFAULT_BATCH_SIZE = 3
MAX_TERMS = 5


def encode_keyword(keyword: str) -> str:
    """对 Trends 的 q= 词做 encodeURIComponent 等价编码（空格 → %20）。"""
    return quote(keyword.strip(), safe="")


def build_trends_url(
    keywords: list[str],
    *,
    date: str = DEFAULT_DATE,
    geo: str = DEFAULT_GEO,
) -> str:
    """生成单条 explore URL；保留 keywords 顺序（通常末尾为锚定词）。

    geo 为空（或仅空白）时表示全球，URL 不附带 geo 参数。
    """
    terms = [k.strip() for k in keywords if k and k.strip()]
    if not terms:
        raise ValueError("至少需要一个关键词")
    if len(terms) > MAX_TERMS:
        raise ValueError(f"单条 URL 最多 {MAX_TERMS} 个词，收到 {len(terms)} 个")

    q = ",".join(encode_keyword(k) for k in terms)
    # date/geo 编码与 SKILL 一致：空格 → %20，不用 +
    date_q = quote(date, safe="")
    parts = [f"q={q}", f"date={date_q}"]
    geo = (geo or "").strip()
    if geo:
        parts.append(f"geo={quote(geo, safe='')}")
    return f"{TRENDS_BASE}?{'&'.join(parts)}"


def batch_keywords(
    games: list[str],
    *,
    anchor: str = DEFAULT_ANCHOR,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[list[str]]:
    """将游戏名按 batch_size 分批，每批末尾追加锚定词。"""
    cleaned = [g.strip() for g in games if g and g.strip()]
    if not cleaned:
        raise ValueError("未提供游戏关键词")

    anchor = anchor.strip()
    if not anchor:
        raise ValueError("锚定词不能为空")

    max_games = MAX_TERMS - 1  # 预留 1 个位置给锚定词
    if batch_size < 1 or batch_size > max_games:
        raise ValueError(f"batch_size 须在 1..{max_games}，收到 {batch_size}")

    batches: list[list[str]] = []
    for i in range(0, len(cleaned), batch_size):
        chunk = cleaned[i : i + batch_size]
        batches.append([*chunk, anchor])
    return batches


def build_trends_urls(
    games: list[str],
    *,
    anchor: str = DEFAULT_ANCHOR,
    batch_size: int = DEFAULT_BATCH_SIZE,
    date: str = DEFAULT_DATE,
    geo: str = DEFAULT_GEO,
) -> list[dict[str, object]]:
    """按批生成结果；每项含 keywords 与 url。"""
    results: list[dict[str, object]] = []
    for keywords in batch_keywords(games, anchor=anchor, batch_size=batch_size):
        results.append(
            {
                "keywords": keywords,
                "url": build_trends_url(keywords, date=date, geo=geo),
            }
        )
    return results


def _read_games(args: argparse.Namespace) -> list[str]:
    """从参数、文件、JSON 或 stdin 读取游戏名列表。"""
    if args.file:
        text = args.file.read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]
    if args.json:
        data = json.loads(args.json)
        if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
            raise SystemExit("--json 须为字符串数组，例如 [\"snake\",\"frog\"]")
        return data
    if args.games:
        return list(args.games)
    if not sys.stdin.isatty():
        return [line.strip() for line in sys.stdin if line.strip()]
    raise SystemExit("请通过参数、--file、--json 或 stdin 提供游戏名")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="将游戏标题转换为 Google Trends 查询链接。"
    )
    p.add_argument("games", nargs="*", help="游戏标题关键词")
    p.add_argument(
        "-f",
        "--file",
        type=lambda s: __import__("pathlib").Path(s),
        help="文本文件，每行一个游戏标题",
    )
    p.add_argument("--json", help='JSON 字符串数组，例如 \'["snake","frog"]\'')
    p.add_argument(
        "--anchor",
        default=DEFAULT_ANCHOR,
        help=f'每批末尾追加的锚定词（默认："{DEFAULT_ANCHOR}"）',
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"每批游戏名数量，不含锚定词（默认：{DEFAULT_BATCH_SIZE}，最大 {MAX_TERMS - 1}）",
    )
    p.add_argument(
        "--geo",
        nargs="?",
        const="",
        default=DEFAULT_GEO,
        help=(
            f'地区代码；省略本参数默认 "{DEFAULT_GEO}"；'
            "写 --geo 且不跟值（或传空）表示全球"
        ),
    )
    p.add_argument(
        "--date",
        default=DEFAULT_DATE,
        help=f'Trends 时间范围（默认："{DEFAULT_DATE}"）',
    )
    p.add_argument(
        "--no-anchor",
        action="store_true",
        help="不追加锚定词；仅按批输出游戏名",
    )
    p.add_argument(
        "--plain",
        action="store_true",
        help="只打印 URL（每行一条）；默认输出 JSON",
    )
    args = p.parse_args(argv)

    games = _read_games(args)

    if args.no_anchor:
        # 无锚定词时仍分批，保证单次打开不超过 5 个词
        size = min(args.batch_size, MAX_TERMS)
        batches = [
            games[i : i + size] for i in range(0, len(games), size)
        ]
        results = [
            {"keywords": b, "url": build_trends_url(b, date=args.date, geo=args.geo)}
            for b in batches
        ]
    else:
        results = build_trends_urls(
            games,
            anchor=args.anchor,
            batch_size=args.batch_size,
            date=args.date,
            geo=args.geo,
        )

    if args.plain:
        for item in results:
            print(item["url"])
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
