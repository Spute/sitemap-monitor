"""飞书通知：跨站爆发热游卡片。"""

import logging

import requests


def _md_link(text, url):
    """飞书 lark_md 可点击链接；无 URL 时退回纯文本。"""
    if url:
        return f"[{text}]({url})"
    return text


def build_burst_card(burst_games, window_days):
    """构造飞书互动卡片：以关键词为维度展示跨站爆发信息。"""
    lines = []
    for g in burst_games[:20]:
        first_site = g.get('first_site') or '未知'
        first_seen = g.get('first_seen') or '未知'
        first_url = g.get('first_url')
        today_sites = g.get('today_sites') or 0
        site_count = g.get('site_count') or g.get('burst_sites') or 0

        site_links = g.get('site_links')
        if site_links:
            sites_md = ', '.join(
                _md_link(item['site'], item.get('url')) for item in site_links
            )
        else:
            sites_md = (g.get('sites') or '').replace(',', ', ') or '—'

        lines.append(
            f"• **{_md_link(g['slug'], first_url)}**\n"
            f"  近窗最早：{_md_link(first_site, first_url)}（{first_seen}）\n"
            f"  今日新增：{today_sites} 站｜累计：{site_count} 站\n"
            f"  近 {window_days} 天新增：{sites_md}"
        )
    body = (
        f"**近 {window_days} 天跨站爆发 {len(burst_games)} 个游戏词**\n\n"
        + ("\n\n".join(lines) if lines else "（无）")
    )
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "🔥 跨站热游爆发"},
                "template": "red",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": body},
                }
            ],
        },
    }


def send_feishu_notification(message_card, config):
    """发送飞书 Webhook，失败重试最多 3 次。"""
    webhook_url = config['feishu']['webhook_url']
    for attempt in range(3):
        try:
            resp = requests.post(webhook_url, json=message_card)
            resp.raise_for_status()
            logging.info("飞书通知发送成功")
            return True
        except requests.RequestException as e:
            logging.error(f"飞书通知发送失败: {str(e)}")
            if attempt < 2:
                logging.info("重试发送通知...")
    return False
