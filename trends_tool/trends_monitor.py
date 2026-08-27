import argparse
import logging
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(PROJECT_ROOT))

from config_loader import load_config
from notify import build_interest_trend_card, send_feishu_notification
from interest_store import load_interest_keywords
from querytrends import (
    DEFAULT_DATA_DIR,
    _explore_page_url,
    _interest_series,
    batch_get_queries,
    get_interest_over_time,
    has_rising_interest,
    print_interest_over_time,
    print_related_queries,
    print_rising_interest,
    save_interest_over_time,
    save_related_queries,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

DEFAULT_BATCH_SIZE = 5
DEFAULT_BATCH_INTERVAL = 60
DEFAULT_DELAY_BETWEEN_QUERIES = 5
DEFAULT_INTEREST_TIMEFRAME = 'now 1-d'


def get_date_range_timeframe(timeframe):
    """将 last-N-d 转为日期区间，例如 last-2-d → '2024-01-01 2024-01-03'。"""
    if not timeframe.startswith('last-'):
        return timeframe

    try:
        days = int(timeframe.split('-')[1])
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        return f"{start_date.strftime('%Y-%m-%d')} {end_date.strftime('%Y-%m-%d')}"
    except (ValueError, IndexError):
        logging.warning(f"Invalid timeframe format: {timeframe}, falling back to 'now 1-d'")
        return 'now 1-d'


def create_output_directory(output_dir=None):
    """创建输出目录，默认项目根目录 data/。"""
    directory = Path(output_dir) if output_dir else DEFAULT_DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def query_keywords(keywords, timeframe='now 1-d', geo='', output_dir=None,
                   batch_size=DEFAULT_BATCH_SIZE, delay_between_queries=DEFAULT_DELAY_BETWEEN_QUERIES):
    """分批查询关键词的 Trends 相关查询，并保存结果。"""
    actual_timeframe = get_date_range_timeframe(timeframe)
    directory = create_output_directory(output_dir)

    logging.info(f"Query parameters: timeframe={actual_timeframe}, geo={geo or 'Global'}")
    logging.info(f"Keywords ({len(keywords)}): {keywords}")
    logging.info(f"Output directory: {directory}")

    all_results = {}

    for i in range(0, len(keywords), batch_size):
        keywords_batch = keywords[i:i + batch_size]
        logging.info(f"Processing batch of {len(keywords_batch)} keywords: {keywords_batch}")

        try:
            results = batch_get_queries(
                keywords_batch,
                timeframe=actual_timeframe,
                geo=geo,
                delay_between_queries=delay_between_queries + random.uniform(0, 2)
            )
        except Exception as e:
            logging.error(f"Failed to process batch starting with {keywords_batch[0]}: {e}")
            continue

        for keyword, data in results.items():
            all_results[keyword] = data
            if data:
                print_related_queries(data)
                filename = save_related_queries(keyword, data, directory)
                if filename:
                    logging.info(f"Saved {keyword} -> {filename}")
            else:
                logging.warning(f"No data for keyword: {keyword}")

        if i + batch_size < len(keywords):
            wait_time = DEFAULT_BATCH_INTERVAL + random.uniform(0, 60)
            logging.info(f"Waiting {wait_time:.1f} seconds before next batch...")
            time.sleep(wait_time)

    logging.info(f"Done. Success: {sum(1 for v in all_results.values() if v)}/{len(keywords)}")
    return all_results


def _timeline_stats(timeline):
    """从热度序列取出峰值、最近值等，供飞书卡片使用。"""
    series = _interest_series(timeline)
    if series is None or series.empty:
        return {}
    peak_idx = series.idxmax()
    return {
        'points': int(len(series)),
        'peak': series.max().item() if hasattr(series.max(), 'item') else series.max(),
        'peak_at': str(peak_idx),
        'latest': series.iloc[-1].item() if hasattr(series.iloc[-1], 'item') else series.iloc[-1],
        'latest_at': str(series.index[-1]),
    }


def _normalize_interest_targets(keywords, geo, timeframe):
    """CLI 词列表或数据库行 → [{keyword, geo, timeframe}, ...]。"""
    if not keywords:
        return []
    targets = []
    for item in keywords:
        if isinstance(item, str):
            keyword = item.strip()
            if not keyword:
                continue
            targets.append({
                'keyword': keyword,
                'geo': geo,
                'timeframe': timeframe,
            })
            continue
        keyword = (item.get('keyword') or '').strip()
        if not keyword:
            continue
        targets.append({
            'keyword': keyword,
            'geo': (item.get('geo') or geo or '').strip(),
            'timeframe': (item.get('timeframe') or timeframe or DEFAULT_INTEREST_TIMEFRAME).strip(),
        })
    return targets


def monitor_interest_trends(
    keywords=None,
    timeframe=DEFAULT_INTEREST_TIMEFRAME,
    geo='',
    output_dir=None,
    config_path=None,
    notify=True,
    keywords_db_path=None,
):
    """监控关键词热度随时间变化，判断是否翻倍上升，并将结果发到飞书。

    未传入 keywords 时从 Turso interest_keywords 表读取启用中的词。
    """
    if keywords:
        targets = _normalize_interest_targets(keywords, geo, timeframe)
    else:
        targets = _normalize_interest_targets(
            load_interest_keywords(db_path=keywords_db_path),
            geo,
            timeframe,
        )
    if not targets:
        raise RuntimeError('没有可监控的关键词：请在 Turso interest_keywords 表写入 active=1 的行，或用 --keywords 指定')

    directory = create_output_directory(output_dir)
    config_file = config_path or str(PROJECT_ROOT / 'config.yaml')
    config = load_config(config_file) if notify else None

    logging.info(f"Interest monitor targets ({len(targets)}): {[t['keyword'] for t in targets]}")

    results = []
    for i, target in enumerate(targets):
        keyword = target['keyword']
        item_geo = target['geo']
        item_timeframe = get_date_range_timeframe(target['timeframe'])
        logging.info(
            f"Querying interest over time: {keyword} geo={item_geo or 'Global'} timeframe={item_timeframe}"
        )
        try:
            timeline = get_interest_over_time(keyword, geo=item_geo, timeframe=item_timeframe)
        except Exception as e:
            logging.error(f"Failed to query {keyword}: {e}")
            timeline = None

        if timeline is None or timeline.empty:
            logging.warning(f"No interest data for keyword: {keyword}")
            rising = {
                'rising': False,
                'reason': '未能获取热度趋势数据',
                'baseline_mean': None,
                'recent_mean': None,
            }
            stats = {}
        else:
            print_interest_over_time(timeline, keyword)
            rising = has_rising_interest(timeline)
            print_rising_interest(rising, keyword)
            stats = _timeline_stats(timeline)
            filename = save_interest_over_time(
                keyword, timeline, directory=directory, geo=item_geo, timeframe=item_timeframe
            )
            if filename:
                logging.info(f"Saved {keyword} -> {filename}")

        explore_url = _explore_page_url(keyword, item_geo, item_timeframe)
        card = build_interest_trend_card(
            keyword, item_timeframe, item_geo, explore_url, rising, stats
        )
        if notify and config:
            ok = send_feishu_notification(card, config)
            if not ok:
                logging.error(f"Feishu notify failed for {keyword}")
        results.append({
            'keyword': keyword,
            'rising': rising,
            'stats': stats,
            'explore_url': explore_url,
        })

        if i < len(targets) - 1:
            wait_time = DEFAULT_DELAY_BETWEEN_QUERIES + random.uniform(0, 2)
            logging.info(f"Waiting {wait_time:.1f} seconds before next keyword...")
            time.sleep(wait_time)

    rising_n = sum(1 for r in results if r['rising'].get('rising'))
    logging.info(f"Interest monitor done. Rising: {rising_n}/{len(results)}")
    return results


def main():
    parser = argparse.ArgumentParser(description='Google Trends 查询与热度监控')
    parser.add_argument('--interest', action='store_true',
                        help='监控热度随时间变化（关键词从 Turso interest_keywords 读取）并发送飞书')
    parser.add_argument('--keywords', nargs='+',
                        help='要查询的关键词列表；热度监控若指定则不再读库')
    parser.add_argument('--timeframe', default=None,
                        help="时间范围，如 'now 1-d'、'now 7-d'、'today 12-m'、'last-2-d'")
    parser.add_argument('--geo', default='',
                        help="地区代码，空表示全球，如 'US'、'CN'")
    parser.add_argument('--output-dir', default=None,
                        help='结果保存目录，默认项目根目录 data/')
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE,
                        help='每批查询的关键词数量（相关查询）')
    parser.add_argument('--delay', type=float, default=DEFAULT_DELAY_BETWEEN_QUERIES,
                        help='同一批内关键词之间的间隔秒数')
    parser.add_argument('--no-notify', action='store_true',
                        help='热度监控时不发送飞书')
    args = parser.parse_args()

    if args.interest:
        monitor_interest_trends(
            keywords=args.keywords,
            timeframe=args.timeframe or DEFAULT_INTEREST_TIMEFRAME,
            geo=args.geo,
            output_dir=args.output_dir,
            notify=not args.no_notify,
        )
        return

    if not args.keywords:
        parser.error('相关查询需要 --keywords；热度监控请使用 --interest')

    query_keywords(
        keywords=args.keywords,
        timeframe=args.timeframe or 'now 1-d',
        geo=args.geo,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        delay_between_queries=args.delay,
    )


if __name__ == "__main__":
    main()
