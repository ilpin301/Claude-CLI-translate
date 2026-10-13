from cct.normalize import normalize


def n(text, **kw):
    return normalize(text, **kw)[0]


def test_empty_and_whitespace():
    assert normalize("") == ("", False)
    assert normalize("   \n \r\n\t ") == ("", False)


def test_rstrip_padded_rows_and_trailing_blank_lines():
    padded = "Hello wor" + " " * 100 + "\nld again" + " " * 960 + "\n" + " " * 973 + "\n\n"
    assert normalize(padded) == ("Hello wor ld again", False)


def test_crlf_nul_and_nbsp():
    assert n("one\r\ntwo\x00 three\r\n") == "one two three"


def test_wrapped_lines_joined_and_paragraphs_kept():
    assert n("first line of text\nsecond line\n\n\n\nnew paragraph\nwraps") == \
        "first line of text second line\n\nnew paragraph wraps"


def test_tui_decoration_stripped():
    text = "● Here is the answer\n  that wraps on\n│ > what next │\n⎿  details here"
    assert n(text) == "Here is the answer that wraps on what next details here"


def test_border_only_rows_become_blank():
    text = "╭" + "─" * 20 + "╮\n│ some prose here │\n╰" + "─" * 20 + "╯"
    assert n(text) == "some prose here"


def test_prompt_marker_only_at_line_start_with_space():
    assert n("> quoted\nx >= y") == "quoted x >= y"


def test_code_skip_tab_indent_fence():
    assert n("a\n\tb\nc") == "a\n\tb\nc"
    assert n("def f():\n    return 1  \nx") == "def f():\n    return 1\nx"
    assert n("```py\nx  =  1\n```") == "```py\nx  =  1\n```"


def test_indent_checked_after_decoration_strip():
    # "│ " is stripped, leaving 4 spaces -> code mode
    assert n("│     indented\n│ next") == "    indented\nnext"
    # only 2 leading spaces left -> prose
    assert n("│   two\n│ next") == "two next"


def test_table_skip_keeps_original_rows_with_borders():
    table = ("┌───┬───┐  \n"
             "│ a │ b │   \n"
             "├───┼───┤\n"
             "│ c │ d │\n")
    out = n(table)
    assert out.split("\n") == [
        "┌───┬───┐", "│ a │ b │",
        "├───┼───┤", "│ c │ d │"]


def test_table_without_pure_border_rows():
    assert n("│ a │ b │\n│ c │ d │") == "│ a │ b │\n│ c │ d │"


def test_equal_length_lines_skip_join():
    text = "abcdefghij klmnopqrst\nabcdefghij klmnopqrs\nabcdefghij klmnopqrstu"
    assert n(text) == text


def test_short_or_two_equal_lines_still_join():
    assert n("abcdefghij klmnopqrst\nabcdefghij klmnopqrst") == "abcdefghij klmnopqrst abcdefghij klmnopqrst"
    assert n("aa bb\ncc dd\nee ff") == "aa bb cc dd ee ff"


def test_space_collapse_only_in_prose():
    assert n("a    b\nc   d") == "a b c d"
    assert n("a    b\n\tc   d") == "a    b\n\tc   d"


def test_cap_and_truncated_flag():
    out, truncated = normalize("x" * 6000, max_chars=5000)
    assert len(out) == 5000 and truncated
    assert normalize("x" * 5000, max_chars=5000)[1] is False
