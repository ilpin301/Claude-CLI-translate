from cct.geometry import clamp_rect, point_in_rect

WORK = (0, 0, 1920, 1040)


def test_inside_is_unchanged():
    assert clamp_rect(100, 200, 24, 24, WORK) == (100, 200)


def test_clamped_at_right_and_bottom():
    assert clamp_rect(1915, 1035, 24, 24, WORK) == (1896, 1016)


def test_clamped_at_left_and_top():
    assert clamp_rect(-30, -5, 24, 24, WORK) == (0, 0)


def test_second_monitor_offset_work_area():
    work = (1920, 0, 3840, 1040)
    assert clamp_rect(3835, 10, 24, 24, work) == (3816, 10)


def test_rect_larger_than_work_area_pins_to_top_left():
    assert clamp_rect(50, 50, 5000, 5000, WORK) == (0, 0)


def test_point_in_rect_edges():
    rect = (10, 10, 20, 20)
    assert point_in_rect(10, 10, rect)
    assert point_in_rect(19, 19, rect)
    assert not point_in_rect(20, 19, rect)
    assert not point_in_rect(9, 15, rect)
