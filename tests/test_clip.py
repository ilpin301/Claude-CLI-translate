from cct import clip


class Clock:
    """Fake monotonic clock: sleep() advances it."""
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run(seqs, owner="windowsterminal.exe", text="hello", fg="windowsterminal.exe", deadline=1.0, current=lambda: True):
    """seqs: the sequence number returned at each poll (the last one repeats)."""
    clock = Clock()
    polls = iter(seqs)
    last = [seqs[0]]

    def read_seq():
        last[0] = next(polls, last[0])
        return last[0]

    return clip.wait_for_copy(10, read_seq, lambda: owner, fg, lambda: text, deadline, current,
                              sleep=clock.sleep, now=clock.now)


def test_copy_after_drag_is_accepted():
    assert run([10, 10, 11]) == ("ok", "windowsterminal.exe", "hello")


def test_no_change_times_out():
    assert run([10])[0] == "none"


def test_foreign_owner_is_rejected():
    status, owner, text = run([11], owner="chrome.exe")
    assert (status, text) == ("none", "") and owner == "chrome.exe"


def test_foreign_copy_then_terminal_copy_is_accepted():
    clock = Clock()
    owners = iter(["chrome.exe", "windowsterminal.exe"])
    seqs = iter([11, 11, 12])
    last = [10]

    def read_seq():
        last[0] = next(seqs, last[0])
        return last[0]

    res = clip.wait_for_copy(10, read_seq, lambda: next(owners), "windowsterminal.exe", lambda: "ok text", 1.0,
                             lambda: True, sleep=clock.sleep, now=clock.now)
    assert res == ("ok", "windowsterminal.exe", "ok text")


def test_unknown_owner_is_accepted():
    assert run([11], owner="")[0] == "ok"


def test_owner_is_foreground_exe():
    assert run([11], owner="myterm.exe", fg="myterm.exe")[0] == "ok"


def test_empty_or_blank_text_is_skipped():
    assert run([11], text="")[0] == "none"
    assert run([11], text="  \n ")[0] == "none"


def test_superseded_request_stops_waiting():
    assert run([10], current=lambda: False)[0] == "superseded"
