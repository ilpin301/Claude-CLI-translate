import pytest
import requests

from cct import translate
from cct.translate import (GoogleTranslator, TranslateError, parse_response, parse_system_proxy,
                           plan_attempts, same_language)

SOCKS = {"socks": "127.0.0.1:10808"}
PROXY = "socks5h://127.0.0.1:10808"


def test_parse_response_normal_and_multi_segment():
    assert parse_response([[["Privet", "Hello", None, None, 1]], None, "en"]) == ("Privet", "en")
    data = [[["Pervoe. ", "First. "], ["Vtoroe", "Second"]], None, "de", None]
    assert parse_response(data) == ("Pervoe. Vtoroe", "de")


def test_parse_response_skips_null_segments():
    data = [[["a", "x"], None, [None, None], ["b", "y"]], None, "fr"]
    assert parse_response(data) == ("ab", "fr")


@pytest.mark.parametrize("bad", [None, {}, [], [[]], [[["a"]], None], [[["a"]], None, 5],
                                 [[None], None, "en"], [[[1]], None, "en"], "x"])
def test_parse_response_malformed(bad):
    with pytest.raises(TranslateError):
        parse_response(bad)


def test_same_language():
    assert same_language("RU", "ru")
    assert same_language("zh-CN", "zh")
    assert not same_language("en", "ru")
    assert not same_language("", "ru")


@pytest.mark.parametrize("proxies, expected", [
    ({"socks": "127.0.0.1:10808"}, PROXY),
    ({"socks": "socks://127.0.0.1:10808"}, PROXY),
    ({"socks": "socks=127.0.0.1:10808"}, PROXY),
    ({"all": "socks5://127.0.0.1:10808/"}, PROXY),
    ({"https": "socks5h://127.0.0.1:10808"}, PROXY),
    ({"http": "http://proxy:8080"}, None),
    ({"http": "127.0.0.1:8080"}, None),
    ({}, None),
])
def test_parse_system_proxy(proxies, expected):
    assert parse_system_proxy(proxies) == expected


def test_plan_attempts():
    assert plan_attempts("direct", SOCKS) == [None]
    assert plan_attempts("system", SOCKS) == [PROXY]
    assert plan_attempts("auto", SOCKS) == [None, PROXY]
    assert plan_attempts("auto", {}) == [None]
    with pytest.raises(TranslateError):
        plan_attempts("system", {})
    with pytest.raises(TranslateError):
        plan_attempts("bogus", SOCKS)


class FakeResp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload if payload is not None else [[["Privet", "Hello"]], None, "en"]

    def json(self):
        return self._payload


