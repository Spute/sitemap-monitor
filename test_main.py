from datetime import datetime

from build_trend_urls import DEFAULT_ANCHOR, build_trends_url
from notify import build_burst_card, slug_to_trends_keyword
from sitemap import matches_patterns, parse_txt, parse_xml, process_sitemap
from slug import extract_slug, is_game_slug, to_game_entries
from store import GameStore, open_store
from translate import (
    attach_zh_names,
    contains_cjk,
    slug_to_phrase,
    translate_phrase,
    translate_slugs,
)


def test_parse_xml():
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/a</loc></url>
      <url><loc>https://example.com/b</loc></url>
    </urlset>
    """
    assert parse_xml(content) == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_parse_xml_skips_image_loc():
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
      <url>
        <loc>https://example.com/sport/soccer</loc>
        <image:image>
          <image:loc>https://cdn.example.com/soccer.avif</image:loc>
        </image:image>
      </url>
    </urlset>
    """
    assert parse_xml(content) == ["https://example.com/sport/soccer"]


def test_parse_xml_sitemapindex():
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/sitemap-games.xml</loc></sitemap>
    </sitemapindex>
    """
    assert parse_xml(content) == ["https://example.com/sitemap-games.xml"]


def test_parse_txt():
    content = "https://example.com/a\n\nhttps://example.com/b\n"
    assert parse_txt(content) == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_matches_patterns():
    assert matches_patterns("https://example.com/en/sitemap", None)
    assert matches_patterns("https://example.com/en/sitemap", [])
    assert matches_patterns(
        "https://example.com/en/sitemap",
        ["https://example.com/en/"],
    )
    assert not matches_patterns(
        "https://example.com/nl/sitemap",
        ["https://example.com/en/"],
    )


def test_extract_slug_default():
    assert extract_slug("https://1games.io/hill-sprint") == "hill-sprint"
    assert extract_slug("https://1games.io/") is None
    assert extract_slug("not-a-url") is None


def test_extract_slug_with_marker():
    assert (
        extract_slug(
            "https://www.crazygames.com/en/game/wacky-flip",
            game_path_marker="/game/",
        )
        == "wacky-flip"
    )
    assert (
        extract_slug(
            "https://www.crazygames.com/en/t/action",
            game_path_marker="/game/",
        )
        is None
    )


def test_extract_slug_strips_id_suffix():
    assert (
        extract_slug(
            "https://playhop.com/app/foosball-96247",
            game_path_marker="/app/",
            strip_id_suffix=True,
        )
        == "foosball"
    )
    assert (
        extract_slug(
            "https://playhop.com/app/get-10-96433",
            game_path_marker="/app/",
            strip_id_suffix=True,
        )
        == "get-10"
    )
    assert (
        extract_slug(
            "https://playhop.com/app/foosball-96247",
            game_path_marker="/app/",
        )
        == "foosball-96247"
    )


def test_extract_slug_normalizes_underscores():
    assert (
        extract_slug(
            "https://zh.y8.com/games/crazy_goat_simulator",
            game_path_marker="/games/",
        )
        == "crazy-goat-simulator"
    )
    assert (
        extract_slug(
            "https://zh.y8.com/tags/action",
            game_path_marker="/games/",
        )
        is None
    )


def test_extract_slug_strips_html_suffix():
    assert (
        extract_slug(
            "https://www.brightygames.com/games/sniper-for-brainrot.html",
            game_path_marker="/games/",
        )
        == "sniper-for-brainrot"
    )


def test_extract_slug_last_segment():
    assert (
        extract_slug(
            "https://www.playagame.io/arcade/cut-the-rope/",
            slug_last_segment=True,
        )
        == "cut-the-rope"
    )
    assert extract_slug("https://www.playagame.io/arcade/cut-the-rope/") == (
        "arcade/cut-the-rope"
    )
    assert (
        extract_slug(
            "https://www.friv-2018.com/tag/reflex-games",
            slug_last_segment=True,
        )
        is None
    )


def test_extract_slug_after_marker():
    assert (
        extract_slug(
            "https://www.friv.com/z/games/2048numbermatch/game.html",
            game_path_marker="/games/",
            slug_after_marker=True,
        )
        == "2048numbermatch"
    )
    assert (
        extract_slug(
            "https://www.friv.com/z/play/games.html",
            game_path_marker="/games/",
            slug_after_marker=True,
        )
        is None
    )
    assert (
        extract_slug(
            "https://www.friv.com/z/games/2048numbermatch/game.html",
            game_path_marker="/games/",
        )
        == "game"
    )


def test_is_game_slug_filters_noise():
    assert is_game_slug("hill-sprint")
    assert not is_game_slug("new-games")
    assert not is_game_slug("recently-played")
    assert not is_game_slug("top-rated-games")
    assert not is_game_slug("about-us")
    assert not is_game_slug("tag/indie")
    assert not is_game_slug("action.games")
    assert not is_game_slug("category/io-games")
    assert not is_game_slug("phrazle-1631")


def test_to_game_entries_dedupes_and_filters():
    urls = [
        "https://1games.io/new-games",
        "https://1games.io/hill-sprint",
        "https://1games.io/hill-sprint?ref=1",
        "https://1games.io/action.games",
        "https://1games.io/tag/indie",
    ]
    assert to_game_entries(urls) == [
        ("hill-sprint", "https://1games.io/hill-sprint"),
    ]


def test_open_store_requires_turso_env(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    try:
        open_store()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "TURSO_DATABASE_URL" in str(exc)


def test_open_store_local_path(tmp_path):
    store = open_store(db_path=tmp_path / "games.db")
    try:
        assert store.backend == "sqlite"
        assert store.stats()["games"] == 0
    finally:
        store.close()


def test_sync_site_baseline_then_detects_new(tmp_path):
    today = datetime.now().strftime("%Y-%m-%d")
    store = GameStore(tmp_path / "games.db")
    try:
        # 首跑：建基线，不产生 events
        first = store.sync_site(
            "Demo",
            [("hill-sprint", "https://example.com/hill-sprint")],
            today,
            burst_window_days=7,
        )
        assert first == []
        assert store.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0

        # 再跑：只把新 slug 记为新增
        second = store.sync_site(
            "Demo",
            [
                ("hill-sprint", "https://example.com/hill-sprint"),
                ("tap-road-2", "https://example.com/tap-road-2"),
            ],
            today,
            burst_window_days=7,
        )
        assert second == ["tap-road-2"]
        assert store.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    finally:
        store.close()


def test_game_store_burst(tmp_path):
    today = datetime.now().strftime("%Y-%m-%d")
    store = GameStore(tmp_path / "games.db")
    try:
        # 先给各站建基线，再写入跨站新增，避免首跑被当成 baseline
        store.sync_site("1Games", [("seed-a", "https://1games.io/seed-a")], today, 7)
        store.sync_site("Wordle2", [("seed-b", "https://wordle2.io/seed-b")], today, 7)
        store.sync_site("Sprunki", [("seed-c", "https://sprunki.org/seed-c")], today, 7)

        store.sync_site(
            "1Games",
            [
                ("seed-a", "https://1games.io/seed-a"),
                ("hill-sprint", "https://1games.io/hill-sprint"),
            ],
            today,
            7,
        )
        store.sync_site(
            "Wordle2",
            [
                ("seed-b", "https://wordle2.io/seed-b"),
                ("hill-sprint", "https://wordle2.io/hill-sprint"),
            ],
            today,
            7,
        )
        store.sync_site(
            "Sprunki",
            [
                ("seed-c", "https://sprunki.org/seed-c"),
                ("solo-game", "https://sprunki.org/solo-game"),
            ],
            today,
            7,
        )

        burst = store.burst_games(window_days=7, threshold=2)
        assert len(burst) == 1
        assert burst[0]["slug"] == "hill-sprint"
        assert burst[0]["burst_sites"] == 2
        assert burst[0]["first_site"] == "1Games"
        assert burst[0]["first_url"] == "https://1games.io/hill-sprint"
        assert burst[0]["first_seen"] == today
        assert burst[0]["today_sites"] == 2
        assert burst[0]["site_count"] == 2
        assert burst[0]["site_links"] == [
            {"site": "1Games", "url": "https://1games.io/hill-sprint"},
            {"site": "Wordle2", "url": "https://wordle2.io/hill-sprint"},
        ]

        involving = store.burst_games_involving(
            ["hill-sprint", "solo-game"],
            window_days=7,
            threshold=2,
        )
        assert [g["slug"] for g in involving] == ["hill-sprint"]
        assert store.slugs_with_events_on(today) == {"hill-sprint", "solo-game"}
        assert store.slugs_with_events_on("1999-01-01") == set()

        game = store.conn.execute(
            "SELECT site_count, heat_score FROM games WHERE slug = ?",
            ("hill-sprint",),
        ).fetchone()
        assert game["site_count"] == 2
        assert game["heat_score"] == 2 + 2 * 2
    finally:
        store.close()


def test_process_sitemap_index_recursive(monkeypatch):
    index_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/en/sitemap</loc></sitemap>
      <sitemap><loc>https://example.com/nl/sitemap</loc></sitemap>
    </sitemapindex>
    """
    en_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/game/a</loc></url>
      <url><loc>https://example.com/game/b</loc></url>
    </urlset>
    """
    nl_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/nl/game/c</loc></url>
    </urlset>
    """
    payloads = {
        "https://example.com/sitemap-index.xml": index_xml,
        "https://example.com/en/sitemap": en_xml,
        "https://example.com/nl/sitemap": nl_xml,
    }

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

    class FakeScraper:
        def get(self, url, timeout=10):
            return FakeResponse(payloads[url])

    monkeypatch.setattr("sitemap.cloudscraper.create_scraper", lambda: FakeScraper())

    urls = process_sitemap(
        "https://example.com/sitemap-index.xml",
        include_sitemap_patterns=["https://example.com/en/"],
    )
    assert urls == [
        "https://example.com/game/a",
        "https://example.com/game/b",
    ]


