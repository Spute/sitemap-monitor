"""Sitemap Monitor 入口：抓取 → 提 slug → 入库 → 跨站爆发告警。"""

import logging
from datetime import datetime

from config_loader import load_config
from notify import build_burst_card, send_feishu_notification
from sitemap import process_sitemap
from slug import to_game_entries
from store import is_store_auth_error, open_store, reopen_store
from translate import attach_zh_names

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def process_site(site, store, today, burst_window_days):
    """处理单个站点：抓 sitemap、提游戏词、与 DB 同步。

    返回本次该站首次见到的 slug 列表（用于后续爆发告警过滤）。
    """
    site_name = site['name']
    marker = site.get('game_path_marker')
    strip_id_suffix = site.get('strip_id_suffix', False)
    slug_after_marker = site.get('slug_after_marker', False)
    slug_last_segment = site.get('slug_last_segment', False)
    logging.info(f"处理站点: {site_name}")

    all_urls = []
    include_sitemap_patterns = site.get('include_sitemap_patterns')
    for sitemap_url in site['sitemap_urls']:
        urls = process_sitemap(
            sitemap_url,
            include_sitemap_patterns=include_sitemap_patterns,
        )
        all_urls.extend(urls)

    if not all_urls:
        logging.warning(f"{site_name}: 抓取 sitemap 未得到任何 URL，请检查站点配置或可达性")
        return []

    entries = to_game_entries(
        all_urls,
        game_path_marker=marker,
        strip_id_suffix=strip_id_suffix,
        slug_after_marker=slug_after_marker,
        slug_last_segment=slug_last_segment,
    )
    if not entries:
        logging.warning(
            f"{site_name}: 抓到 {len(all_urls)} 个 URL，但过滤后无游戏词，请检查噪音规则或 game_path_marker"
        )
    newly_seen = store.sync_site(site_name, entries, today, burst_window_days)

    if newly_seen:
        logging.info(f"{site_name}: 新增 {len(newly_seen)} 个游戏词")
    else:
        logging.info(f"没有新增游戏: {site_name}")
    return newly_seen


def main(config_path='config.yaml'):
    config = load_config(config_path)
    heat = config.get('heat', {})
    burst_window_days = heat.get('burst_window_days', 7)
    alert_threshold = heat.get('alert_site_threshold', 2)
    events_retention_days = heat.get('events_retention_days', 90)

    store = open_store()
    logging.info(f"数据库: {store.backend} {store.location}")
    today = datetime.now().strftime('%Y-%m-%d')

    touched_slugs = []
    try:
        for site in config['sites']:
            if not site.get('active', True):
                continue
            try:
                touched_slugs.extend(
                    process_site(site, store, today, burst_window_days)
                )
            except Exception as exc:
                if not is_store_auth_error(exc):
                    raise
                logging.warning(
                    "%s: 数据库鉴权失败，跳过该站: %s",
                    site.get('name', '?'),
                    exc,
                )
                try:
                    store = reopen_store(store)
                except Exception as reopen_exc:
                    if not is_store_auth_error(reopen_exc):
                        raise
                    logging.warning("数据库重连失败: %s", reopen_exc)

        # 只对「本次新出现」且已达跨站阈值的词告警
        try:
            burst = store.burst_games_involving(
                touched_slugs, burst_window_days, alert_threshold
            )
            if burst:
                logging.info(f"跨站爆发 {len(burst)} 个游戏词，发送飞书通知")
                attach_zh_names(burst, config)
                send_feishu_notification(
                    build_burst_card(burst, burst_window_days), config
                )
            else:
                logging.info("本次无跨站爆发游戏词")

            store.cleanup_events(events_retention_days)
        except Exception as exc:
            if not is_store_auth_error(exc):
                raise
            logging.warning("数据库鉴权失败，跳过爆发告警与事件清理: %s", exc)
    finally:
        try:
            store.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
