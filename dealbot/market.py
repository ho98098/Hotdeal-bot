"""다나와 가격비교 검색으로 시세 계산.
(네이버 쇼핑 검색 API는 2026-07-31 종료되어 사용하지 않습니다.)"""
import re
import statistics

import requests
from bs4 import BeautifulSoup

URL = "https://search.danawa.com/dsearch.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.danawa.com/",
}
NUM_RE = re.compile(r"\d[\d,]{2,}")
# 본품 시세를 흐리는 항목
EXCLUDE = ("중고", "리퍼", "단품", "케이스", "필름", "커버", "호환", "파우치", "해외")


def _num(text):
    m = NUM_RE.search(text or "")
    return int(m.group().replace(",", "")) if m else 0


def parse_danawa(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for li in soup.select("li.prod_item"):
        if not str(li.get("id", "")).startswith("productItem"):
            continue  # 광고 슬롯 제외
        a = li.select_one(".prod_name a")
        if not a:
            continue
        name = a.get_text(" ", strip=True)
        price = 0
        for sect in li.select(".price_sect"):
            label = sect.get_text(" ", strip=True)
            if any(x in label for x in ("중고", "해외", "렌탈", "리퍼")):
                continue
            strong = sect.select_one("strong")
            price = _num(strong.get_text() if strong else "")
            if price:
                break
        if price:
            out.append({"title": name, "price": price, "mall": "다나와 최저가", "link": a.get("href", "")})
    return out


def search(query, timeout=15):
    r = requests.get(URL, params={"query": query}, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return parse_danawa(r.text)


def _tokens(s):
    return set(re.findall(r"[0-9a-zA-Z가-힣]+", s.lower()))


def relevant(items, query, min_overlap=0.6):
    """검색어 단어의 60% 이상이 상품명에 있고, 액세서리·중고가 아닌 항목만."""
    q = _tokens(query)
    keep = []
    for it in items:
        if any(x in it["title"] and x not in query for x in EXCLUDE):
            continue
        joined = it["title"].lower().replace(" ", "")
        if not q or sum(1 for t in q if t in joined) / len(q) >= min_overlap:
            keep.append(it)
    return keep


def market_price(items):
    """시세 = 가장 관련 높은(첫) 상품의 다나와 최저가. 결과가 여러 개면 극단값 제외 중앙값과 비교해
    첫 상품이 튀면 중앙값 사용. 반환: (시세, 대표 항목) 또는 (None, None)"""
    if not items:
        return None, None
    first = items[0]
    if len(items) >= 3:
        med = statistics.median(it["price"] for it in items)
        if not (0.4 * med <= first["price"] <= 2.5 * med):
            core = [it for it in items if 0.4 * med <= it["price"] <= 2.5 * med]
            return int(statistics.median(it["price"] for it in core)), min(core, key=lambda x: x["price"])
    return first["price"], first


def discount(price, reference):
    return 0.0 if not reference else (reference - price) / reference
