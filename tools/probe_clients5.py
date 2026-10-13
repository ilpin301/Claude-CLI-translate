"""Print raw responses of the clients5 dict-chrome-ex endpoint for FIXED sample texts (never your selections).

Run from the project folder:  python tools/probe_clients5.py
Paste the whole output back.
"""
import time

import requests

URL = "https://clients5.google.com/translate_a/t"
SAMPLES = [
    ("short", "Hello world", "ru", "GET"),
    ("two sentences", "Hello world. This is a test.", "ru", "GET"),
    ("multi-line", "First line\nSecond line\n\nNew paragraph", "ru", "GET"),
    ("russian->english", "Привет, как дела?", "en", "GET"),
    ("same language", "Привет, как дела?", "ru", "GET"),
    ("long GET (1400 chars)", ("The quick brown fox jumps over the lazy dog. " * 31)[:1400], "ru", "GET"),
    ("long POST (3000 chars)", ("The quick brown fox jumps over the lazy dog. " * 67)[:3000], "ru", "POST"),
]


def main() -> None:
    session = requests.Session()
    session.trust_env = False
    for name, text, tl, method in SAMPLES:
        params = {"client": "dict-chrome-ex", "sl": "auto", "tl": tl}
        try:
            if method == "GET":
                params["q"] = text
                resp = session.get(URL, params=params, timeout=(5, 10))
            else:
                resp = session.post(URL, params=params, data={"q": text}, timeout=(5, 10))
            body = resp.content.decode("utf-8", "replace")
            print("== %s [%s] -> HTTP %s, %d bytes" % (name, method, resp.status_code, len(resp.content)))
            print(body[:500] + (" ...[cut]" if len(body) > 500 else ""))
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            print("== %s [%s] -> ERROR %s" % (name, method, type(exc).__name__))
        time.sleep(1.5)


if __name__ == "__main__":
    main()
