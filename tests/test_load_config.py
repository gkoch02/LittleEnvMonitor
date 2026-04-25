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
    api_key, sensor_id = airQuality.load_config(str(conf))
    assert api_key == "real-key"
    assert sensor_id == 98765


def test_api_key_whitespace_is_stripped(tmp_path):
    conf = tmp_path / "airquality.conf"
    conf.write_text("[purpleair]\napi_key =   padded-key   \nsensor_id = 1\n")
    api_key, _ = airQuality.load_config(str(conf))
    assert api_key == "padded-key"
