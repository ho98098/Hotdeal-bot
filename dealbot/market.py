"""네이버 쇼핑 검색 API로 시세 계산."""
import re
import statistics

import requests

API = "https://openapi.naver.com/v1/search/shop.json"
TAG_RE = re.compile(r"<[^>]+>")


def search(query, client_id, client_secret, display=30, timeout=10):
    r = requests.get(
        API,
        params={"query": query, "display": display, "sort": "sim"},
        headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
        timeout=timeout,
    )
    r.raise_for_status()
    out = []
    for it in r.json().get("items", []):
        try:
            price = int(it.get("lprice") or 0)
        except ValueError:
            price = 0
        if price > 0:
            out.append({
                "title": TAG_RE.sub("", it.get("title", "")),
                "price": price,
                "mall": it.get("mallName", ""),
                "link": it.get("link", ""),
            })
    return out


def _tokens(s):
    return set(re.findall(r"[0-9a-zA-Z가-힣]+", s.lower()))


def relevant(items, query, min_overlap=0.6):
    """검색어 단어의 60% 이상이 제목에 들어 있는 결과만 (케이스·필름 같은 엉뚱한 상품 줄이기)."""
    q = _tokens(query)
    if not q:
        return items
    keep = []
    for it in items:
        joined = it["title"].lower().replace(" ", "")
        hit = sum(1 for t in q if t in joined)
        if hit / len(q) >= min_overlap:
            keep.append(it)
    return keep


def market_price(items):
    """시세 = 가격 중앙값. 중앙값의 40% 미만(액세서리)·250% 초과(묶음)는 빼고 다시 계산.
    반환: (시세, 최저가 항목) 또는 (None, None)"""
    prices = [it["price"] for it in items]
    if len(prices) < 3:
        return None, None
    med = statistics.median(prices)
    core = [it for it in items if 0.4 * med <= it["price"] <= 2.5 * med]
    if len(core) < 3:
        return None, None
    return int(statistics.median(it["price"] for it in core)), min(core, key=lambda x: x["price"])


def discount(price, reference):
    return 0.0 if not reference else (reference - price) / reference
