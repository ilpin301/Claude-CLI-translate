"""Translation backend: Translator interface + unofficial Google gtx endpoint (no key).

Raw text is never logged: only length, a short sha1 prefix, latency and status.
"""
import hashlib
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

from . import config

log = logging.getLogger("cct.translate")

# (name, url, fixed params). Tried in this order; a 429 moves on to the next one. clients5/dict-chrome-ex
# (the Chrome dictionary extension endpoint) answered 200 where the gtx endpoint returned 429 for the
# same IP (measured with tools/probe_translate.py), so it is first.
ENDPOINTS = (
    ("clients5", "https://clients5.google.com/translate_a/t", {"client": "dict-chrome-ex", "sl": "auto"}),
    ("gtx", "https://translate.googleapis.com/translate_a/single",
     {"client": "gtx", "sl": "auto", "dt": "t"}),
)
POST_THRESHOLD = 1500
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_TRIES = 3  # total HTTP attempts per translate() call, across routes
BACKOFF_S = (0.8, 2.0)  # sleep before the 2nd and 3rd try when the server sent no Retry-After
RETRY_AFTER_CAP_S = 5.0


class TranslateError(Exception):
    """Readable, user-facing translation failure. retryable: a manual Retry in the popup may help."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class TranslationResult:
    text: str
    detected_lang: str
    same_lang: bool


class Translator(ABC):
    @abstractmethod
    def translate(self, text: str, target: str) -> TranslationResult:
        ...


def same_language(detected: str, target: str) -> bool:
    """Compare primary subtags, case-insensitive ('zh-CN' == 'zh')."""
    if not detected or not target:
        return False
    return detected.lower().split("-")[0] == target.lower().split("-")[0]


def parse_response(data) -> tuple:
    """Response JSON -> (translated_text, detected_lang).

    Two layouts: clients5 `[["translation", "xx"]]` and gtx `[[[seg, orig, ...], ...], None, "xx", ...]`.
    """
    try:
        if isinstance(data, list) and data and isinstance(data[0], list) and data[0] \
                and isinstance(data[0][0], str):
            rows = [row for row in data if isinstance(row, list) and row and isinstance(row[0], str)]
            detected = rows[0][1] if len(rows[0]) > 1 and isinstance(rows[0][1], str) else ""
            return "".join(row[0] for row in rows), detected
        items, detected = data[0], data[2]
        if not isinstance(items, list) or not isinstance(detected, str):
            raise TypeError("unexpected layout")
        segs = [it[0] for it in items if it and it[0] is not None]
        if not segs or not all(isinstance(s, str) for s in segs):
            raise TypeError("no text segments")
    except (TypeError, IndexError, KeyError) as exc:
        raise TranslateError("Unexpected response from the translation service.") from exc
    return "".join(segs), detected


def parse_system_proxy(proxies: Dict[str, str]) -> Optional[str]:
    """Pick a SOCKS proxy out of urllib.request.getproxies() output.

    Accepts {'socks': '127.0.0.1:10808'}, {'socks': 'socks://h:p'}, 'socks5://h:p' and 'socks=h:p'
    values. Returns 'socks5h://host:port' or None. socks5h (not socks5) makes the proxy resolve DNS,
    so name resolution of translate.googleapis.com also goes through the tunnel (local DNS may be
    blocked or poisoned, which is the reason the user runs a proxy at all).
    """
    for key in ("socks", "socks5", "socks4", "all", "https", "http"):
        value = (proxies.get(key) or "").strip()
        if not value:
            continue
        if "=" in value and "://" not in value:
            value = value.split("=", 1)[1]
        if "://" in value:
            scheme, value = value.split("://", 1)
            if not scheme.lower().startswith("socks"):
                continue
        elif not key.startswith("socks"):
            continue
        value = value.strip("/")
        if value:
            return "socks5h://" + value
    return None


def plan_attempts(proxy_mode: str, system_proxies: Dict[str, str]) -> List[Optional[str]]:
    """Ordered proxy configs to try; None means a direct connection."""
    proxy = parse_system_proxy(system_proxies)
    if proxy_mode == "direct":
        return [None]
    if proxy_mode == "system":
        if proxy is None:
            raise TranslateError("proxy_mode is 'system' but no system SOCKS proxy is configured.", retryable=False)
        return [proxy]
    if proxy_mode == "auto":
        return [None, proxy] if proxy else [None]
    raise TranslateError("Unknown proxy_mode %r." % proxy_mode, retryable=False)


def retry_delay(try_no: int, retry_after) -> float:
    """Seconds to wait before try number try_no + 1 (try_no is 1-based). Honours a numeric Retry-After header."""
    try:
        wanted = float(retry_after)
    except (TypeError, ValueError):
        wanted = None
    if wanted is not None and wanted >= 0:
        return min(wanted, RETRY_AFTER_CAP_S)
    return BACKOFF_S[min(try_no, len(BACKOFF_S)) - 1]


def _fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


class GoogleTranslator(Translator):
    def __init__(self, proxy_mode: str = "auto", cache_size: int = config.CACHE_SIZE,
                 session_factory=None, proxies_provider=None, sleep=time.sleep):
        self._sleep = sleep
        self.proxy_mode = proxy_mode
        self.cache_size = cache_size
        self._session_factory = session_factory or self._new_session
        self._proxies_provider = proxies_provider or _system_proxies
        self._cache: "OrderedDict[tuple, TranslationResult]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _new_session():
        session = requests.Session()
        session.trust_env = False  # proxy choice is explicit, never from env vars
        session.headers["User-Agent"] = USER_AGENT  # the default python-requests UA is throttled more readily
        return session

    def _cache_get(self, key):
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
            return hit

    def _cache_put(self, key, value) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    def _request(self, session, text: str, target: str, proxy: Optional[str], endpoint=ENDPOINTS[0]):
        _name, url, fixed = endpoint
        params = dict(fixed, tl=target)
        proxies = {"http": proxy, "https": proxy} if proxy else None
        timeout = (config.CONNECT_TIMEOUT_S, config.READ_TIMEOUT_S)
        if len(text) > POST_THRESHOLD:
            return session.request("POST", url, params=params, data={"q": text},
                                   timeout=timeout, proxies=proxies)
        params["q"] = text
        return session.request("GET", url, params=params, timeout=timeout, proxies=proxies)

    def translate(self, text: str, target: str) -> TranslationResult:
        key = (text, target)
        tag = "len=%d sha1=%s" % (len(text), _fingerprint(text))
        cached = self._cache_get(key)
        if cached is not None:
            log.info("translate cache hit %s", tag)
            return cached
        routes = plan_attempts(self.proxy_mode, self._proxies_provider())
        session = self._session_factory()
        started = time.monotonic()
        route = 0
        ep = 0
        net_failures = 0
        resp = None
        for try_no in range(1, MAX_TRIES + 1):
            proxy = routes[route]
            via = "proxy" if proxy else "direct"
            ep_name = ENDPOINTS[ep][0]
            try:
                resp = self._request(session, text, target, proxy, ENDPOINTS[ep])
            except (requests.ConnectionError, requests.Timeout) as exc:
                net_failures += 1
                log.warning("translate %s try=%d via=%s ep=%s network error %s", tag, try_no, via, ep_name, type(exc).__name__)
                if net_failures >= len(routes):  # every route failed once: give up
                    raise TranslateError(
                        "Cannot reach the translation service (%s). Check the connection or proxy."
                        % type(exc).__name__) from exc
                route = (route + 1) % len(routes)
                continue
            except requests.RequestException as exc:
                log.warning("translate %s try=%d via=%s ep=%s request error %s", tag, try_no, via, ep_name, type(exc).__name__)
                raise TranslateError("Translation request failed (%s)." % type(exc).__name__) from exc
            if resp.status_code == 200:
                break
            log.warning("translate %s try=%d via=%s ep=%s http=%s", tag, try_no, via, ep_name, resp.status_code)
            if resp.status_code not in RETRY_STATUSES:
                raise TranslateError("Translation service returned HTTP %s." % resp.status_code,
                                     retryable=False)
            if try_no == MAX_TRIES:
                if resp.status_code == 429:
                    raise TranslateError("The translation service is rate-limiting requests (HTTP 429). "
                                         "Try again in a moment.")
                raise TranslateError("Translation service returned HTTP %s." % resp.status_code)
            headers = getattr(resp, "headers", None) or {}
            self._sleep(retry_delay(try_no, headers.get("Retry-After")))
            if resp.status_code == 429:  # try the other endpoint; once all were tried, the other route
                ep = (ep + 1) % len(ENDPOINTS)
                if ep == 0:
                    route = (route + 1) % len(routes)
        else:  # only reachable when the last try was a network error that did not raise
            raise TranslateError("Cannot reach the translation service. Check the connection or proxy.")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise TranslateError("Translation service returned invalid data.") from exc
        translated, detected = parse_response(payload)
        result = TranslationResult(translated, detected, same_language(detected, target))
        log.info("translate ok %s tries=%d via=%s ep=%s ms=%d detected=%s", tag, try_no, via, ep_name,
                 (time.monotonic() - started) * 1000, detected)
        self._cache_put(key, result)
        return result


def _system_proxies() -> Dict[str, str]:
    import urllib.request
    return urllib.request.getproxies()
