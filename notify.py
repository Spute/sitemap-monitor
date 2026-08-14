"""飞书通知：跨站爆发热游卡片。"""

import logging

import requests

from build_trend_urls import DEFAULT_ANCHOR, build_trends_url, build_trends_urls


def _md_link(text, url):
    """飞书 lark_md 可点击链接；无 URL 时退回纯文本。"""
    if url:
        return f"[{text}]({url})"
    return text


def slug_to_trends_keyword(slug: str) -> str:
    """slug → Trends 查询词（连字符转空格）。"""
    return (slug or "").strip().replace("-", " ")


def _trends_url_for_slug(slug: str) -> str:
    """单个游戏词的 Trends 链接（含锚定词对比）。"""
    keyword = slug_to_trends_keyword(slug)
    if not keyword:
        return ""
    return build_trends_url([keyword, DEFAULT_ANCHOR])


def _trends_batch_urls(slugs: list[str]) -> list[str]:
    """将本次挑选的游戏词分批生成 Trends 对比链接，每批一条 URL。"""
    keywords = [slug_to_trends_keyword(s) for s in slugs if slug_to_trends_keyword(s)]
    if not keywords:
        return []
    return [item["url"] for item in build_trends_urls(keywords)]


def _trends_batch_section(slugs: list[str]) -> str:
    """将本次挑选的游戏词分批生成 Trends 对比链接，以代码块列出 URL。"""
    urls = _trends_batch_urls(slugs)
    if not urls:
        return ""
    return "**Google Trends 对比查询**\n```\n" + "\n".join(urls) + "\n```"


def build_burst_card(burst_games, window_days):
    """构造飞书互动卡片：以关键词为维度展示跨站爆发信息。"""
    shown = burst_games[:20]
    lines = []
    for g in shown:
        first_site = g.get('first_site') or '未知'
        first_seen = g.get('first_seen') or '未知'
        first_url = g.get('first_url')
        today_sites = g.get('today_sites') or 0
        site_count = g.get('site_count') or g.get('burst_sites') or 0
        trends_url = _trends_url_for_slug(g['slug'])

        site_links = g.get('site_links')
        if site_links:
            sites_md = ', '.join(
                _md_link(item['site'], item.get('url')) for item in site_links
            )
        else:
            sites_md = (g.get('sites') or '').replace(',', ', ') or '—'

        trends_md = f"｜{_md_link('Trends', trends_url)}" if trends_url else ""
        lines.append(
            f"• **{_md_link(g['slug'], first_url)}**{trends_md}\n"
            f"  近窗最早：{_md_link(first_site, first_url)}（{first_seen}）\n"
            f"  今日新增：{today_sites} 站｜累计：{site_count} 站\n"
            f"  近 {window_days} 天新增：{sites_md}"
        )

    parts = [
        f"**近 {window_days} 天跨站爆发 {len(burst_games)} 个游戏词**",
        "\n\n".join(lines) if lines else "（无）",
    ]
    batch_section = _trends_batch_section([g['slug'] for g in shown])
    if batch_section:
        parts.append(batch_section)
    body = "\n\n".join(parts)
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
