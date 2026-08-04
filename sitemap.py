"""拉取并解析 sitemap（含 sitemapindex 递归展开）。"""

import gzip
import logging
import time

import cloudscraper
import requests
from bs4 import BeautifulSoup

# 超时 / 连接重置等多属瞬时网络问题，失败后重试 1 次
FETCH_TIMEOUT = 10
FETCH_RETRIES = 1
FETCH_RETRY_DELAY_SEC = 1


def matches_patterns(url, patterns):
    """patterns 为空则全部接受；否则 URL 需包含任一子串。"""
    if not patterns:
        return True
    return any(pattern in url for pattern in patterns)


def parse_xml(content):
    """从 urlset / sitemapindex 的 <loc> 提取 URL。"""
    urls = []
    soup = BeautifulSoup(content, 'xml')
    for loc in soup.find_all('loc'):
        url = loc.get_text().strip()
        if url:
            urls.append(url)
    return urls


def parse_txt(content):
    """纯文本 sitemap：每行一个 URL。"""
    return [line.strip() for line in content.splitlines() if line.strip()]


def _get_sitemap(url):
    """优先 cloudscraper（过 Cloudflare）；遇 403/401/429 再回退普通 requests。"""
    scraper = cloudscraper.create_scraper()
    try:
        response = scraper.get(url, timeout=FETCH_TIMEOUT)
        response.raise_for_status()
        return response.content
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status not in (401, 403, 429):
            raise
        response = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        return response.content


def fetch_sitemap_content(url):
    """拉取 sitemap 原始内容；网络错误时重试一次。失败返回 None。"""
    last_error = None
    attempts = FETCH_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            return _get_sitemap(url)
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
