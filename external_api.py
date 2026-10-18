"""失敗時も手入力を続けられるISBN・映像作品の取得。画面やJSONには触らない。"""
import json
import os
import re
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HEADERS = {"User-Agent": "ContentRecordApp/1.0"}
MAX_RESPONSE_BYTES = 2_000_000
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
ANNICT_API_BASE = "https://api.annict.com/v1"
# キーは.streamlit/secrets.toml（Streamlitが環境変数にも展開する）か環境変数で渡す。
VIDEO_KEY_NAMES = {"TMDB": ("TMDB_API_READ_ACCESS_TOKEN", "TMDB_API_KEY"), "Annict": ("ANNICT_ACCESS_TOKEN",)}

# Cコード（書籍JANコード2段目の分類記号）の各桁の意味。
C_CODE_AUDIENCES = {
    "0": "一般", "1": "教養", "2": "実用", "3": "専門", "4": "検定教科書・消費税非課税品",
    "5": "女性向け", "6": "小中学生向け学習参考書", "7": "高校生向け学習参考書",
    "8": "児童向け", "9": "雑誌扱いコミックス・ムック",
}
C_CODE_FORMATS = {
    "0": "単行本", "1": "文庫", "2": "新書", "3": "全集・双書", "4": "ムック・その他",
    "5": "辞典・事典", "6": "図鑑", "7": "絵本", "8": "記録媒体・オーディオブック", "9": "コミックス",
}
C_CODE_MAIN_CATEGORIES = {
    "0": "総記", "1": "哲学・心理学・宗教", "2": "歴史・地理", "3": "社会科学",
    "4": "自然科学", "5": "工学・工業", "6": "産業", "7": "芸術・生活", "8": "語学", "9": "文学",
}
C_CODE_CONTENTS = {
    "00": "総記", "01": "百科事典", "02": "年鑑・雑誌", "04": "情報科学",
    "10": "哲学", "11": "心理（学）", "12": "倫理（学）", "14": "宗教", "15": "仏教", "16": "キリスト教",
    "20": "歴史総記", "21": "日本歴史", "22": "外国歴史", "23": "伝記・系譜", "25": "地理", "26": "旅行",
    "30": "社会科学総記", "31": "政治（国防・軍事含む）", "32": "法律", "33": "経済・財政・統計",
    "34": "経営", "36": "社会", "37": "教育", "39": "民族・風習",
    "40": "自然科学総記", "41": "数学", "42": "物理学", "43": "化学", "44": "天文・地学", "45": "生物学", "47": "医学・歯学・薬学",
    "50": "工学・工業総記", "51": "土木", "52": "建築", "53": "機械", "54": "電気", "55": "電子通信",
    "56": "海事・兵器", "57": "採鉱・冶金", "58": "各種工業",
    "60": "産業総記", "61": "農林業", "62": "水産業", "63": "商業", "65": "交通・通信",
    "70": "芸術総記", "71": "絵画・彫刻", "72": "写真・工芸", "73": "音楽・舞踊", "74": "演劇・映画",
    "75": "体育・スポーツ", "76": "諸芸・娯楽", "77": "家事", "78": "生活", "79": "コミックス・劇画",
    "80": "語学総記", "81": "日本語", "82": "英米語", "84": "ドイツ語", "85": "フランス語", "87": "各国語",
    "90": "文学総記", "91": "日本文学総記", "92": "日本文学・詩歌", "93": "日本文学・小説・物語",
    "95": "日本文学・評論・随筆その他", "97": "外国文学・小説", "98": "外国文学・その他",
}


def _isbn13_check(digits12):
    return (10 - sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(digits12)) % 10) % 10


