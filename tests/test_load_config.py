import pytest

import airQuality


def test_missing_file_raises(tmp_path):
    missing = tmp_path / "absent.conf"
    with pytest.raises(SystemExit, match="Config file not found"):
        airQuality.load_config(str(missing))


def test_missing_section_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[other]\nkey = value\n")
    with pytest.raises(SystemExit, match="Invalid config"):
        airQuality.load_config(str(conf))


def test_placeholder_api_key_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = YOUR_PURPLEAIR_API_KEY\nsensor_id = 12345\n"
    )
    with pytest.raises(SystemExit, match="Set a real api_key"):
        airQuality.load_config(str(conf))


def test_empty_api_key_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key = \nsensor_id = 12345\n")
    with pytest.raises(SystemExit, match="Set a real api_key"):
        airQuality.load_config(str(conf))


def test_non_integer_sensor_id_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key = real-key\nsensor_id = not-a-number\n")
    with pytest.raises(SystemExit, match="Invalid config"):
        airQuality.load_config(str(conf))


def test_valid_config_returns_key_and_id(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key = real-key\nsensor_id = 98765\n")
    api_key, sensor_id, weather, city, theme = airQuality.load_config(str(conf))
    assert api_key == "real-key"
    assert sensor_id == 98765
    assert weather is None
    assert city == "Campbell"
    assert theme == "default"


def test_api_key_whitespace_is_stripped(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key =   padded-key   \nsensor_id = 1\n")
    api_key, _, _, _, _ = airQuality.load_config(str(conf))
    assert api_key == "padded-key"


def test_weather_section_returns_coords(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[weather]\nlatitude = 37.5\nlongitude = -121.9\n"
    )
    _, _, weather, _, _ = airQuality.load_config(str(conf))
    assert weather == (37.5, -121.9)


def test_weather_section_missing_field_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[weather]\nlatitude = 37.5\n"
    )
    with pytest.raises(SystemExit, match=r"\[weather\]"):
        airQuality.load_config(str(conf))


def test_weather_section_non_numeric_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[weather]\nlatitude = north\nlongitude = -121.9\n"
    )
    with pytest.raises(SystemExit, match=r"\[weather\]"):
        airQuality.load_config(str(conf))


def test_display_city_overrides_default(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ncity = San Jose\n"
    )
    _, _, _, city, _ = airQuality.load_config(str(conf))
    assert city == "San Jose"


def test_display_city_whitespace_is_stripped(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ncity =   Oakland   \n"
    )
    _, _, _, city, _ = airQuality.load_config(str(conf))
    assert city == "Oakland"


def test_display_city_blank_falls_back_to_default(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ncity =   \n"
    )
    _, _, _, city, _ = airQuality.load_config(str(conf))
    assert city == "Campbell"


def test_zero_sensor_id_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key = real-key\nsensor_id = 0\n")
    with pytest.raises(SystemExit, match="sensor_id"):
        airQuality.load_config(str(conf))


def test_negative_sensor_id_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key = real-key\nsensor_id = -3\n")
    with pytest.raises(SystemExit, match="sensor_id"):
        airQuality.load_config(str(conf))


@pytest.mark.parametrize(
    "lat,lon",
    [(91.0, 0.0), (-90.5, 0.0), (0.0, 181.0), (0.0, -181.0)],
)
def test_weather_coords_out_of_range_raises(tmp_path, lat, lon):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        f"[weather]\nlatitude = {lat}\nlongitude = {lon}\n"
    )
    with pytest.raises(SystemExit, match="coordinates"):
        airQuality.load_config(str(conf))


@pytest.mark.parametrize(
    "lat,lon",
    [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0)],
)
def test_weather_coords_at_boundaries_accepted(tmp_path, lat, lon):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        f"[weather]\nlatitude = {lat}\nlongitude = {lon}\n"
    )
    _, _, weather, _, _ = airQuality.load_config(str(conf))
    assert weather == (lat, lon)


def test_env_var_overrides_config_api_key(tmp_path, monkeypatch):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = file-key\nsensor_id = 1\n"
    )
    monkeypatch.setenv("PURPLEAIR_API_KEY", "env-key")
    api_key, _, _, _, _ = airQuality.load_config(str(conf))
    assert api_key == "env-key"


def test_env_var_used_when_config_has_placeholder(tmp_path, monkeypatch):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = YOUR_PURPLEAIR_API_KEY\nsensor_id = 1\n"
    )
    monkeypatch.setenv("PURPLEAIR_API_KEY", "env-key")
    api_key, _, _, _, _ = airQuality.load_config(str(conf))
    assert api_key == "env-key"


def test_env_var_blank_falls_back_to_config(tmp_path, monkeypatch):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = file-key\nsensor_id = 1\n"
    )
    monkeypatch.setenv("PURPLEAIR_API_KEY", "")
    api_key, _, _, _, _ = airQuality.load_config(str(conf))
    assert api_key == "file-key"


def test_env_var_whitespace_only_falls_back_to_config(tmp_path, monkeypatch):
    """A misconfigured EnvironmentFile= shouldn't clobber a valid file key."""
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = file-key\nsensor_id = 1\n"
    )
    monkeypatch.setenv("PURPLEAIR_API_KEY", "   \t\n")
    api_key, _, _, _, _ = airQuality.load_config(str(conf))
    assert api_key == "file-key"


def test_display_theme_default_when_section_missing(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key = real-key\nsensor_id = 1\n")
    _, _, _, _, theme = airQuality.load_config(str(conf))
    assert theme == "default"


def test_display_theme_minimal_accepted(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ntheme = minimal\n"
    )
    _, _, _, _, theme = airQuality.load_config(str(conf))
    assert theme == "minimal"


def test_display_theme_fredoka_accepted(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ntheme = fredoka\n"
    )
    _, _, _, _, theme = airQuality.load_config(str(conf))
    assert theme == "fredoka"


def test_display_theme_is_case_insensitive(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ntheme = Minimal\n"
    )
    _, _, _, _, theme = airQuality.load_config(str(conf))
    assert theme == "minimal"


def test_display_theme_blank_falls_back_to_default(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ntheme =   \n"
    )
    _, _, _, _, theme = airQuality.load_config(str(conf))
    assert theme == "default"


def test_display_theme_unknown_value_raises(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ntheme = neon\n"
    )
    with pytest.raises(SystemExit, match="theme"):
        airQuality.load_config(str(conf))
