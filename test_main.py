from main import compare_data, parse_txt, parse_xml, process_sitemap


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


def test_process_sitemap_live():
    urls = process_sitemap("https://1games.io/sitemap.xml")
    assert isinstance(urls, list)
    assert urls
