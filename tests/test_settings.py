from cct import settings


def test_defaults_when_missing(tmp_path):
    assert settings.load(str(tmp_path / "s.json")) == {"font_px": settings.DEFAULT_FONT_PX}


def test_roundtrip_leaves_no_temp_file(tmp_path):
    p = str(tmp_path / "s.json")
    settings.save({"font_px": 23}, p)
    assert settings.load(p) == {"font_px": 23}
    assert not [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]


def test_corrupt_file_falls_back(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert settings.load(str(p)) == {"font_px": settings.DEFAULT_FONT_PX}


def test_wrong_shape_falls_back(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("[1, 2]", encoding="utf-8")
    assert settings.load(str(p)) == {"font_px": settings.DEFAULT_FONT_PX}


def test_loaded_value_snaps_to_an_offered_size(tmp_path):
    p = tmp_path / "s.json"
    for stored, expected in ((999, 23), (28, 23), (17, 16), (14, 13), (21, 19), (1, 13)):
        p.write_text('{"font_px": %d}' % stored, encoding="utf-8")
        assert settings.load(str(p))["font_px"] == expected


def test_clamp_font():
    assert settings.clamp_font(5) == settings.MIN_FONT_PX
    assert settings.clamp_font(500) == settings.MAX_FONT_PX
    assert settings.clamp_font("abc") == settings.DEFAULT_FONT_PX
    assert settings.clamp_font(None) == settings.DEFAULT_FONT_PX
    assert settings.clamp_font("19") == 19


def test_save_creates_missing_folder(tmp_path):
    p = tmp_path / "new" / "s.json"
    settings.save({"font_px": 19}, str(p))
    assert p.exists()
