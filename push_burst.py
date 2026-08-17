"""基于当前数据库推送飞书跨站爆发通知（不抓 sitemap）。

用法:
  uv run python push_burst.py                 # 推送近窗全部爆发词
  uv run python push_burst.py --today         # 只推送今天有新增的词
  uv run python push_burst.py --yesterday     # 只推送昨天有新增的词
  uv run python push_burst.py --on 2026-08-16 # 只推送指定日有新增的词
  uv run python push_burst.py --dry-run       # 只打印卡片内容，不发送
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta

from config_loader import load_config
from notify import build_burst_card, send_feishu_notification
from store import open_store
from translate import attach_zh_names

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _parse_on_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as e:
        raise argparse.ArgumentTypeError("日期格式应为 YYYY-MM-DD") from e


def main(config_path="config.yaml"):
    parser = argparse.ArgumentParser(description="基于当前 DB 推送飞书爆发通知")
    day = parser.add_mutually_exclusive_group()
    day.add_argument(
        "--today",
        action="store_true",
        help="只推送今天有新增站点的爆发词",
    )
    day.add_argument(
        "--yesterday",
        action="store_true",
        help="只推送昨天有新增站点的爆发词",
    )
    day.add_argument(
        "--on",
        metavar="YYYY-MM-DD",
        type=_parse_on_date,
        help="只推送指定日有新增站点的爆发词",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印卡片内容，不实际发送",
    )
    parser.add_argument(
        "--config",
        default=config_path,
        help="配置文件路径（默认 config.yaml）",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    heat = config.get("heat", {})
    window = heat.get("burst_window_days", 7)
    threshold = heat.get("alert_site_threshold", 2)
    if args.yesterday:
        on_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    elif args.on:
        on_date = args.on
    elif args.today:
        on_date = datetime.now().strftime("%Y-%m-%d")
    else:
        on_date = None

    store = open_store()
    logging.info(f"数据库: {store.backend} {store.location}")
    try:
        burst = store.burst_games(window, threshold)
        if on_date:
            wanted = store.slugs_with_events_on(on_date)
            burst = [g for g in burst if g["slug"] in wanted]

        if not burst:
            scope = f"{on_date} 有新增的" if on_date else "近窗"
            logging.info(f"无可推送的{scope}爆发词")
            return 0

        attach_zh_names(burst, config)
        card = build_burst_card(burst, window)
        logging.info(f"准备推送 {len(burst)} 个爆发词")
        print(card["card"]["elements"][0]["text"]["content"])

        if args.dry_run:
            logging.info("dry-run：未发送飞书通知")
            return 0

        ok = send_feishu_notification(card, config)
        return 0 if ok else 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
