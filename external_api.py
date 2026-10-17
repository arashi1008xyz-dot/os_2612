"""失敗時も手入力を続けられるISBN取得。画面やJSONには触らない。"""
import json
import re
from urllib.request import urlopen
from urllib.error import URLError


def normalize_isbn(value):
    isbn = re.sub(r"[-\s]", "", str(value))
    if not re.fullmatch(r"97[89]\d{10}", isbn) or sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(isbn)) % 10:
        raise ValueError("978または979で始まる正しいISBN-13を入力してください。")
    return isbn


def lookup_isbn(value):
    try:
        isbn = normalize_isbn(value)
        with urlopen(f"https://api.openbd.jp/v1/get?isbn={isbn}", timeout=8) as response:
            result = json.loads(response.read(2_000_000).decode("utf-8"))
        if not result or not result[0]:
            return None
        summary = result[0].get("summary", {})
        return {"title": summary.get("title"), "creator": summary.get("author"),
                "publisher": summary.get("publisher"), "image_url": summary.get("cover"),
                "metrics": {"pages": None}}
    except (ValueError, URLError, TimeoutError, OSError, KeyError, TypeError):
        return None
