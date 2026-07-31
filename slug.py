"""从 URL 提取游戏关键词（slug），并过滤非游戏页噪音。"""

import re
from urllib.parse import urlparse

# 导航 / 列表 / 静态页等，不能当作游戏词
NOISE_EXACT = frozenset({
    '',
    'updated',
    'new-games',
    'hot-games',
    'recents',
    'all-tags',
    'trending-games',
    'popular-games',
    'top-popular',
    'online',
    'pratice',
    'practice',
    'about-us',
    'contact-us',
    'privacy-policy',
    'terms-of-service',
    'terms',
    'cookie-policy',
    'disclaimer',
    'dmca',
    'faq',
    'blog',
    'login',
    'signup',
    'register',
    'search',
    'sitemap',
})
NOISE_PREFIXES = ('tag/', 'category/', 'tags/', 'blog/', 'page/')
NOISE_SUFFIXES = ('.games',)
# 站点连载页，如 phrazle-1631
SERIAL_SLUG_RE = re.compile(r'^(phrazle)-\d+$')


def extract_slug(url, game_path_marker=None):
    """从页面 URL 提取游戏关键词。

    - 默认：取完整 path（去首尾 `/`，小写），如 `/hill-sprint` → `hill-sprint`
    - 配置了 game_path_marker（如 `/game/`）：仅当 path 含该段时才提取，
      slug 取最后一段，适配 CrazyGames 等深层路径
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith('http'):
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    path = parsed.path.strip('/')
    if not path:
        return None
    path = path.lower()

    if game_path_marker:
        marker = game_path_marker.strip('/').lower()
        segments = path.split('/')
        if marker not in segments:
            return None
        return segments[-1] or None

    return path


def is_game_slug(slug):
    """判断 slug 是否像游戏页（排除导航、分类、静态页、连载页）。"""
    if not slug or not isinstance(slug, str):
        return False
    slug = slug.lower().strip('/')
    if slug in NOISE_EXACT:
        return False
    if any(slug.startswith(p) for p in NOISE_PREFIXES):
        return False
    if any(slug.endswith(s) for s in NOISE_SUFFIXES):
        return False
    if SERIAL_SLUG_RE.match(slug):
        return False
    # 无 marker 时，多段 path 通常是分类/标签，不当作游戏词
    if '/' in slug:
        return False
    return True


def to_game_entries(urls, game_path_marker=None):
    """URL 列表 → 去重后的 (slug, url)，保持首次出现顺序。"""
    seen = set()
    entries = []
    for url in urls:
        slug = extract_slug(url, game_path_marker=game_path_marker)
        if not is_game_slug(slug) or slug in seen:
            continue
        seen.add(slug)
        entries.append((slug, url))
    return entries
