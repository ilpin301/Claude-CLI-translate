from cct.gating import WM_LBUTTONDOWN, WM_LBUTTONUP, Gate


def down(x, y, shift=False):
    return (WM_LBUTTONDOWN, x, y, 0, shift)


def up(x, y, shift=False):
    return (WM_LBUTTONUP, x, y, 0, shift)


def test_shift_drag_triggers():
    g = Gate()
    assert g.feed(down(10, 10, True)) is None
    t = g.feed(up(110, 10, True))
    assert t is not None and (t.x, t.y) == (110, 10) and t.drag_px == 100


def test_plain_drag_is_ignored():
    g = Gate()
    g.feed(down(10, 10))
    assert g.feed(up(110, 10)) is None


def test_shift_only_at_button_up_is_accepted():
    g = Gate()
    g.feed(down(10, 10, False))
    assert g.feed(up(110, 10, True)) is not None


def test_shift_only_at_button_down_is_accepted():
    g = Gate()
    g.feed(down(10, 10, True))
    assert g.feed(up(110, 10, False)) is not None


def test_short_drag_is_ignored():
    g = Gate()
    g.feed(down(10, 10, True))
    assert g.feed(up(12, 11, True)) is None


def test_up_without_down_is_ignored():
    assert Gate().feed(up(50, 50, True)) is None


def test_second_up_without_new_down_is_ignored():
    g = Gate()
    g.feed(down(0, 0, True))
    assert g.feed(up(50, 0, True)) is not None
    assert g.feed(up(80, 0, True)) is None


def test_require_shift_false_accepts_plain_drag():
    g = Gate(require_shift=False)
    g.feed(down(0, 0))
    assert g.feed(up(50, 0)) is not None


def test_reset_clears_pending_down():
    g = Gate()
    g.feed(down(0, 0, True))
    g.reset()
    assert g.feed(up(50, 0, True)) is None
