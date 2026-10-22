"""핫딜 게시판 RSS 수집과 제목 파싱."""
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

UA = {"User-Agent": "Mozilla/5.0 (personal deal watcher)"}

PRICE_RE = re.compile(r"(?<![만\d,.])(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
MAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*만\s*(\d{1,4})?\s*원?")
BARE_RE = re.compile(r"\(\s*(\d{1,3}(?:,\d{3})+)\s*/")
# '98000+배송무료', '12,900/무배', '15900 무료배송' 처럼 '원' 없이 적은 가격 (외화 표기는 제외)
SHIP_RE = re.compile(r"(?<![\d,.$€¥])(\d{1,3}(?:,\d{3})+|\d{4,})\s*(?:\+\s*|/\s*|\s)(?:배송|무료|무배|택배|와우|로켓)")
FOREIGN_RE = re.compile(r"(\$|usd|jpy|eur|cny|€|¥|달러|엔|유로|위안|불)\s*$", re.I)
ENTITY_RE = re.compile(rb"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
MALL_RE = re.compile(r"^\s*\[([^\]]+)\]\s*")


@dataclass
class Deal:
    source: str
    id: str
    title: str      # 원래 제목
    name: str       # 쇼핑몰/가격 표기를 뗀 상품명
    mall: str
    price: int      # 못 찾으면 0
    link: str
    category: str = ""
    votes: int = 0
    comments: int = 0
    ended: bool = False


ENDED_RE = re.compile(r"[\[(【]\s*(종료|품절|마감|끝)\s*[\])】]|^\s*(종료|품절)\b|딜\s*종료|품절됨")


def is_ended(title):
    return bool(ENDED_RE.search(title))


def parse_price(text):
    """'189,000원', '18.9만원', '3만5천원' 류에서 첫 가격을 원 단위로."""
    m = PRICE_RE.search(text)
    if m:
        return int(m.group(1).replace(",", ""))
    m = MAN_RE.search(text)
    if m:
        return int(float(m.group(1)) * 10000) + int(m.group(2) or 0)
    m = BARE_RE.search(text)  # '(11,900/무배)' 처럼 '원' 없이 적은 경우
    if m and not FOREIGN_RE.search(text[:m.start(1)]):
        return int(m.group(1).replace(",", ""))
    for m in SHIP_RE.finditer(text):
        if not FOREIGN_RE.search(text[:m.start(1)]):
            return int(m.group(1).replace(",", ""))
    return 0


def parse_title(title):
    """'[쿠팡] 갤럭시 버즈3 프로 (189,000원/무료)' -> (mall, name, price)"""
    mall = ""
    m = MALL_RE.match(title)
    rest = title
    if m:
        mall, rest = m.group(1).strip(), title[m.end():]
    price = parse_price(rest)
    # 끝의 (가격/배송) 괄호와 댓글수 [12] 제거
    name = re.sub(r"\s*\[\d+\]\s*$", "", rest)
    name = re.sub(r"\s*\([^()]*(원|무료|무배|배송)[^()]*\)\s*$", "", name).strip()
    return mall, name, price


def parse_rss(xml_bytes, source):
    # 실제 피드에 &nbsp; 같은 비표준 엔티티가 섞여 있어 그대로는 파싱이 깨짐
    xml_bytes = xml_bytes.replace(b"&nbsp;", b" ")
    root = ET.fromstring(ENTITY_RE.sub(b"&amp;", xml_bytes))
    deals = []
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        mall, name, price = parse_title(title)
        deals.append(Deal(source, f"{source}:{link}", title, name, mall, price, link, ended=is_ended(title)))
    return deals


def parse_clien(html_text, source="클리앙"):
    """클리앙 알뜰구매 목록 (RSS가 없어 목록 화면을 읽음)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    deals = []
    for row in soup.select("div.list_item.symph_row[data-board-sn]"):
        a = row.select_one(".list_subject a[data-role=list-title-text]")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        link = "https://www.clien.net" + a.get("href", "").split("?")[0]
        mall, name, price = parse_title(title)
        em = row.select_one(".list_symph em")
        votes = int(em.get_text(strip=True) or 0) if em and em.get_text(strip=True).isdigit() else 0
        comments = int(row.get("data-comment-count") or 0)
        deals.append(Deal(source, f"{source}:{row['data-board-sn']}", title, name, mall, price, link,
                          votes=votes, comments=comments, ended=is_ended(title)))
    return deals


def parse_ruliweb(html_text, source="루리웹"):
    """루리웹 핫딜 목록 화면 (추천·댓글 수 포함)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    deals = []
    for row in soup.select("tr.table_body"):
        if "notice" in row.get("class", []):
            continue
        a = row.select_one("a.subject_link")
        if not a:
            continue
        link = a.get("href", "").split("?")[0]
        m = re.search(r"/read/(\d+)", link)
        if not m:
            continue
        subj = row.select_one("td.subject")
        ended = bool(subj and "[종료]" in subj.get_text(" ", strip=True))
        reply = row.select_one(".num_reply")
        if reply:
            reply.extract()
        title = a.get_text(" ", strip=True)
        rec = row.select_one("td.recomd")
        votes = int(rec.get_text(strip=True)) if rec and rec.get_text(strip=True).isdigit() else 0
        comments = int(re.sub(r"\D", "", reply.get_text()) or 0) if reply else 0
        mall, name, price = parse_title(title)
        deals.append(Deal(source, f"{source}:{m.group(1)}", title, name, mall, price, link,
                          votes=votes, comments=comments, ended=ended or is_ended(title)))
    return deals


BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36", "Accept-Language": "ko-KR,ko;q=0.9"}


def fetch_source(src, timeout=15):
    kind = src.get("type", "rss")
    r = requests.get(src["url"], headers=BROWSER_UA if kind != "rss" else UA, timeout=timeout)
    r.raise_for_status()
    if kind == "clien":
        return parse_clien(r.text, src["name"])
    if kind == "ruliweb":
        return parse_ruliweb(r.text, src["name"])
    return parse_rss(r.content, src["name"])


def match_category(title, categories):
    low = title.lower()
    for cat, keywords in categories.items():
        if any(k.lower() in low for k in keywords):
            return cat
    return ""
