from datetime import datetime

from fastapi.testclient import TestClient

import api
from store import GameStore


def _seed(store: GameStore):
    today = datetime.now().strftime("%Y-%m-%d")
    store.sync_site("1Games", [("seed-a", "https://1games.io/seed-a")], today, 7)
    store.sync_site("Wordle2", [("seed-b", "https://wordle2.io/seed-b")], today, 7)
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


def test_api_burst_and_game_detail(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    store = GameStore(db_path)
    _seed(store)
    store.close()

    monkeypatch.setattr(
        api, "_open_store", lambda: GameStore(db_path, check_same_thread=False)
    )
    monkeypatch.setattr(
        api,
        "_heat_defaults",
        {"burst_window_days": 7, "alert_site_threshold": 2},
    )

    with TestClient(api.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        stats = client.get("/stats")
        assert stats.status_code == 200
        assert stats.json()["games"] >= 1

        burst = client.get("/games/burst")
        assert burst.status_code == 200
        body = burst.json()
        assert any(g["slug"] == "hill-sprint" for g in body)

        games = client.get("/games", params={"q": "hill", "min_site_count": 2})
        assert games.status_code == 200
        assert games.json()[0]["slug"] == "hill-sprint"

        detail = client.get("/games/hill-sprint")
        assert detail.status_code == 200
        data = detail.json()
        assert data["game"]["site_count"] == 2
        assert len(data["sightings"]) == 2

        missing = client.get("/games/not-exists-slug")
        assert missing.status_code == 404

        events = client.get("/events", params={"slug": "hill-sprint"})
        assert events.status_code == 200
        assert len(events.json()) == 2

        sites = client.get("/sites")
        assert sites.status_code == 200
        assert {s["site"] for s in sites.json()} >= {"1Games", "Wordle2"}

        site_games = client.get("/sites/1Games/games")
        assert site_games.status_code == 200
        assert any(g["slug"] == "hill-sprint" for g in site_games.json())