class FakeSession:
    """Each script item is an exception (raised) or a FakeResp (returned)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, url, params=None, data=None, timeout=None, proxies=None):
        self.calls.append({"method": method, "url": url, "params": params, "data": data, "proxies": proxies})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


sleeps = []


def make(script, mode="auto", proxies=SOCKS, cache_size=100):
    session = FakeSession(script)
    tr = GoogleTranslator(mode, cache_size=cache_size, session_factory=lambda: session,
                          proxies_provider=lambda: proxies, sleep=sleeps.append)
    return tr, session


def test_success_direct_get():
    tr, s = make([FakeResp()])
    res = tr.translate("Hello", "ru")
    assert (res.text, res.detected_lang, res.same_lang) == ("Privet", "en", False)
    assert s.calls[0]["method"] == "GET" and s.calls[0]["proxies"] is None
    assert s.calls[0]["params"]["q"] == "Hello" and s.calls[0]["params"]["tl"] == "ru"


def test_long_text_uses_post():
    tr, s = make([FakeResp()])
    tr.translate("x" * 1501, "ru")
    assert s.calls[0]["method"] == "POST" and s.calls[0]["data"] == {"q": "x" * 1501}
    assert "q" not in s.calls[0]["params"]


def test_same_lang_flag():
    tr, _ = make([FakeResp(payload=[[["Privet", "Privet"]], None, "ru"])])
    assert tr.translate("Privet", "ru").same_lang


@pytest.mark.parametrize("exc", [requests.ConnectionError("x"), requests.ConnectTimeout("x"),
                                 requests.ReadTimeout("x")])
def test_auto_falls_back_to_proxy_once(exc):
    tr, s = make([exc, FakeResp()])
    assert tr.translate("Hello", "ru").text == "Privet"
    assert [c["proxies"] for c in s.calls] == [None, {"http": PROXY, "https": PROXY}]


def test_auto_both_fail_is_one_retry_only():
    tr, s = make([requests.ConnectionError("a"), requests.ConnectionError("b"), FakeResp()])
    with pytest.raises(TranslateError):
        tr.translate("Hello", "ru")
    assert len(s.calls) == 2


def test_auto_without_system_proxy_has_no_retry():
    tr, s = make([requests.ConnectionError("a"), FakeResp()], proxies={})
    with pytest.raises(TranslateError):
        tr.translate("Hello", "ru")
    assert len(s.calls) == 1


@pytest.fixture(autouse=True)
def _clear_sleeps():
    sleeps.clear()


def test_first_request_goes_to_clients5():
    tr, s = make([FakeResp()])
    tr.translate("Hello", "ru")
    assert s.calls[0]["url"].startswith("https://clients5.google.com/")
    assert s.calls[0]["params"]["client"] == "dict-chrome-ex" and s.calls[0]["params"]["tl"] == "ru"


def test_429_then_ok_falls_back_to_the_gtx_endpoint_on_the_same_route():
    tr, s = make([FakeResp(status=429), FakeResp()])
    assert tr.translate("Hello", "ru").text == "Privet"
    assert [c["url"].split("/")[2] for c in s.calls] == ["clients5.google.com", "translate.googleapis.com"]
    assert [c["proxies"] for c in s.calls] == [None, None]
    assert sleeps == [translate.BACKOFF_S[0]]


def test_429_on_every_endpoint_moves_to_the_other_route():
    tr, s = make([FakeResp(status=429), FakeResp(status=429), FakeResp()])
    assert tr.translate("Hello", "ru").text == "Privet"
    assert [c["proxies"] for c in s.calls] == [None, None, {"http": PROXY, "https": PROXY}]
    assert s.calls[2]["url"].startswith("https://clients5.google.com/")


def test_parse_response_clients5_layout():
    assert parse_response([["Привет, мир", "en"]]) == ("Привет, мир", "en")
    assert parse_response([["a\nb\n\nc", "ru"]]) == ("a\nb\n\nc", "ru")
    assert parse_response([["x"]]) == ("x", "")
    assert parse_response([["a", "en"], ["b", "en"]]) == ("ab", "en")


def test_429_without_proxy_retries_same_route_with_backoff():
    tr, s = make([FakeResp(status=429), FakeResp(status=429), FakeResp()], proxies={})
    assert tr.translate("Hello", "ru").text == "Privet"
    assert len(s.calls) == 3 and all(c["proxies"] is None for c in s.calls)
    assert sleeps == list(translate.BACKOFF_S)


def test_429_every_time_gives_up_after_max_tries_with_retryable_error():
    tr, s = make([FakeResp(status=429)] * 5)
    with pytest.raises(TranslateError, match="rate-limiting") as info:
        tr.translate("Hello", "ru")
    assert len(s.calls) == translate.MAX_TRIES and info.value.retryable
    assert len(sleeps) == translate.MAX_TRIES - 1


def test_5xx_retries_on_the_same_route():
    tr, s = make([FakeResp(status=503), FakeResp()])
    assert tr.translate("Hello", "ru").text == "Privet"
    assert [c["proxies"] for c in s.calls] == [None, None]


def test_retry_after_header_is_honoured_and_capped():
    tr, _ = make([FakeResp(status=429, headers={"Retry-After": "3"}), FakeResp()])
    tr.translate("Hello", "ru")
    assert sleeps == [3.0]
    assert translate.retry_delay(1, "999") == translate.RETRY_AFTER_CAP_S
    assert translate.retry_delay(1, "soon") == translate.BACKOFF_S[0]
    assert translate.retry_delay(2, None) == translate.BACKOFF_S[1]
    assert translate.retry_delay(9, None) == translate.BACKOFF_S[-1]


def test_other_http_errors_do_not_retry_and_are_not_retryable():
    tr, s = make([FakeResp(status=403), FakeResp()])
    with pytest.raises(TranslateError, match="403") as info:
        tr.translate("Hello", "ru")
    assert len(s.calls) == 1 and not info.value.retryable and sleeps == []


def test_429_then_network_errors_on_both_routes_raises():
    tr, s = make([FakeResp(status=429), requests.ConnectionError("a"), FakeResp(status=429)])
    with pytest.raises(TranslateError):
        tr.translate("Hello", "ru")
    assert len(s.calls) == 3


def test_config_errors_are_not_retryable():
    tr, _ = make([FakeResp()], mode="system", proxies={})
    with pytest.raises(TranslateError) as info:
        tr.translate("Hello", "ru")
    assert not info.value.retryable


def test_parse_error_does_not_fall_back():
    tr, s = make([FakeResp(payload=[]), FakeResp()])
    with pytest.raises(TranslateError):
        tr.translate("Hello", "ru")
    assert len(s.calls) == 1


def test_direct_mode_never_uses_proxy():
    tr, s = make([requests.ConnectionError("a"), FakeResp()], mode="direct")
    with pytest.raises(TranslateError):
        tr.translate("Hello", "ru")
    assert len(s.calls) == 1 and s.calls[0]["proxies"] is None


def test_system_mode_uses_proxy_only():
    tr, s = make([FakeResp()], mode="system")
    tr.translate("Hello", "ru")
    assert s.calls[0]["proxies"] == {"http": PROXY, "https": PROXY}


def test_cache_hit_avoids_second_call():
    tr, s = make([FakeResp()])
    first = tr.translate("Hello", "ru")
    assert tr.translate("Hello", "ru") is first
    assert len(s.calls) == 1


def test_cache_keyed_by_target_and_evicts_lru():
    tr, s = make([FakeResp() for _ in range(5)], cache_size=2)
    tr.translate("a", "ru")
    tr.translate("b", "ru")
    tr.translate("a", "ru")  # refresh a; b is now the oldest
    tr.translate("c", "ru")  # evicts b
    assert len(s.calls) == 3
    tr.translate("a", "ru")  # still cached
    assert len(s.calls) == 3
    tr.translate("b", "ru")  # was evicted
    assert len(s.calls) == 4
    tr.translate("a", "en")  # different target
    assert len(s.calls) == 5


def test_module_exports_no_qt():
    assert not hasattr(translate, "QObject")


def test_session_sends_browser_user_agent():
    session = GoogleTranslator._new_session()
    assert "python-requests" not in session.headers["User-Agent"]
    assert session.headers["User-Agent"] == translate.USER_AGENT
    assert session.trust_env is False


def test_source_language_is_sent_and_cached_separately():
    tr, s = make([FakeResp(), FakeResp()])
    tr.translate("Hello", "ru")
    tr.translate("Hello", "ru", "en")
    assert s.calls[0]["params"]["sl"] == "auto"
    assert s.calls[1]["params"]["sl"] == "en"
    tr.translate("Hello", "ru", "en")  # cached: no third call
    assert len(s.calls) == 2
