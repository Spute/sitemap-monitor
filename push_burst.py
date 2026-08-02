"""基于当前数据库推送飞书跨站爆发通知（不抓 sitemap）。

用法:
  uv run python push_burst.py              # 推送近窗全部爆发词
  uv run python push_burst.py --today      # 只推送今天有新增的词
  uv run python push_burst.py --dry-run    # 只打印卡片内容，不发送
"""

import argparse
import logging
import sys

from config_loader import load_config
from notify import build_burst_card, send_feishu_notification
from store import GameStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main(config_path="config.yaml"):
    parser = argparse.ArgumentParser(description="基于当前 DB 推送飞书爆发通知")
    parser.add_argument(
        "--today",
        action="store_true",
        help="只推送今天有新增站点的爆发词",
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
    db_path = config.get("storage", {}).get("db_path", "./data/games.db")

    store = GameStore(db_path)
    try:
        burst = store.burst_games(window, threshold)
        if args.today:
            burst = [g for g in burst if (g.get("today_sites") or 0) > 0]

        if not burst:
            scope = "今天有新增的" if args.today else "近窗"
            logging.info(f"无可推送的{scope}爆发词")
            return 0

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
