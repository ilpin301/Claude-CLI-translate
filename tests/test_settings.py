from cct import settings


def test_defaults_when_missing(tmp_path):
    assert settings.load(str(tmp_path / "s.json")) == settings.normalize(None)


def test_roundtrip_leaves_no_temp_file(tmp_path):
    p = str(tmp_path / "s.json")
    settings.save({"font_px": 23}, p)
    assert settings.load(p)["font_px"] == 23
    assert not [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]


def test_corrupt_file_falls_back(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert settings.load(str(p)) == settings.normalize(None)


def test_wrong_shape_falls_back(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("[1, 2]", encoding="utf-8")
    assert settings.load(str(p)) == settings.normalize(None)


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


def test_defaults_are_complete_and_independent():
    a, b = settings.normalize(None), settings.normalize(None)
    assert a == settings.DEFAULTS | {"allowlist": ["windowsterminal.exe"]}
    a["allowlist"].append("x.exe")
    assert b["allowlist"] == ["windowsterminal.exe"]


def test_full_roundtrip(tmp_path):
    p = str(tmp_path / "s.json")
    custom = {"font_px": 19, "target_lang": "de", "scope": "all", "enabled": False,
              "proxy_mode": "system", "allowlist": ["wt.exe", "code.exe"], "first_run_done": True}
    settings.save(custom, p)
    assert settings.load(p) == custom


def test_invalid_values_fall_back_per_key():
    got = settings.normalize({"target_lang": "xx", "scope": "bogus", "proxy_mode": 5,
                              "enabled": "yes", "first_run_done": 1, "font_px": 16})
    assert got == settings.normalize(None)


def test_language_is_case_insensitive_and_canonical():
    assert settings.valid_lang("ZH-cn") == "zh-CN"
    assert settings.valid_lang("DE") == "de"
    assert settings.valid_lang(None) == "ru"


def test_allowlist_cleaning():
    assert settings.clean_allowlist(["C:\\Apps\\Code.EXE", " wt.exe ", "wt.exe", "", 3]) == ["code.exe", "wt.exe"]
    assert settings.clean_allowlist([]) == ["windowsterminal.exe"]
    assert settings.clean_allowlist("code.exe") == ["windowsterminal.exe"]


def test_exe_allowed_scope_and_enabled():
    s = settings.normalize({"allowlist": ["windowsterminal.exe", "code.exe"]})
    assert settings.exe_allowed("code.exe", s)
    assert not settings.exe_allowed("notepad.exe", s)
    assert not settings.exe_allowed("", s)
    s["scope"] = "all"
    assert settings.exe_allowed("notepad.exe", s)
    assert not settings.exe_allowed("", s)
    s["enabled"] = False
    assert not settings.exe_allowed("code.exe", s)
