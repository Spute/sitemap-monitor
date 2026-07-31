"""飞书通知：跨站爆发热游卡片。"""

import logging

import requests


def build_burst_card(burst_games, window_days):
    """构造飞书互动卡片：展示近窗跨站爆发的游戏词。"""
    lines = []
    for g in burst_games[:20]:
        sites = (g.get('sites') or '').replace(',', ', ')
        lines.append(
            f"• **{g['slug']}** — {g['burst_sites']} 站 / 总量 {g.get('site_count') or g['burst_sites']}\n"
            f"  {sites}"
        )
    body = (
        f"**近 {window_days} 天跨站爆发 {len(burst_games)} 个游戏词**\n\n"
        + ("\n".join(lines) if lines else "（无）")
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
