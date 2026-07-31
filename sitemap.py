"""拉取并解析 sitemap（含 sitemapindex 递归展开）。"""

import gzip
import logging

import cloudscraper
import requests
from bs4 import BeautifulSoup


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


def process_sitemap(url, include_sitemap_patterns=None, visited=None, max_depth=3):
    """拉取 sitemap，返回页面 URL 列表。

    遇到 sitemapindex 会递归子 sitemap；可用 include_sitemap_patterns
    只跟进匹配的子项（例如只抓英文 locale）。
    """
    if visited is None:
        visited = set()
    if url in visited or max_depth < 0:
        return []
    visited.add(url)

    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, timeout=30)
        response.raise_for_status()

        content = response.content
        # gzip magic number
        if content[:2] == b'\x1f\x8b':
            content = gzip.decompress(content)

        if b'<sitemapindex' in content:
            child_sitemaps = parse_xml(content)
            urls = []
            for child in child_sitemaps:
                if not matches_patterns(child, include_sitemap_patterns):
                    continue
                urls.extend(
                    process_sitemap(
                        child,
                        include_sitemap_patterns=include_sitemap_patterns,
                        visited=visited,
                        max_depth=max_depth - 1,
                    )
                )
            return urls
        if b'<urlset' in content:
            return parse_xml(content)
        return parse_txt(content.decode('utf-8'))
    except requests.RequestException as e:
        logging.error(f"Error processing {url}: {str(e)}")
        return []
    except Exception as e:
        logging.error(f"Unexpected error processing {url}: {str(e)}")
        return []
