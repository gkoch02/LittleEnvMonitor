import pytest

import airQuality

BASE = "[purpleair]\napi_key = real-key\nsensor_id = 1\n"


def _load(tmp_path, text):
    conf = tmp_path / "airquality.conf"
    conf.write_text(text)
    return airQuality.load_config(str(conf))


def test_missing_file_raises(tmp_path):
    with pytest.raises(SystemExit, match="Config file not found"):
        airQuality.load_config(str(tmp_path / "absent.conf"))


def test_missing_section_raises(tmp_path):
    with pytest.raises(SystemExit, match="Invalid config"):
        _load(tmp_path, "[other]\nkey = value\n")


def test_placeholder_api_key_raises(tmp_path):
    with pytest.raises(SystemExit, match="Set a real api_key"):
        _load(tmp_path, "[purpleair]\napi_key = YOUR_PURPLEAIR_API_KEY\nsensor_id = 12345\n")


def test_empty_api_key_raises(tmp_path):
    with pytest.raises(SystemExit, match="Set a real api_key"):
        _load(tmp_path, "[purpleair]\napi_key = \nsensor_id = 12345\n")


def test_non_integer_sensor_id_raises(tmp_path):
    with pytest.raises(SystemExit, match="Invalid config"):
        _load(tmp_path, "[purpleair]\napi_key = real-key\nsensor_id = not-a-number\n")


def test_valid_config_returns_key_and_id(tmp_path):
    api_key, sensor_id, weather, city, theme = _load(
        tmp_path, "[purpleair]\napi_key = real-key\nsensor_id = 98765\n",
    )
    assert api_key == "real-key"
    assert sensor_id == 98765
    assert weather is None
    assert city == "Campbell"
    assert theme == "default"


def test_api_key_whitespace_is_stripped(tmp_path):
    api_key, *_ = _load(tmp_path, "[purpleair]\napi_key =   padded-key   \nsensor_id = 1\n")
    assert api_key == "padded-key"


def test_weather_section_returns_coords(tmp_path):
    _, _, weather, _, _ = _load(tmp_path, BASE + "[weather]\nlatitude = 37.5\nlongitude = -121.9\n")
    assert weather == (37.5, -121.9)


@pytest.mark.parametrize(
    "weather",
    ["[weather]\nlatitude = 37.5\n", "[weather]\nlatitude = north\nlongitude = -121.9\n"],
    ids=["missing-field", "non-numeric"],
)
def test_invalid_weather_section_raises(tmp_path, weather):
    with pytest.raises(SystemExit, match=r"\[weather\]"):
        _load(tmp_path, BASE + weather)


@pytest.mark.parametrize(
    "line,expected",
    [
        ("city = San Jose", "San Jose"),
        ("city =   Oakland   ", "Oakland"),
        ("city =   ", "Campbell"),
    ],
    ids=["override", "stripped", "blank-falls-back"],
)
def test_display_city(tmp_path, line, expected):
    _, _, _, city, _ = _load(tmp_path, BASE + f"[display]\n{line}\n")
    assert city == expected


@pytest.mark.parametrize("sensor_id", ["0", "-3"])
def test_non_positive_sensor_id_raises(tmp_path, sensor_id):
    with pytest.raises(SystemExit, match="sensor_id"):
        _load(tmp_path, f"[purpleair]\napi_key = real-key\nsensor_id = {sensor_id}\n")


@pytest.mark.parametrize(
    "lat,lon",
    [(91.0, 0.0), (-90.5, 0.0), (0.0, 181.0), (0.0, -181.0)],
)
def test_weather_coords_out_of_range_raises(tmp_path, lat, lon):
    with pytest.raises(SystemExit, match="coordinates"):
        _load(tmp_path, BASE + f"[weather]\nlatitude = {lat}\nlongitude = {lon}\n")


@pytest.mark.parametrize(
    "lat,lon",
    [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0)],
)
def test_weather_coords_at_boundaries_accepted(tmp_path, lat, lon):
    text = BASE + f"[weather]\nlatitude = {lat}\nlongitude = {lon}\n"
    _, _, weather, _, _ = _load(tmp_path, text)
    assert weather == (lat, lon)


@pytest.mark.parametrize(
    "file_key,env_value,expected",
    [
        ("file-key", "env-key", "env-key"),
        ("YOUR_PURPLEAIR_API_KEY", "env-key", "env-key"),
        ("file-key", "", "file-key"),
        # A misconfigured EnvironmentFile= shouldn't clobber a valid file key.
        ("file-key", "   \t\n", "file-key"),
    ],
    ids=["env-wins", "env-over-placeholder", "blank-env", "whitespace-env"],
)
def test_api_key_env_var_precedence(tmp_path, monkeypatch, file_key, env_value, expected):
    monkeypatch.setenv("PURPLEAIR_API_KEY", env_value)
    api_key, *_ = _load(tmp_path, f"[purpleair]\napi_key = {file_key}\nsensor_id = 1\n")
    assert api_key == expected


@pytest.mark.parametrize(
    "section,expected",
    [
        ("", "default"),
        ("[display]\ntheme = minimal\n", "minimal"),
        ("[display]\ntheme = fredoka\n", "fredoka"),
        ("[display]\ntheme = Minimal\n", "minimal"),
        ("[display]\ntheme =   \n", "default"),
    ],
    ids=["section-missing", "minimal", "fredoka", "case-insensitive", "blank"],
)
def test_display_theme(tmp_path, section, expected):
    *_, theme = _load(tmp_path, BASE + section)
    assert theme == expected


def test_display_theme_unknown_value_raises(tmp_path):
    with pytest.raises(SystemExit, match="theme"):
        _load(tmp_path, BASE + "[display]\ntheme = neon\n")
