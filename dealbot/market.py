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


SKIP_LABELS = ("중고", "해외", "렌탈", "리퍼")
ROW_RE = re.compile(r"([^|]{0,20})\|\s*([\d,]{4,})원\s*\|\s*\d+\s*\|\s*몰")


def parse_danawa(html):
    """다나와 검색 결과. 다나와가 예전 화면과 새 화면을 섞어서 보내므로 둘 다 처리."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    # 예전 화면
    for li in soup.select("li.prod_item"):
        if not str(li.get("id", "")).startswith("productItem"):
            continue  # 광고 슬롯 제외
        a = li.select_one(".prod_name a")
        if not a:
            continue
        price = 0
        for sect in li.select(".price_sect"):
            label = sect.get_text(" ", strip=True)
            if any(x in label for x in SKIP_LABELS):
                continue
            strong = sect.select_one("strong")
            price = _num(strong.get_text() if strong else "")
            if price:
                break
        if price:
            out.append({"title": a.get_text(" ", strip=True), "price": price,
                        "mall": "다나와 최저가", "link": a.get("href", "")})
    if out:
        return out
    # 새 화면: 상품마다 div.flex.py-6, 가격은 '정품 | 219,530원 | 162 | 몰' 형태
    for d in soup.select("div.flex.py-6"):
        a = d.find("a", href=re.compile(r"prod\.danawa\.com/info/\?pcode="))
        img = d.find("img")
        if not a or not img or not img.get("alt"):
            continue
        name = BeautifulSoup(img["alt"], "html.parser").get_text().strip()
        text = d.get_text(" | ", strip=True)
        text = text[text.rfind("상품분류"):] if "상품분류" in text else text
        price = 0
        for label, num in ROW_RE.findall(text):
            if not any(x in label for x in SKIP_LABELS):
                price = int(num.replace(",", ""))
                break
        if price:
            out.append({"title": name, "price": price, "mall": "다나와 최저가", "link": a.get("href", "")})
    return out


def search(query, timeout=15):
    r = requests.get(URL, params={"query": query}, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return parse_danawa(r.text)


NOISE_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]|당일\S*|무료\S*|무배|관부가세\S*|정품|국내|해외\S*|블루투스|공식\S*|특가|할인")
MODEL_RE = re.compile(r"\b[A-Z]{1,5}-?[A-Z]?\d{2,}[A-Z0-9]*\b")


def clean_query(name):
    """핫딜 글 제목에서 검색에 방해되는 말(괄호, 배송·관세 문구 등)을 걷어냄."""
    return re.sub(r"\s+", " ", NOISE_RE.sub(" ", name)).strip()


def _tokens(s):
    return set(re.findall(r"[0-9a-zA-Z가-힣]+", s.lower()))


def relevant(items, query, min_overlap=0.6):
    """관련도 순으로 정렬해 반환. 액세서리·중고 제외, 모델명(SM-R640 등)이 있으면 일치 필수."""
    q = _tokens(query)
    models = [m.replace("-", "").lower() for m in MODEL_RE.findall(query)]
    scored = []
    for i, it in enumerate(items):
        if any(x in it["title"] and x not in query for x in EXCLUDE):
            continue
        joined = it["title"].lower().replace(" ", "").replace("-", "")
        if models and not any(m in joined for m in models):
            continue
        score = sum(1 for t in q if t in joined) / len(q) if q else 1
        if score >= min_overlap:
            scored.append((-score, i, it))
    return [it for _, _, it in sorted(scored, key=lambda x: (x[0], x[1]))]


def market_price(items):
    """시세 = 가장 관련 높은 상품의 다나와 최저가. 반환: (시세, 그 항목) 또는 (None, None)"""
    if not items:
        return None, None
    return items[0]["price"], items[0]


def discount(price, reference):
    return 0.0 if not reference else (reference - price) / reference
