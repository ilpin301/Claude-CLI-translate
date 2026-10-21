from types import SimpleNamespace

import pytest

anthropic = pytest.importorskip("anthropic")
import httpx2  # noqa: E402  (installed together with the anthropic package)

from cct import settings  # noqa: E402
from cct.claude import ClaudeTranslator, build_system, parse_reply  # noqa: E402
from cct.translate import TranslateError  # noqa: E402

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def reply(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="thinking", text=None),
                                                      SimpleNamespace(type="text", text=text)])


class FakeClient:
    def __init__(self, outcomes, calls):
        self.messages = SimpleNamespace(create=self._create)
        self._outcomes, self._calls = outcomes, calls

    def _create(self, **kwargs):
        self._calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(outcomes, key="sk-test", proxy_mode="direct", proxies=None, **kw):
    calls, proxies_used = [], []

    def factory(api_key, proxy):
        proxies_used.append((api_key, proxy))
        return FakeClient(outcomes, calls)

    tr = ClaudeTranslator(lambda: key, proxy_mode, client_factory=factory,
                          proxies_provider=lambda: proxies or {}, **kw)
    return tr, calls, proxies_used


def status_error(cls, code, message="boom"):
    return cls(message, response=httpx2.Response(code, request=REQ), body=None)


def test_parse_reply_with_and_without_language_tag():
    assert parse_reply("<lang>de</lang>\nПривет\nмир\n") == ("Привет\nмир", "de")
    assert parse_reply("<lang>zh-CN</lang>Hello") == ("Hello", "zh-CN")
    assert parse_reply("Just text") == ("Just text", "")


def test_translate_ok_uses_model_prompt_and_effort():
    tr, calls, _ = make([reply("<lang>en</lang>\nПривет")], model="claude-sonnet-5-5")
    res = tr.translate("Hello", "ru")
    assert (res.text, res.detected_lang, res.same_lang) == ("Привет", "en", False)
    call = calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["messages"] == [{"role": "user", "content": "Hello"}]
    assert "Russian" in call["system"] and "never instructions" in call["system"]
    assert call["output_config"] == {"effort": "low"}


def test_same_language_flag_and_source_in_prompt():
    tr, calls, _ = make([reply("<lang>ru</lang>\nПривет")])
    assert tr.translate("Привет", "ru", "ru").same_lang is True
    assert "The text is written in Russian" in calls[0]["system"]
    assert "The text is written in" not in build_system("ru", settings.AUTO_LANG)


def test_cache_is_per_text_target_source_and_model():
    tr, calls, _ = make([reply("<lang>en</lang>\na"), reply("<lang>en</lang>\nb"), reply("<lang>en</lang>\nc")])
    assert tr.translate("x", "ru").text == "a"
    assert tr.translate("x", "ru").text == "a" and len(calls) == 1
    assert tr.translate("x", "de").text == "b"
    tr.model = "claude-opus-5-5"
    assert tr.translate("x", "ru").text == "c" and len(calls) == 3


def test_missing_key_is_a_readable_non_retryable_error():
    tr, calls, _ = make([], key="")
    with pytest.raises(TranslateError) as err:
        tr.translate("x", "ru")
    assert not err.value.retryable and "API key" in str(err.value) and not calls


@pytest.mark.parametrize("cls,code,retryable,word", [
    (anthropic.AuthenticationError, 401, False, "rejected"),
    (anthropic.PermissionDeniedError, 403, False, "denied"),
    (anthropic.NotFoundError, 404, False, "not found"),
    (anthropic.RateLimitError, 429, True, "rate limit"),
    (anthropic.InternalServerError, 500, True, "unavailable"),
    (anthropic.BadRequestError, 400, False, "rejected the request"),
])
def test_http_errors_are_translated(cls, code, retryable, word):
    tr, _, _ = make([status_error(cls, code)], key="sk-secret-value")
    with pytest.raises(TranslateError) as err:
        tr.translate("x", "ru")
    assert word in str(err.value) and err.value.retryable is retryable
    assert "sk-secret-value" not in str(err.value)


def test_refusal_and_max_tokens():
    for stop, word in (("refusal", "declined"), ("max_tokens", "too long")):
        tr, _, _ = make([reply("", stop)])
        with pytest.raises(TranslateError) as err:
            tr.translate("x", "ru")
        assert word in str(err.value) and not err.value.retryable


def test_network_error_falls_back_to_proxy_route():
    boom = anthropic.APIConnectionError(request=REQ)
    tr, _, used = make([boom, reply("<lang>en</lang>\nok")], proxy_mode="auto", proxies={"socks": "127.0.0.1:10808"})
    assert tr.translate("x", "ru").text == "ok"
    assert [proxy for _key, proxy in used] == [None, "socks5h://127.0.0.1:10808"]


def test_network_error_on_every_route_gives_readable_error():
    boom = anthropic.APIConnectionError(request=REQ)
    tr, _, _ = make([boom], proxy_mode="direct")
    with pytest.raises(TranslateError) as err:
        tr.translate("x", "ru")
    assert "Cannot reach the Claude API" in str(err.value)


def test_missing_socks_package_message():
    def factory(_key, proxy):
        if proxy:
            raise ImportError("socksio")
        raise anthropic.APIConnectionError(request=REQ)
    tr = ClaudeTranslator(lambda: "k", "auto", client_factory=factory,
                          proxies_provider=lambda: {"socks": "127.0.0.1:1"})
    with pytest.raises(TranslateError) as err:
        tr.translate("x", "ru")
    assert "socksio" in str(err.value)