def test_fetch_sitemap_retries_once(monkeypatch):
    import requests
    from sitemap import fetch_sitemap_content

    calls = {"n": 0}

    class FakeResponse:
        content = b"https://example.com/a\n"

        def raise_for_status(self):
            return None

    class FakeScraper:
        def get(self, url, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.exceptions.ReadTimeout("timed out")
            return FakeResponse()

    monkeypatch.setattr("sitemap.cloudscraper.create_scraper", lambda: FakeScraper())
    monkeypatch.setattr("sitemap.time.sleep", lambda _: None)

    content = fetch_sitemap_content("https://example.com/sitemap.xml")
    assert content == b"https://example.com/a\n"
    assert calls["n"] == 2


def test_slug_to_trends_keyword():
    assert slug_to_trends_keyword("hill-sprint") == "hill sprint"
    assert slug_to_trends_keyword("  tap-road-2 ") == "tap road 2"


def test_build_burst_card_includes_trends_links():
    card = build_burst_card(
        [
            {
                "slug": "hill-sprint",
                "first_site": "1Games",
                "first_seen": "2026-08-11",
                "first_url": "https://1games.io/hill-sprint",
                "today_sites": 1,
                "site_count": 2,
                "sites": "1Games,Wordle2",
                "site_links": [
                    {"site": "1Games", "url": "https://1games.io/hill-sprint"},
                    {"site": "Wordle2", "url": "https://wordle2.io/hill-sprint"},
                ],
            },
            {
                "slug": "tap-road",
                "first_site": "1Games",
                "first_seen": "2026-08-11",
                "first_url": "https://1games.io/tap-road",
                "today_sites": 2,
                "site_count": 2,
                "sites": "1Games,Wordle2",
            },
        ],
        window_days=7,
    )
    body = card["card"]["elements"][0]["text"]["content"]
    hill_url = build_trends_url([DEFAULT_ANCHOR, "hill sprint"])
    tap_url = build_trends_url([DEFAULT_ANCHOR, "tap road"])
    assert f"[Trends]({hill_url})" in body
    assert f"[Trends]({tap_url})" in body
    batch_url = build_trends_url(
        [DEFAULT_ANCHOR, "hill sprint", "tap road"]
    )
    assert "**Google Trends 对比查询**" in body
    assert f"```\n{batch_url}\n```" in body
    assert "第 1 批" not in body


def test_build_burst_card_includes_zh():
    card = build_burst_card(
        [
            {
                "slug": "hill-sprint",
                "zh": "山地冲刺",
                "first_site": "1Games",
                "first_seen": "2026-08-11",
                "first_url": "https://1games.io/hill-sprint",
                "today_sites": 1,
                "site_count": 2,
                "sites": "1Games",
            }
        ],
        window_days=7,
    )
    body = card["card"]["elements"][0]["text"]["content"]
    assert "**[hill-sprint](https://1games.io/hill-sprint)**（山地冲刺）" in body


def test_slug_to_phrase_and_cjk():
    assert slug_to_phrase("hill-sprint") == "hill sprint"
    assert contains_cjk("山地冲刺")
    assert not contains_cjk("hill sprint")
    assert not contains_cjk("")


def test_translate_phrase_google_then_mymemory(monkeypatch):
    calls = []

    def fake_google(phrase):
        calls.append(("google", phrase))
        return "山地冲刺"

    def fake_mymemory(phrase):
        calls.append(("mymemory", phrase))
        return "丘陵冲刺"

    monkeypatch.setattr("translate._translate_google", fake_google)
    monkeypatch.setattr("translate._translate_mymemory", fake_mymemory)
    zh, provider = translate_phrase("hill sprint")
    assert zh == "山地冲刺"
    assert provider == "google"
    assert calls == [("google", "hill sprint")]


def test_translate_phrase_falls_back(monkeypatch):
    import requests

    def boom(phrase):
        raise requests.RequestException("blocked")

    monkeypatch.setattr("translate._translate_google", boom)
    monkeypatch.setattr("translate._translate_mymemory", lambda phrase: "几何冲刺")
    zh, provider = translate_phrase("geometry dash")
    assert zh == "几何冲刺"
    assert provider == "mymemory"


def test_translate_slugs_realtime(monkeypatch):
    called = []

    def fake_google(phrase):
        called.append(phrase)
        return "山地冲刺"

    monkeypatch.setattr("translate._translate_google", fake_google)
    monkeypatch.setattr("translate.time.sleep", lambda _: None)
    result = translate_slugs(["hill-sprint", "hill-sprint"])
    assert result == {"hill-sprint": "山地冲刺"}
    assert called == ["hill sprint"]


def test_attach_zh_names_disabled(monkeypatch):
    monkeypatch.setattr(
        "translate.translate_phrase",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("disabled")),
    )
    games = [{"slug": "hill-sprint"}]
    attach_zh_names(games, {"translation": {"enabled": False}})
    assert "zh" not in games[0]


def test_process_sitemap_live():
    urls = process_sitemap("https://1games.io/sitemap.xml")
    assert isinstance(urls, list)
    assert urls
    entries = to_game_entries(urls)
    assert entries
    assert all("/" not in slug for slug, _ in entries)


def test_process_sitemap_live_crazygames():
    """CrazyGames 英文子 sitemap 应能展开出游戏页。"""
    urls = process_sitemap(
        "https://www.crazygames.com/sitemap-index.xml",
        include_sitemap_patterns=["https://www.crazygames.com/en/"],
    )
    assert isinstance(urls, list)
    assert any("/game/" in url for url in urls)
