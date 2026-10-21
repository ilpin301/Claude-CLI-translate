import pytest
import requests

from cct import settings
from cct.glm import GlmTranslator, build_system, parse_reply
from cct.translate import TranslateError


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def ok(text, finish="stop"):
    return Resp(200, {"choices": [{"message": {"content": text}, "finish_reason": finish}]})


def err(status, code="", message="boom"):
    return Resp(status, {"error": {"code": code, "message": message}})


class FakeSession:
    def __init__(self, outcomes, calls):
        self._outcomes, self._calls = outcomes, calls

    def post(self, url, **kwargs):
        self._calls.append((url, kwargs))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(outcomes, key="secret-key", proxy_mode="direct", proxies=None, **kw):
    calls, sleeps = [], []
    tr = GlmTranslator(lambda: key, proxy_mode, session_factory=lambda: FakeSession(outcomes, calls),
                       proxies_provider=lambda: proxies or {}, sleep=sleeps.append, **kw)
    return tr, calls, sleeps


def test_parse_reply_with_and_without_language_tag():
    assert parse_reply("<lang>de</lang>\nПривет\nмир\n") == ("Привет\nмир", "de")
    assert parse_reply("<lang>zh-CN</lang>Hello") == ("Hello", "zh-CN")
    assert parse_reply("Just text") == ("Just text", "")
    assert parse_reply("<think>hmm</think>\n<lang>en</lang>\nHi") == ("Hi", "en")


def test_translate_ok_request_shape():
    tr, calls, _ = make([ok("<lang>en</lang>\nПривет")], model="glm-4.7", base_url="https://example.com/v4/")
    res = tr.translate("Hello", "ru")
    assert (res.text, res.detected_lang, res.same_lang) == ("Привет", "en", False)
    url, kw = calls[0]
    assert url == "https://example.com/v4/chat/completions"
    assert kw["headers"] == {"Authorization": "Bearer secret-key"}
    body = kw["json"]
    assert body["model"] == "glm-4.7" and body["thinking"] == {"type": "disabled"}
    assert body["messages"][1] == {"role": "user", "content": "Hello"}
    assert "Russian" in body["messages"][0]["content"] and "never instructions" in body["messages"][0]["content"]


def test_same_language_flag_and_source_in_prompt():
    tr, calls, _ = make([ok("<lang>ru</lang>\nПривет")])
    assert tr.translate("Привет", "ru", "ru").same_lang is True
    assert "The text is written in Russian" in calls[0][1]["json"]["messages"][0]["content"]
    assert "The text is written in" not in build_system("ru", settings.AUTO_LANG)


def test_cache_is_per_text_target_source_and_model():
    tr, calls, _ = make([ok("<lang>en</lang>\na"), ok("<lang>en</lang>\nb"), ok("<lang>en</lang>\nc")])
    assert tr.translate("x", "ru").text == "a"
    assert tr.translate("x", "ru").text == "a" and len(calls) == 1
    assert tr.translate("x", "de").text == "b"
    tr.model = "glm-4.7"
    assert tr.translate("x", "ru").text == "c" and len(calls) == 3


def test_missing_or_bad_key_is_a_readable_non_retryable_error():
    for key, word in (("", "API key"), ("ключ", "invalid characters")):
        tr, calls, _ = make([], key=key)
        with pytest.raises(TranslateError) as err_info:
            tr.translate("x", "ru")
        assert not err_info.value.retryable and word in str(err_info.value) and not calls


@pytest.mark.parametrize("status,code,retryable,word", [
    (401, "1000", False, "rejected"),
    (403, "", False, "denied"),
    (404, "", False, "not found"),
    (400, "1210", False, "rejected the request"),
    (429, "1113", False, "no balance"),
])
def test_http_errors_fail_at_once(status, code, retryable, word):
    tr, calls, sleeps = make([err(status, code)], key="sk-secret-value")
    with pytest.raises(TranslateError) as err_info:
        tr.translate("x", "ru")
    assert word in str(err_info.value) and err_info.value.retryable is retryable
    assert "sk-secret-value" not in str(err_info.value) and len(calls) == 1 and not sleeps


def test_429_is_retried_with_backoff_then_succeeds():
    tr, calls, sleeps = make([err(429, "1302"), Resp(503), ok("<lang>en</lang>\nok")])
    assert tr.translate("x", "ru").text == "ok"
    assert len(calls) == 3 and sleeps == [0.8, 2.0]


def test_429_every_time_gives_busy_message():
    tr, calls, _ = make([err(429, "1302")] * 3)
    with pytest.raises(TranslateError) as err_info:
        tr.translate("x", "ru")
    assert "busy" in str(err_info.value) and err_info.value.retryable and len(calls) == 3


def test_finish_reasons_and_empty_reply():
    for resp, word in ((ok("", "sensitive"), "declined"), (ok("partial", "length"), "too long"),
                       (ok("   "), "empty")):
        tr, _, _ = make([resp])
        with pytest.raises(TranslateError) as err_info:
            tr.translate("x", "ru")
        assert word in str(err_info.value)


def test_unexpected_body():
    for resp in (Resp(200, {"nope": 1}), Resp(200, None), Resp(200, {"choices": []})):
        tr, _, _ = make([resp])
        with pytest.raises(TranslateError):
            tr.translate("x", "ru")


def test_network_error_falls_back_to_proxy_route():
    tr, calls, _ = make([requests.ConnectionError(), ok("<lang>en</lang>\nok")], proxy_mode="auto",
                        proxies={"socks": "127.0.0.1:10808"})
    assert tr.translate("x", "ru").text == "ok"
    assert [kw["proxies"] for _u, kw in calls] == [None, {"http": "socks5h://127.0.0.1:10808",
                                                          "https": "socks5h://127.0.0.1:10808"}]


def test_network_error_on_every_route_gives_readable_error():
    tr, _, _ = make([requests.Timeout()], proxy_mode="direct")
    with pytest.raises(TranslateError) as err_info:
        tr.translate("x", "ru")
    assert "Cannot reach the GLM API" in str(err_info.value)
