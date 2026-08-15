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
# Playhop 等站把内部 ID 挂在 slug 后，如 foosball-96247
ID_SUFFIX_RE = re.compile(r'-\d+$')


def extract_slug(
    url,
    game_path_marker=None,
    strip_id_suffix=False,
    slug_after_marker=False,
    slug_last_segment=False,
):
    """从页面 URL 提取游戏关键词。

    - 默认：取完整 path（去首尾 `/`，小写），如 `/hill-sprint` → `hill-sprint`
    - 配置了 game_path_marker（如 `/game/`）：仅当 path 含该段时才提取，
      slug 默认取最后一段，适配 CrazyGames 等深层路径
    - slug_after_marker：改为取 marker 后一段（Friv 的 `/z/games/{slug}/game.html`）
    - slug_last_segment：无 marker 时也取最后一段（PlayA 的 `/{category}/{slug}/`）
    - strip_id_suffix：去掉末尾 `-数字`（Playhop 的 `/app/name-96247`）
    - 下划线统一成连字符，便于 Y8 的 `crazy_goat_simulator` 与其他站对齐
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
        if slug_after_marker:
            idx = segments.index(marker)
            if idx + 1 >= len(segments):
                return None
            slug = segments[idx + 1] or None
        else:
            slug = segments[-1] or None
    elif slug_last_segment:
        slug = path.split('/')[-1] or None
    else:
        slug = path

    if strip_id_suffix and slug:
        stripped = ID_SUFFIX_RE.sub('', slug)
        slug = stripped or slug
    if slug:
        slug = slug.replace('_', '-')
    return slug


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


def to_game_entries(
    urls,
    game_path_marker=None,
    strip_id_suffix=False,
    slug_after_marker=False,
    slug_last_segment=False,
):
    """URL 列表 → 去重后的 (slug, url)，保持首次出现顺序。"""
    seen = set()
    entries = []
    for url in urls:
        slug = extract_slug(
            url,
            game_path_marker=game_path_marker,
            strip_id_suffix=strip_id_suffix,
            slug_after_marker=slug_after_marker,
            slug_last_segment=slug_last_segment,
        )
        if not is_game_slug(slug) or slug in seen:
            continue
        seen.add(slug)
        entries.append((slug, url))
    return entries
