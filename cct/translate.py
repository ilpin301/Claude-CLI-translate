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

ENDPOINT = "https://translate.googleapis.com/translate_a/single"
POST_THRESHOLD = 1500


class TranslateError(Exception):
    """Readable, user-facing translation failure."""


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
    """gtx JSON [[[seg, orig, ...], ...], None, 'xx', ...] -> (translated_text, detected_lang)."""
    try:
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
            raise TranslateError("proxy_mode is 'system' but no system SOCKS proxy is configured.")
        return [proxy]
    if proxy_mode == "auto":
        return [None, proxy] if proxy else [None]
    raise TranslateError("Unknown proxy_mode %r." % proxy_mode)


def _fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


class GoogleTranslator(Translator):
    def __init__(self, proxy_mode: str = "auto", cache_size: int = config.CACHE_SIZE,
                 session_factory=None, proxies_provider=None):
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

    def _request(self, session, text: str, target: str, proxy: Optional[str]):
        params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t"}
        proxies = {"http": proxy, "https": proxy} if proxy else None
        timeout = (config.CONNECT_TIMEOUT_S, config.READ_TIMEOUT_S)
        if len(text) > POST_THRESHOLD:
            return session.request("POST", ENDPOINT, params=params, data={"q": text},
                                   timeout=timeout, proxies=proxies)
        params["q"] = text
        return session.request("GET", ENDPOINT, params=params, timeout=timeout, proxies=proxies)

    def translate(self, text: str, target: str) -> TranslationResult:
        key = (text, target)
        tag = "len=%d sha1=%s" % (len(text), _fingerprint(text))
        cached = self._cache_get(key)
        if cached is not None:
            log.info("translate cache hit %s", tag)
            return cached
        attempts = plan_attempts(self.proxy_mode, self._proxies_provider())
        session = self._session_factory()
        started = time.monotonic()
        resp = None
        for i, proxy in enumerate(attempts):
            via = "proxy" if proxy else "direct"
            try:
                resp = self._request(session, text, target, proxy)
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                log.warning("translate %s via=%s network error %s", tag, via, type(exc).__name__)
                if i == len(attempts) - 1:
                    raise TranslateError(
                        "Cannot reach the translation service (%s). Check the connection or proxy."
                        % type(exc).__name__) from exc
            except requests.RequestException as exc:
                log.warning("translate %s via=%s request error %s", tag, via, type(exc).__name__)
                raise TranslateError("Translation request failed (%s)." % type(exc).__name__) from exc
        if resp.status_code != 200:
            log.warning("translate %s http=%s", tag, resp.status_code)
            raise TranslateError("Translation service returned HTTP %s." % resp.status_code)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise TranslateError("Translation service returned invalid data.") from exc
        translated, detected = parse_response(payload)
        result = TranslationResult(translated, detected, same_language(detected, target))
        log.info("translate ok %s via=%s ms=%d detected=%s", tag, via,
                 (time.monotonic() - started) * 1000, detected)
        self._cache_put(key, result)
        return result


def _system_proxies() -> Dict[str, str]:
    import urllib.request
    return urllib.request.getproxies()
