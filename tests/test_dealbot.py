import time
import pytest
from dealbot import market, sources
from dealbot.app import App
from dealbot.store import Store

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title>[쿠팡] 삼성 갤럭시 버즈3 프로 (150,000원/무료)</title><link>http://x/1</link></item>
<item><title>[11번가] 삼성 갤럭시 워치7 (300,000원/무료) [12]</title><link>http://x/2</link></item>
<item><title>[G마켓] 신라면 40봉 (25,000원/무료)</title><link>http://x/3</link></item>
</channel></rss>""".encode()


class FakeTG:
    chat_id = "1"
    def __init__(self): self.sent, self.queue = [], []
    def send(self, t): self.sent.append(t)
    def updates(self, offset=0): return [u for u in self.queue if u["update_id"] >= offset]


def items(*prices, title="삼성 갤럭시 버즈3 프로"):
    return [{"title": title, "price": p, "mall": "몰", "link": "http://n"} for p in prices]


def make(search, tmp_path):
    cfg = {"categories": {"전자제품": ["갤럭시"]}, "sources": [{"name": "뽐뿌", "url": "u"}],
           "discount_threshold": 0.15, "request_delay_seconds": 0, "min_price": 5000}
    tg = FakeTG()
    return App(cfg, Store(str(tmp_path / "t.db")), tg, search_fn=search,
               fetch_fn=lambda s: sources.parse_rss(RSS, s["name"])), tg


@pytest.mark.parametrize("t,exp", [("189,000원", 189000), ("18.9만원", 189000), ("3만5000원", 35000), ("무료", 0), ("롤케이크 400g(11,900/무배)", 11900)])
def test_parse_price(t, exp):
    assert sources.parse_price(t) == exp


def test_parse_title():
    assert sources.parse_title("[쿠팡] 갤럭시 버즈3 (150,000원/무료) [3]") == ("쿠팡", "갤럭시 버즈3", 150000)


def test_market_price_drops_accessories():
    ref, low = market.market_price(items(200000, 210000, 190000, 205000, 9900))
    assert ref == 202500 and low["price"] == 190000


def test_relevant_filters_unrelated():
    its = items(1, title="갤럭시 버즈3 프로") + items(1, title="아이폰 케이스")
    assert len(market.relevant(its, "삼성 갤럭시 버즈3 프로")) == 1


def test_boards_alert_only_when_cheap_and_in_category(tmp_path):
    def search(q):
        return items(200000, 210000, 190000, title=q) if "버즈" in q else items(310000, 300000, 305000, title=q)
    app, tg = make(search, tmp_path)
    assert app.check_boards() == 1          # 버즈만: 25% 저렴. 워치는 2%, 라면은 카테고리 밖
    assert "25%" in tg.sent[0] and "버즈3" in tg.sent[0]
    assert app.check_boards() == 0          # 같은 글은 다시 알리지 않음


def test_watchlist_uses_history_and_dedupes(tmp_path):
    price = {"low": 100000}
    app, tg = make(lambda q: items(price["low"], 101000, 102000, title=q), tmp_path)
    app.store.watch_add("갤럭시 버즈3 프로")
    for i in range(6):
        app.store.add_price("watch:갤럭시 버즈3 프로", 100000, time.time() - i * 86400)
    assert app.check_watchlist() == 0       # 평소 가격
    price["low"] = 80000
    assert app.check_watchlist() == 1 and "최근 30일" in tg.sent[0]
    assert app.check_watchlist() == 0       # 같은 가격으로는 재알림 없음


def test_commands(tmp_path):
    app, tg = make(lambda q: [], tmp_path)
    tg.queue = [{"update_id": 5, "message": {"chat": {"id": 1}, "text": "/add 아이패드 에어 M3"}},
                {"update_id": 6, "message": {"chat": {"id": 999}, "text": "/add 남의것"}},
                {"update_id": 7, "message": {"chat": {"id": 1}, "text": "/check"}}]
    assert app.handle_commands() is True
    assert [r[0] for r in app.store.watch_list()] == ["아이패드 에어 M3"]
    assert app.handle_commands() is False   # offset 이 저장되어 다시 처리하지 않음


def test_real_feed_quirks():
    xml = """<?xml version="1.0" encoding="UTF-8" ?><rss><channel><item>
<title>[롯데온] 갤럭시 탭&amp;amp;커버 (9,490/무배)</title><link>http://x/9</link>
<description>a&nbsp;b &copy; c</description></item></channel></rss>""".encode()
    d = sources.parse_rss(xml, "뽐뿌")[0]
    assert (d.mall, d.name, d.price) == ("롯데온", "갤럭시 탭&커버", 9490)
