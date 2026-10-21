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
    assert a == settings.DEFAULTS | {"allowlist": ["windowsterminal.exe"],
                                     "allowlist_classes": ["consolewindowclass"]}
    a["allowlist"].append("x.exe")
    assert b["allowlist"] == ["windowsterminal.exe"]


def test_full_roundtrip(tmp_path):
    p = str(tmp_path / "s.json")
    custom = {"font_px": 19, "target_lang": "de", "scope": "all", "enabled": False,
              "proxy_mode": "system", "allowlist": ["wt.exe", "code.exe"],
              "allowlist_classes": ["consolewindowclass", "myclass"], "first_run_done": True,
              "writer_src": "de", "writer_dst": "fr", "writer_font_in": 13, "writer_font_out": 23,
              "claude_icon": False, "claude_model": "claude-opus-5-5", "claude_api_key": "sk-ant-test"}
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


def test_window_allowed_scope_and_enabled():
    s = settings.normalize({"allowlist": ["windowsterminal.exe", "code.exe"]})
    assert settings.window_allowed("code.exe", "", s)
    assert not settings.window_allowed("notepad.exe", "", s)
    assert not settings.window_allowed("", "", s)
    s["scope"] = "all"
    assert settings.window_allowed("notepad.exe", "", s)
    assert not settings.window_allowed("", "", s)
    s["enabled"] = False
    assert not settings.window_allowed("code.exe", "", s)


def test_classic_console_matches_by_window_class_not_exe():
    s = settings.normalize(None)
    for shell in ("cmd.exe", "powershell.exe", "python.exe"):
        assert settings.window_allowed(shell, "consolewindowclass", s)
    assert not settings.window_allowed("notepad.exe", "notepad", s)
    assert settings.window_allowed("windowsterminal.exe", "cascadia_hosting_window_class", s)
    assert not settings.window_allowed("", "", s)


def test_class_allowlist_cleaning():
    assert settings.clean_classes([" ConsoleWindowClass ", "x", "X", 5, ""]) == ["consolewindowclass", "x"]
    assert settings.clean_classes([]) == []  # explicit empty list switches class matching off
    assert settings.clean_classes("x") == ["consolewindowclass"]


def test_writer_defaults_and_validation():
    d = settings.normalize(None)
    assert (d["writer_src"], d["writer_dst"], d["writer_font_in"], d["writer_font_out"]) == ("auto", "en", 16, 16)
    s = settings.normalize({"writer_src": "DE", "writer_dst": "zz", "writer_font_in": 20, "writer_font_out": "x"})
    assert (s["writer_src"], s["writer_dst"], s["writer_font_in"], s["writer_font_out"]) == ("de", "en", 19, 16)
    assert settings.normalize({"writer_src": "AUTO"})["writer_src"] == "auto"
    assert settings.normalize({"writer_src": "klingon"})["writer_src"] == "auto"
    assert settings.normalize({"writer_src": 5})["writer_src"] == "auto"


def test_claude_settings_defaults_and_validation():
    d = settings.normalize(None)
    assert d["claude_icon"] is True and d["claude_api_key"] == ""
    assert d["claude_model"] == settings.DEFAULT_CLAUDE_MODEL
    out = settings.normalize({"claude_model": "claude-sonnet-5-5", "claude_icon": False,
                              "claude_api_key": "  sk-ant-x  "})
    assert (out["claude_model"], out["claude_icon"], out["claude_api_key"]) == ("claude-sonnet-5-5", False, "sk-ant-x")
    bad = settings.normalize({"claude_model": "gpt-4", "claude_icon": "yes", "claude_api_key": 5})
    assert bad["claude_model"] == settings.DEFAULT_CLAUDE_MODEL and bad["claude_icon"] is True
    assert bad["claude_api_key"] == ""
    assert len(settings.normalize({"claude_api_key": "k" * 1000})["claude_api_key"]) == settings.MAX_KEY_CHARS
