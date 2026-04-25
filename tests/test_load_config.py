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
    api_key, sensor_id, weather, city = airQuality.load_config(str(conf))
    assert api_key == "real-key"
    assert sensor_id == 98765
    assert weather is None
    assert city == "Campbell"


def test_api_key_whitespace_is_stripped(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key =   padded-key   \nsensor_id = 1\n")
    api_key, _, _, _ = airQuality.load_config(str(conf))
    assert api_key == "padded-key"


def test_weather_section_returns_coords(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[weather]\nlatitude = 37.5\nlongitude = -121.9\n"
    )
    _, _, weather, _ = airQuality.load_config(str(conf))
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
    _, _, _, city = airQuality.load_config(str(conf))
    assert city == "San Jose"


def test_display_city_whitespace_is_stripped(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ncity =   Oakland   \n"
    )
    _, _, _, city = airQuality.load_config(str(conf))
    assert city == "Oakland"


def test_display_city_blank_falls_back_to_default(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 1\n"
        "[display]\ncity =   \n"
    )
    _, _, _, city = airQuality.load_config(str(conf))
    assert city == "Campbell"
