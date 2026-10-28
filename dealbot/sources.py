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
MALL_PAREN_RE = re.compile(r"^\s*([^\s()\[\]]{1,12})\)\s*")          # 'G마켓) 오리온 ...'
# 쇼핑몰 이름이 아닌 말머리
GENERIC_TAGS = ("특가", "핫딜", "오늘만", "한정", "무료", "이벤트", "체험딜", "종료", "품절", "마감", "끌올",
                "타임딜", "선착순", "공유", "정보", "추천", "강추", "가격오류", "오류", "역대가", "최저가")


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
    downvotes: int = 0


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
    mall, rest = "", title
    for _ in range(3):                     # '[특가] [쿠팡] ...' 처럼 말머리가 앞에 붙은 경우 건너뜀
        m = MALL_RE.match(rest) or MALL_PAREN_RE.match(rest)
        if not m:
            break
        tag = m.group(1).strip()
        rest = rest[m.end():]
        if any(g in tag for g in GENERIC_TAGS) or re.fullmatch(r"[\d\s,./%~-]+", tag):
            continue
        mall = tag
        break
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
        d = Deal(source, f"{source}:{link}", title, name, mall, price, link, ended=is_ended(title))
        # 뽐뿌 RSS 의 <hits> [댓글|조회|추천|비추천] (두 번째가 조회수인 것만 확인됨)
        h = re.findall(r"\d+", item.findtext("hits") or "")
        if len(h) == 4:
            d.comments, d.votes, d.downvotes = int(h[0]), int(h[2]), int(h[3])
        deals.append(d)
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
    deals = _fetch_source(src, timeout)
    for d in deals:
        if not d.mall and src.get("mall"):
            d.mall = src["mall"]          # 예: 알리뽐뿌 글은 쇼핑몰 표기가 없어도 '알리'
    return deals


def _fetch_source(src, timeout=15):
    kind = src.get("type", "rss")
    if kind in ("coupang_goldbox", "ali_hot"):
        from . import shops
        return shops.coupang_goldbox() if kind == "coupang_goldbox" else shops.ali_hot()
    r = requests.get(src["url"], headers=BROWSER_UA if kind != "rss" else UA, timeout=timeout)
    r.raise_for_status()
    if kind == "clien":
        return parse_clien(r.text, src["name"])
    if kind == "ruliweb":
        return parse_ruliweb(r.text, src["name"])
    return parse_rss(r.content, src["name"])


# 키워드가 다른 단어 속에 들어가 잘못 분류되는 것 방지 (예: '김치냉장고' 의 '김치')
DEFAULT_EXCLUDE = {
    "식품": ["냉장고", "냉동고", "세탁기", "건조기", "에어컨", "정수기", "밥솥", "전자레인지", "오븐", "에어프라이어",
           "믹서", "블렌더", "커피머신", "커피메이커", "그라인더", "포트", "청소기", "식기세척기", "인덕션", "가스레인지",
           "제습기", "가습기", "냉온수기", "디스펜서", "보관함", "밀폐용기", "쌀통", "찜기", "텀블러", "머그", "컵",
           "케이스", "필름", "충전기", "노트북", "모니터", "의자", "책상", "가방", "신발", "자켓", "패딩"],
    "생활용품": ["홀더", "디스펜서", "거치대", "케이스"],
}


def match_category(title, categories, excludes=None):
    low = title.lower()
    excludes = DEFAULT_EXCLUDE if excludes is None else excludes
    for cat, keywords in categories.items():
        if not any(k.lower() in low for k in keywords):
            continue
        if any(x.lower() in low for x in excludes.get(cat, [])):
            continue  # 이 카테고리 제외 단어가 있으면 다음 카테고리 확인
        return cat
    return ""


# ---------------- 게시글 상세: 반응(추천·비추천·댓글) 읽기 ----------------
def _int(text):
    m = re.search(r"\d[\d,]*", text or "")
    return int(m.group().replace(",", "")) if m else 0


def parse_reaction(html_text, kind):
    """반환: {"votes", "downvotes", "comments", "texts"(댓글 내용 목록)} 또는 None(지원 안 함)"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    if kind == "ruliweb":
        like = soup.select_one("span.like_value")
        dis = soup.select_one("span.dislike_value")
        cnt = soup.select_one(".comment_count")
        texts = [e.get_text(" ", strip=True) for e in soup.select(".comment_view .comment_element .text_wrapper")]
        return {"votes": _int(like.get_text() if like else ""), "downvotes": _int(dis.get_text() if dis else ""),
                "comments": _int(cnt.get_text() if cnt else "") or len(texts), "texts": texts}
    if kind == "clien":
        sym = soup.select_one(".symph_count") or soup.select_one(".view_symph")
        head = soup.select_one(".comment_head")
        texts = [e.get_text(" ", strip=True) for e in soup.select(".comment_content")]
        n = re.search(r"\[\s*(\d+)\s*\]", head.get_text() if head else "")
        return {"votes": _int(sym.get_text() if sym else ""), "downvotes": 0,
                "comments": int(n.group(1)) if n else len(texts), "texts": texts}
    if kind == "eomisae":
        vote = soup.select_one(".vote")
        m = re.search(r"추천\s*(\d+)", vote.get_text(" ") if vote else "")
        texts = [e.get_text(" ", strip=True) for e in soup.select(".xe_content")][1:]  # 첫 번째는 본문
        return {"votes": int(m.group(1)) if m else 0, "downvotes": 0, "comments": len(texts), "texts": texts}
    return None


def view_kind(link):
    if "ruliweb.com" in link:
        return "ruliweb"
    if "clien.net" in link:
        return "clien"
    if "eomisae.co.kr" in link:
        return "eomisae"
    return None  # 뽐뿌 상세 페이지는 GitHub 서버 접속이 막혀 RSS 숫자로 판단


def fetch_reaction(link, timeout=15):
    kind = view_kind(link)
    if not kind:
        return None
    r = requests.get(link, headers=BROWSER_UA, timeout=timeout)
    r.raise_for_status()
    return parse_reaction(r.text, kind)