def normalize_isbn(value):
    """ISBN-10・ISBN-13を検証し、保存・検索用のISBN-13（ハイフンなし）を返す。"""
    text = re.sub(r"(?i)^ISBN(?:-1[03])?\s*:?\s*", "", str(value).strip())
    digits = re.sub(r"[-\s]", "", text).upper()
    if re.fullmatch(r"[0-9]{9}[0-9X]", digits):
        check = 10 if digits[-1] == "X" else int(digits[-1])
        if (sum((10 - i) * int(n) for i, n in enumerate(digits[:9])) + check) % 11:
            raise ValueError("ISBN-10のチェック数字が正しくありません。")
        core = "978" + digits[:9]
        return core + str(_isbn13_check(core))
    if not re.fullmatch(r"97[89][0-9]{10}", digits) or _isbn13_check(digits[:12]) != int(digits[-1]):
        raise ValueError("978または979で始まる正しいISBN-13（またはISBN-10）を入力してください。")
    return digits


def classify_ccode(ccode):
    """Cコード4桁を販売対象・発行形態・内容に分解する。形式が違えばValueError。"""
    code = re.sub(r"\s+", "", str(ccode)).upper().removeprefix("C")
    if not re.fullmatch(r"\d{4}", code):
        raise ValueError("Cコードは4桁の数字で指定してください。")
    content = code[2:]
    return {
        "ccode": code, "audience_code": code[0], "audience_label": C_CODE_AUDIENCES.get(code[0]),
        "format_code": code[1], "format_label": C_CODE_FORMATS.get(code[1]),
        "major_code": code[2], "major_label": C_CODE_MAIN_CATEGORIES.get(code[2]),
        "content_code": content, "content_label": C_CODE_CONTENTS.get(content),
    }


def _get_json(url, timeout, headers=None):
    with urlopen(Request(url, headers={**HEADERS, **(headers or {})}), timeout=timeout) as response:
        return json.loads(response.read(MAX_RESPONSE_BYTES).decode("utf-8"))


def _openlibrary_cover(isbn):
    """openBDに表紙がないときの予備。Open Libraryに表紙があればそのURL、なければNone。"""
    query = urlencode({"bibkeys": f"ISBN:{isbn}", "jscmd": "data", "format": "json"})
    try:
        book = _get_json(f"https://openlibrary.org/api/books?{query}", timeout=8).get(f"ISBN:{isbn}")
        # jscmd=dataでは表紙はcover（small・medium・large）に入る。thumbnail_urlはjscmd=viewapiの項目。
        cover = book.get("cover") if isinstance(book, dict) else None
        url = (cover.get("medium") or cover.get("small")) if isinstance(cover, dict) else None
        return str(url) if url else None
    except (ValueError, URLError, TimeoutError, OSError, AttributeError):
        return None


def _parse_openbd(item):
    """openBDの1件分から、summaryで欠けがちな著者・出版社・ページ数・Cコードを補って取り出す。"""
    onix = item.get("onix") or {}
    detail = onix.get("DescriptiveDetail") or {}
    publishing = onix.get("PublishingDetail") or {}
    summary = item.get("summary") or {}

    title_element = (detail.get("TitleDetail") or {}).get("TitleElement") or {}
    names = [(c.get("PersonName") or {}).get("content") for c in detail.get("Contributor") or [] if isinstance(c, dict)]

    ccode = None
    for subject in detail.get("Subject") or []:
        if isinstance(subject, dict) and str(subject.get("SubjectSchemeIdentifier")) == "78":
            ccode = str(subject.get("SubjectCode", "")).strip() or None
    try:
        classification = classify_ccode(ccode) if ccode else None
    except ValueError:
        classification = None

    pages = None
    for extent in detail.get("Extent") or []:
        if isinstance(extent, dict) and extent.get("ExtentType") == "11":  # 11 = 本文のページ数
            try:
                pages = int(extent.get("ExtentValue"))
            except (TypeError, ValueError):
                pass
            break

    return {
        "title": summary.get("title") or (title_element.get("TitleText") or {}).get("content"),
        "creator": summary.get("author") or "、".join(n for n in names if n) or None,
        "publisher": summary.get("publisher") or (publishing.get("Imprint") or {}).get("ImprintName")
                     or (publishing.get("Publisher") or {}).get("PublisherName"),
        "image_url": summary.get("cover") or None,
        "metrics": {"pages": pages if pages and pages > 0 else None},
        "classification": classification,
    }


