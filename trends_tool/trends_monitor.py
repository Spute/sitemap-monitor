import argparse
import logging
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from querytrends import (
    DEFAULT_DATA_DIR,
    batch_get_queries,
    save_related_queries,
    print_related_queries,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

DEFAULT_BATCH_SIZE = 5
DEFAULT_BATCH_INTERVAL = 60
DEFAULT_DELAY_BETWEEN_QUERIES = 5


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


def main():
    parser = argparse.ArgumentParser(description='Query Google Trends related queries')
    parser.add_argument('--keywords', nargs='+', required=True,
                        help='要查询的关键词列表')
    parser.add_argument('--timeframe', default='now 1-d',
                        help="时间范围，如 'now 1-d'、'now 7-d'、'today 12-m'、'last-2-d'")
    parser.add_argument('--geo', default='',
                        help="地区代码，空表示全球，如 'US'、'CN'")
    parser.add_argument('--output-dir', default=None,
                        help='结果保存目录，默认项目根目录 data/')
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE,
                        help='每批查询的关键词数量')
    parser.add_argument('--delay', type=float, default=DEFAULT_DELAY_BETWEEN_QUERIES,
                        help='同一批内关键词之间的间隔秒数')
    args = parser.parse_args()

    query_keywords(
        keywords=args.keywords,
        timeframe=args.timeframe,
        geo=args.geo,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        delay_between_queries=args.delay,
    )


if __name__ == "__main__":
    main()
