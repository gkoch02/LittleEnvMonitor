import airQuality


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    cache_path = tmp_path / "airquality" / "last_reading.json"
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(cache_path))

    data = {
        "PM2.5": 8.2,
        "PM10": 12,
        "Temp": 72,
        "Humidity": 38,
        "Time": "10:30 AM",
    }
    airQuality.write_cache(data)

    assert airQuality.read_cache() == data


def test_read_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(tmp_path / "missing.json"))
    assert airQuality.read_cache() is None


def test_read_returns_none_when_corrupt(tmp_path, monkeypatch):
    cache = tmp_path / "corrupt.json"
    cache.write_text("not json{{{")
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(cache))
    assert airQuality.read_cache() is None


def test_write_creates_parent_dirs(tmp_path, monkeypatch):
    cache_path = tmp_path / "deep" / "nested" / "cache.json"
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(cache_path))

    airQuality.write_cache({"PM2.5": 1})

    assert cache_path.exists()


def test_write_is_atomic(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(cache_path))

    airQuality.write_cache({"PM2.5": 5})

    assert cache_path.exists()
    assert not (tmp_path / "cache.json.tmp").exists()