def lookup_isbn(value):
    """openBDから書誌情報を取得する。失敗時はNone（画面を止めない）。

    戻り値：title・creator・publisher・image_url・metrics.pages（取れない項目はNone）に加え、
    isbn・image_source（"openBD" / "Open Library" / None）・classification（Cコードの分類、なければNone）・
    suggested_category（Cコードがコミックスなら"manga"、それ以外は"book"）。
    """
    try:
        isbn = normalize_isbn(value)
        result = _get_json(f"https://api.openbd.jp/v1/get?{urlencode({'isbn': isbn})}", timeout=8)
        item = result[0] if isinstance(result, list) and result else None
        if isinstance(item, dict):
            book = _parse_openbd(item)
        else:
            # openBDに無い本でも、表紙だけはOpen Libraryにあることがある。
            book = {"title": None, "creator": None, "publisher": None, "image_url": None,
                    "metrics": {"pages": None}, "classification": None}
        image_source = "openBD" if book["image_url"] else None
        if not book["image_url"]:
            book["image_url"] = _openlibrary_cover(isbn)
            image_source = "Open Library" if book["image_url"] else None
        if not isinstance(item, dict) and not book["image_url"]:
            return None
        classification = book["classification"] or {}
        return {**book, "isbn": isbn, "image_source": image_source,
                "suggested_category": "manga" if classification.get("format_code") == "9" else "book"}
    except (ValueError, URLError, TimeoutError, OSError, KeyError, TypeError, AttributeError):
        return None


VIDEO_ERRORS = (ValueError, URLError, TimeoutError, OSError, KeyError, TypeError, AttributeError)


def _secret(name):
    return os.environ.get(name, "").strip()


def video_sources(category):
    """カテゴリの検索に使うサービス。アニメはAnnictを先に使い、無ければTMDBのテレビ作品で探す。"""
    return ["Annict", "TMDB"] if category == "anime" else ["TMDB"]


def missing_video_keys(category):
    """検索に使えるキーが1つも無いときだけ、設定すべきキー名を返す。"""
    if any(_secret(n) for s in video_sources(category) for n in VIDEO_KEY_NAMES[s]):
        return []
    return [VIDEO_KEY_NAMES[s][0] for s in video_sources(category)]


def _tmdb_get(path, params):
    token, api_key = _secret("TMDB_API_READ_ACCESS_TOKEN"), _secret("TMDB_API_KEY")
    if not token and not api_key:
        raise ValueError("TMDBのキーが未設定です。")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        params = {**params, "api_key": api_key}
    return _get_json(f"{TMDB_API_BASE}{path}?{urlencode(params)}", timeout=10, headers=headers)


def _annict_get(path, params):
    token = _secret("ANNICT_ACCESS_TOKEN")
    if not token:
        raise ValueError("Annictのキーが未設定です。")
    return _get_json(f"{ANNICT_API_BASE}{path}?{urlencode(params)}", timeout=10,
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})


def _join(names, limit=3):
    return "、".join(list(dict.fromkeys(n for n in names if n))[:limit]) or None


def _positive(value):
    return value if isinstance(value, int) and value > 0 else None


def _search_tmdb(query, category):
    media = "movie" if category == "movie" else "tv"
    params = {"query": query, "language": "ja-JP", "page": "1", "include_adult": "false"}
    results = []
    for item in _tmdb_get(f"/search/{media}", params).get("results") or []:
        if not isinstance(item, dict) or not (item.get("title") or item.get("name")) or item.get("id") is None:
            continue
        poster = item.get("poster_path")
        results.append({
            "source": "TMDB", "external_id": str(item["id"]), "media": media,
            "title": str(item.get("title") or item.get("name")),
            "release_date": item.get("release_date") or item.get("first_air_date") or None,
            "image_url": f"{TMDB_IMAGE_BASE}{poster}" if poster else None,
            "creator": None, "studio": None, "metrics": {},
        })
    return results[:10]


