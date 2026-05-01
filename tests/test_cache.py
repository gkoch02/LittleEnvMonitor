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


def test_failed_write_preserves_previous_cache(tmp_path, monkeypatch):
    """The whole point of the .tmp + os.replace dance: a crash mid-write must
    not leave an empty/partial cache that the next tick treats as authoritative."""
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(cache_path))

    airQuality.write_cache({"PM2.5": 7.7, "PM10": 9})
    original = cache_path.read_text()

    # Force the second write to fail mid-flight (after the tmp file is opened
    # but before os.replace runs).
    real_replace = airQuality.os.replace

    def _boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(airQuality.os, "replace", _boom)
    try:
        airQuality.write_cache({"PM2.5": 99.9})
    except OSError:
        pass
    monkeypatch.setattr(airQuality.os, "replace", real_replace)

    # Previous cache must still be intact and readable.
    assert cache_path.read_text() == original
    assert airQuality.read_cache() == {"PM2.5": 7.7, "PM10": 9}
