import os
import re

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
    assert city == ""
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
        ("city =   ", ""),
    ],
    ids=["override", "stripped", "blank"],
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


@pytest.mark.parametrize(
    "text,expected",
    [
        (BASE + "[display]\nthem = minimal\n", "Unknown key 'them' in [display]"),
        (BASE + "sensorid = 2\n", "Unknown key 'sensorid' in [purpleair]"),
        (BASE + "[dispaly]\ntheme = minimal\n", "Unknown section [dispaly]"),
        (BASE + "[DEFAULT]\nfoo = 1\n", "Unknown key 'foo' in [DEFAULT]"),
    ],
    ids=["key", "key-in-first-section", "section", "default-section"],
)
def test_unknown_config_name_warns_and_is_ignored(tmp_path, caplog, text, expected):
    result = _load(tmp_path, text)
    assert result[-1] == "default"
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert expected in warnings[0]
    assert str(tmp_path / "airquality.conf") in warnings[0]


@pytest.mark.parametrize(
    "text,hint",
    [
        (BASE + "[display]\nthem = minimal\n", "did you mean 'theme'?"),
        (BASE + "[dispaly]\ntheme = minimal\n", "did you mean 'display'?"),
        (BASE + "[display]\nzzz = 1\n", None),
    ],
    ids=["close-key", "close-section", "no-close-match"],
)
def test_unknown_config_name_suggests_close_match(tmp_path, caplog, text, hint):
    _load(tmp_path, text)
    (warning,) = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    if hint is None:
        assert "did you mean" not in warning
    else:
        assert warning.endswith(hint)


def test_full_example_config_has_no_unknown_keys(tmp_path, caplog):
    example = os.path.join(airQuality.REPO_DIR, "airquality.conf.example")
    with open(example) as f:
        text = f.read().replace("YOUR_PURPLEAIR_API_KEY", "real-key").replace(
            "YOUR_SENSOR_ID", "1"
        )
    _load(tmp_path, text)
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_default_section_key_is_not_reported_per_section(tmp_path, caplog):
    _load(tmp_path, "[DEFAULT]\ncity = X\n" + BASE + "[display]\ntheme = minimal\n")
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("api_key = k\n" + BASE, r"line 1: 'api_key = k' comes before any \[section\] header"),
        (BASE + "sensor_id = 2\n", r"line 4: 'sensor_id' appears twice in \[purpleair\]"),
        (BASE + "[purpleair]\n", r"line 4: \[purpleair\] appears twice"),
        (BASE + "oops no equals\n", r"line 4: can't read 'oops no equals'"),
        (
            "[purpleair]\napi_key = 50%off\nsensor_id = 1\n",
            r"'api_key' in \[purpleair\]: .*write '%%' for a literal '%'",
        ),
    ],
    ids=["no-section-header", "duplicate-key", "duplicate-section", "bad-line", "bare-percent"],
)
def test_unparseable_config_raises_friendly_error(tmp_path, text, expected):
    path = str(tmp_path / "airquality.conf")
    with pytest.raises(SystemExit, match=f"^Invalid config at {re.escape(path)}: {expected}"):
        _load(tmp_path, text)


def test_binary_config_raises_friendly_error(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_bytes(b"\xff\xfe\x00[purpleair]\n")
    with pytest.raises(SystemExit, match="Invalid config at .*not a text file"):
        airQuality.load_config(str(conf))
