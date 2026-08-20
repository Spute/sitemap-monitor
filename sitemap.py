"""拉取并解析 sitemap（含 sitemapindex 递归展开）。"""

import gzip
import io
import logging
import threading
import time

import cloudscraper
import requests
from lxml import etree

# 超时 / 连接重置等多属瞬时网络问题，失败后重试 1 次
FETCH_TIMEOUT = 20
FETCH_RETRIES = 1
FETCH_RETRY_DELAY_SEC = 1
# cloudscraper 解 JS 挑战时可能无视 timeout，单独加硬超时
CLOUDSCRAPER_HARD_TIMEOUT = 25
_UA = {'User-Agent': 'Mozilla/5.0'}


def matches_patterns(url, patterns):
    """patterns 为空则全部接受；否则 URL 需包含任一子串。"""
    if not patterns:
        return True
    return any(pattern in url for pattern in patterns)


def parse_xml(content):
    """从 urlset / sitemapindex 的页面 <loc> 提取 URL。

    只取 <url><loc> 与 <sitemap><loc>，忽略 image:loc 等扩展字段。
    用 lxml 流式解析，避免 GameMonetize 这类 8MB+ sitemap 把进程卡住。
    """
    urls = []
    for _, elem in etree.iterparse(
        io.BytesIO(content),
        events=('end',),
        recover=True,
        huge_tree=True,
    ):
        try:
            local = etree.QName(elem.tag).localname.lower()
        except ValueError:
            elem.clear()
            continue
        if local == 'loc':
            parent = elem.getparent()
            parent_name = ''
            if parent is not None:
                try:
                    parent_name = etree.QName(parent.tag).localname.lower()
                except ValueError:
                    parent_name = ''
            if parent_name in ('url', 'sitemap'):
                text = (elem.text or '').strip()
                if text:
                    urls.append(text)
        if local in ('url', 'sitemap', 'loc'):
            elem.clear()
            parent = elem.getparent()
            if parent is not None:
                while elem.getprevious() is not None:
                    del parent[0]
    return urls


def parse_txt(content):
    """纯文本 sitemap：每行一个 URL。"""
    return [line.strip() for line in content.splitlines() if line.strip()]


def _call_with_timeout(fn, timeout_sec):
    """在独立线程跑 fn；超时抛 TimeoutError（线程为 daemon，不阻塞退出）。"""
    box = {}

    def runner():
        try:
            box['result'] = fn()
        except Exception as exc:
            box['error'] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout_sec)
    if thread.is_alive():
        raise TimeoutError(f'超过 {timeout_sec}s 未返回')
    if 'error' in box:
        raise box['error']
    return box.get('result')


def _cloudscraper_get(url):
    scraper = cloudscraper.create_scraper()
    return _call_with_timeout(
        lambda: scraper.get(url, timeout=FETCH_TIMEOUT),
        CLOUDSCRAPER_HARD_TIMEOUT,
    )


def _get_sitemap(url):
    """优先普通 requests（有真实超时）；遇 401/403/429/503 再让 cloudscraper 过 Cloudflare。"""
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT, headers=_UA)
        response.raise_for_status()
        return response.content
    except requests.HTTPError as e:
        status = getattr(e.response, 'status_code', None)
        if status not in (401, 403, 429, 503):
            raise
        logging.info(f"HTTP {status}，改用 cloudscraper: {url}")

    response = _cloudscraper_get(url)
    response.raise_for_status()
    return response.content


def fetch_sitemap_content(url):
    """拉取 sitemap 原始内容；网络错误时重试一次。失败返回 None。"""
    last_error = None
    attempts = FETCH_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            return _get_sitemap(url)
        except TimeoutError as e:
            logging.error(f"拉取 sitemap 超时，跳过: {url} ({e})")
            return None
        except requests.RequestException as e:
            last_error = e
            if attempt <= FETCH_RETRIES:
                logging.warning(
                    f"拉取 sitemap 失败，准备重试 ({attempt}/{FETCH_RETRIES}): {url} ({e})"
                )
                time.sleep(FETCH_RETRY_DELAY_SEC)
            else:
                logging.error(f"Error processing {url}: {last_error}")
    return None


def process_sitemap(url, include_sitemap_patterns=None, visited=None, max_depth=3):
    """拉取 sitemap，返回页面 URL 列表。

    遇到 sitemapindex 会递归子 sitemap；可用 include_sitemap_patterns
    只跟进匹配的子项（例如只抓英文 locale）。
    抓取成功但未解析到任何 URL 时打 warning，便于发现失效 sitemap。
    """
    if visited is None:
        visited = set()
    if url in visited or max_depth < 0:
        return []
    visited.add(url)

    try:
        logging.info(f"拉取 sitemap: {url}")
        content = fetch_sitemap_content(url)
        if content is None:
            return []
        if not content:
            logging.warning(f"sitemap 响应为空: {url}")
            return []

        # gzip magic number
        if content[:2] == b'\x1f\x8b':
            content = gzip.decompress(content)

        if b'<sitemapindex' in content:
            child_sitemaps = parse_xml(content)
            if not child_sitemaps:
                logging.warning(f"sitemapindex 无子项: {url}")
                return []
            urls = []
            matched = 0
            for child in child_sitemaps:
                if not matches_patterns(child, include_sitemap_patterns):
                    continue
                matched += 1
                urls.extend(
                    process_sitemap(
                        child,
                        include_sitemap_patterns=include_sitemap_patterns,
                        visited=visited,
                        max_depth=max_depth - 1,
                    )
                )
            if matched == 0:
                logging.warning(
                    f"sitemapindex 子项均未匹配 include_sitemap_patterns: {url}"
                )
            elif not urls:
                logging.warning(f"sitemapindex 展开后无 URL: {url}")
            return urls

        if b'<urlset' in content:
            urls = parse_xml(content)
        else:
            urls = parse_txt(content.decode('utf-8', errors='ignore'))

        if not urls:
            logging.warning(f"sitemap 无 URL 内容: {url}")
        return urls
    except Exception as e:
        logging.error(f"Unexpected error processing {url}: {str(e)}")
        return []
