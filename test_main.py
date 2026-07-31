from main import (
    compare_data,
    matches_patterns,
    parse_txt,
    parse_xml,
    process_sitemap,
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


def test_compare_data_no_latest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert compare_data("Demo", ["https://example.com/a"]) == []


def test_compare_data_detects_new(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    latest = tmp_path / "latest"
    latest.mkdir()
    (latest / "Demo.json").write_text("https://example.com/a\n", encoding="utf-8")

    assert compare_data(
        "Demo",
        ["https://example.com/a", "https://example.com/b"],
    ) == ["https://example.com/b"]


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
        def get(self, url, timeout=30):
            return FakeResponse(payloads[url])

    monkeypatch.setattr("main.cloudscraper.create_scraper", lambda: FakeScraper())

    urls = process_sitemap(
        "https://example.com/sitemap-index.xml",
        include_sitemap_patterns=["https://example.com/en/"],
    )
    assert urls == [
        "https://example.com/game/a",
        "https://example.com/game/b",
    ]


def test_process_sitemap_live():
    urls = process_sitemap("https://1games.io/sitemap.xml")
    assert isinstance(urls, list)
    assert urls


def test_process_sitemap_live_crazygames():
    urls = process_sitemap(
        "https://www.crazygames.com/sitemap-index.xml",
        include_sitemap_patterns=["https://www.crazygames.com/en/"],
    )
    print(urls)
    assert isinstance(urls, list)
    assert urls
    assert all(not u.strip().startswith("<") for u in urls)
    assert any("/game/" in u for u in urls)