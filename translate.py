"""游戏词英译中：发通知时实时调用免费接口。

默认先走 Google 网页翻译（无需 key），失败再试 MyMemory 官方免费 API。
只把含汉字的结果写入通知，避免专有名词原样回传。
"""

from __future__ import annotations

import html
import logging
import re
import time

import requests

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_MYMEMORY_WARN_RE = re.compile(r"MYMEMORY WARNING", re.I)

_GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
_MYMEMORY_URL = "https://api.mymemory.translated.net/get"

_DEFAULT_PROVIDERS = ("google", "mymemory")
_TIMEOUT = 8
_PAUSE_SEC = 0.15


def slug_to_phrase(slug: str) -> str:
    """slug → 可读英文短语（连字符转空格）。"""
    return (slug or "").strip().replace("-", " ")


def contains_cjk(text: str) -> bool:
    return bool(text and _CJK_RE.search(text))


def _clean_zh(text: str) -> str:
    text = html.unescape((text or "").strip())
    if not text or _MYMEMORY_WARN_RE.search(text):
        return ""
    return text


def _translate_google(phrase: str) -> str:
    resp = requests.get(
        _GOOGLE_URL,
        params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": phrase},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data or not data[0]:
        return ""
    parts = [seg[0] for seg in data[0] if seg and seg[0]]
    return _clean_zh("".join(parts))


def _translate_mymemory(phrase: str) -> str:
    resp = requests.get(
        _MYMEMORY_URL,
        params={"q": phrase, "langpair": "en|zh-CN"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    return _clean_zh((data.get("responseData") or {}).get("translatedText") or "")


def _provider_fn(name):
    # 调用时再解析，便于测试 monkeypatch
    return {
        "google": _translate_google,
        "mymemory": _translate_mymemory,
    }.get(name)


def translate_phrase(phrase: str, providers=None) -> tuple[str, str]:
    """将英文短语译成中文。返回 (译文, 成功的 provider)，失败则为 ("", "")。"""
    phrase = (phrase or "").strip()
    if not phrase:
        return "", ""
    for name in providers or _DEFAULT_PROVIDERS:
        fn = _provider_fn(name)
        if not fn:
            logging.warning(f"未知翻译 provider: {name}")
            continue
        try:
            zh = fn(phrase)
        except (requests.RequestException, ValueError, TypeError, IndexError) as e:
            logging.warning(f"翻译失败 provider={name} phrase={phrase!r}: {e}")
            continue
        if contains_cjk(zh):
            return zh, name
        logging.info(f"翻译无中文 provider={name} phrase={phrase!r} zh={zh!r}")
    return "", ""


def translate_slugs(slugs, config=None) -> dict[str, str]:
    """批量实时翻译 slug。"""
    cfg = (config or {}).get("translation") or {}
    if not cfg.get("enabled", True):
        return {}

    unique = []
    seen = set()
    for slug in slugs:
        if slug and slug not in seen:
            unique.append(slug)
            seen.add(slug)
    if not unique:
        return {}

    providers = tuple(cfg.get("providers") or _DEFAULT_PROVIDERS)
    result = {}
    for i, slug in enumerate(unique):
        if i:
            time.sleep(_PAUSE_SEC)
        phrase = slug_to_phrase(slug)
        zh, provider = translate_phrase(phrase, providers)
        if not zh:
            continue
        result[slug] = zh
        logging.info(f"翻译 {slug} → {zh} ({provider})")
    return result


def attach_zh_names(burst_games, config=None, limit=20):
    """给飞书卡片将展示的爆发词附上 zh 字段。"""
    shown = burst_games[:limit]
    zh_map = translate_slugs([g["slug"] for g in shown], config)
    for g in shown:
        zh = zh_map.get(g["slug"])
        if zh:
            g["zh"] = zh
    return burst_games