def _search_annict(query):
    params = {"filter_title": query, "per_page": "10", "sort_watchers_count": "desc"}
    results = []
    for item in _annict_get("/works", params).get("works") or []:
        if not isinstance(item, dict) or not item.get("title") or item.get("id") is None:
            continue
        image = (item.get("images") or {}).get("recommended_url") or None
        results.append({
            "source": "Annict", "external_id": str(item["id"]), "media": "tv",
            "title": str(item["title"]),
            "release_date": item.get("released_on") or item.get("season_name_text") or None,
            # Annictの画像は外部サイトのURLで、httpや空文字のこともある。
            "image_url": image if str(image).startswith("https://") else None,
            "creator": None, "studio": None, "metrics": {"episodes": _positive(item.get("episodes_count"))},
        })
    return results


def search_video(query, category):
    """映画・ドラマはTMDB、アニメはAnnict（無ければTMDB）で作品名を検索する。

    戻り値：候補のリスト（見つからなければ[]）。キー未設定・通信失敗などで1つも検索できなければNone。
    各候補はsource・external_id・title・release_date・image_url・creator・studio・metricsを持つ。
    """
    query = str(query or "").strip()
    if not query:
        return None
    searched = False
    for source in video_sources(category):
        try:
            results = _search_annict(query) if source == "Annict" else _search_tmdb(query, category)
        except VIDEO_ERRORS:
            continue
        searched = True
        if results:
            return results
    return [] if searched else None


def _tmdb_details(item):
    media = item["media"]
    payload = _tmdb_get(f"/{media}/{item['external_id']}",
                        {"language": "ja-JP", **({"append_to_response": "credits"} if media == "movie" else {})})
    poster = payload.get("poster_path")
    details = {**item, "title": payload.get("title") or payload.get("name") or item["title"],
               "image_url": f"{TMDB_IMAGE_BASE}{poster}" if poster else item["image_url"],
               "studio": _join(c.get("name") for c in payload.get("production_companies") or [] if isinstance(c, dict))}
    if media == "movie":
        crew = (payload.get("credits") or {}).get("crew") or []
        details["creator"] = _join(p.get("name") for p in crew if isinstance(p, dict) and p.get("job") == "Director")
        details["metrics"] = {"minutes": _positive(payload.get("runtime"))}
    else:
        details["creator"] = _join(p.get("name") for p in payload.get("created_by") or [] if isinstance(p, dict))
        runtimes = [r for r in payload.get("episode_run_time") or [] if _positive(r)]
        # episode_run_timeは空のことが多いので、最新話の長さで補う。
        runtime = round(sum(runtimes) / len(runtimes)) if runtimes else _positive((payload.get("last_episode_to_air") or {}).get("runtime"))
        details["metrics"] = {"episodes": _positive(payload.get("number_of_episodes")), "minutes_per_episode": runtime}
    return details


def _annict_details(item):
    staffs = _annict_get("/staffs", {"filter_work_id": item["external_id"], "per_page": "50"}).get("staffs") or []
    def names(role):
        for s in staffs:
            if isinstance(s, dict) and s.get("role_text") == role:
                yield s.get("name") or (s.get("person") or {}).get("name") or (s.get("organization") or {}).get("name")
    return {**item, "creator": _join(names("監督")), "studio": _join(names("アニメーション制作")),
            "metrics": {**item["metrics"], "minutes_per_episode": None}}


def video_details(item):
    """候補1件の詳細（監督・制作会社・上映時間／話数など）を取得する。失敗時は候補をそのまま返す。

    戻り値のmetricsは、映画がminutes、アニメ・ドラマがepisodes・minutes_per_episode（取れない値はNone）。
    """
    try:
        return _annict_details(item) if item["source"] == "Annict" else _tmdb_details(item)
    except VIDEO_ERRORS:
        return item
