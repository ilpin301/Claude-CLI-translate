"""Diagnose Google translate access: tries several request variants and prints only HTTP status codes.

Run from the project folder:  python tools/probe_translate.py
Sends the fixed text "Hello world" (never your selections). Paste the whole output back.
"""
import sys
import time

sys.path.insert(0, ".")

import requests

from cct import translate

TEXT = "Hello world"
HOSTS = {
    "googleapis gtx": ("https://translate.googleapis.com/translate_a/single",
                       {"client": "gtx", "sl": "auto", "tl": "ru", "dt": "t", "q": TEXT}),
    "googleapis gtx dj": ("https://translate.googleapis.com/translate_a/single",
                          {"client": "gtx", "sl": "auto", "tl": "ru", "dt": ["t", "bd"], "dj": "1", "q": TEXT}),
    "translate.google.com gtx": ("https://translate.google.com/translate_a/single",
                                 {"client": "gtx", "sl": "auto", "tl": "ru", "dt": "t", "q": TEXT}),
    "clients5 dict-chrome-ex": ("https://clients5.google.com/translate_a/t",
                                {"client": "dict-chrome-ex", "sl": "auto", "tl": "ru", "q": TEXT}),
}
UAS = {"python-requests": None, "browser UA": translate.USER_AGENT}


def routes():
    proxy = translate.parse_system_proxy(translate._system_proxies())
    out = {"direct": None}
    if proxy:
        out["proxy " + proxy] = proxy
    else:
        print("(no system SOCKS proxy found by urllib.request.getproxies())")
    return out


def main() -> None:
    print("system proxies:", translate._system_proxies())
    for route_name, proxy in routes().items():
        for host_name, (url, params) in HOSTS.items():
            for ua_name, ua in UAS.items():
                session = requests.Session()
                session.trust_env = False
                if ua:
                    session.headers["User-Agent"] = ua
                proxies = {"http": proxy, "https": proxy} if proxy else None
                started = time.monotonic()
                try:
                    resp = session.get(url, params=params, timeout=(5, 10), proxies=proxies)
                    result = "HTTP %s, %d bytes" % (resp.status_code, len(resp.content))
                except Exception as exc:  # noqa: BLE001 - diagnostic only
                    result = "ERROR %s" % type(exc).__name__
                print("%-24s | %-40s | %-15s | %s (%.1fs)" % (
                    route_name[:24], host_name, ua_name, result, time.monotonic() - started))
                time.sleep(1.5)  # be gentle: do not trigger rate limits ourselves


if __name__ == "__main__":
    main()
