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
    def updates(self, offset=0, wait=0): return [u for u in self.queue if u["update_id"] >= offset]


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


def test_real_danawa_pages():
    import pathlib
    d = pathlib.Path(__file__).parent / "fixtures"
    new = market.relevant(market.parse_danawa((d / "danawa_new.html").read_text("utf-8")), "갤럭시 버즈3 프로")
    assert (new[0]["price"], new[0]["overseas"], "SM-R630N" in new[0]["title"]) == (219530, 170465, True)
    q = market.clean_query("삼성 갤럭시 버즈4 프로 SM-R640 블루투스 무선 이어폰 (당일항공발송 관부가세포함)")
    old = market.relevant(market.parse_danawa((d / "danawa_old.html").read_text("utf-8")), q)
    assert (old[0]["price"], old[0]["overseas"]) == (309860, 209200) and "SM-R640" in old[0]["title"]


DANAWA = """<ul><li class="prod_item prod_layer" id="productItem1">
<p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=1">삼성전자 갤럭시 버즈3 프로 SM-R630N</a></p>
<div class="prod_pricelist"><ul><li><p class="price_sect"><a><strong>217,980</strong>원</a></p></li></ul></div></li>
<li class="prod_item" id="adPointItem"><p class="prod_name"><a href="x">광고 상품</a></p><p class="price_sect"><strong>1,000</strong></p></li>
<li class="prod_item" id="productItem2"><p class="prod_name"><a href="y">삼성전자 갤럭시 버즈3 프로 이어버드 단품</a></p>
<p class="price_sect"><span>중고</span><strong>59,900</strong></p></li></ul>"""


def test_parse_danawa_and_filter():
    its = market.parse_danawa(DANAWA)
    assert [i["price"] for i in its] == [217980]   # 광고 제외, 중고 가격 제외
    its2 = [{"title": "삼성전자 갤럭시 버즈3 프로 이어버드 단품", "price": 59900, "mall": "", "link": ""}]
    assert market.relevant(its2, "갤럭시 버즈3 프로") == []


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


def test_price_command_and_fail_notice(tmp_path):
    app, tg = make(lambda q: items(200000, title=q), tmp_path)
    tg.queue = [{"update_id": 1, "message": {"chat": {"id": 1}, "text": "/price 갤럭시 버즈3 프로"}}]
    app.handle_commands()
    assert "200,000원" in tg.sent[0]
    tg.queue = [{"update_id": 2, "message": {"chat": {"id": 1}, "text": "/status"}}]
    app.handle_commands()
    assert "마지막 특가 확인" in tg.sent[-1]
    def boom(q): raise RuntimeError("blocked")
    app2, tg2 = make(boom, tmp_path / "..")
    app2.store.watch_add("갤럭시 버즈3 프로")
    app2.run_once(); app2.run_once()
    assert sum("실패" in t for t in tg2.sent) == 1


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


def test_serve_loop_saves_and_stops(tmp_path):
    app, tg = make(lambda q: [], tmp_path)
    saves = []
    app.serve(hours=0.0001, save=lambda: saves.append(1), save_every=0)
    assert saves  # 끝날 때 반드시 저장


def test_category_commands(tmp_path):
    app, tg = make(lambda q: [], tmp_path)
    tg.queue = [{"update_id": i, "message": {"chat": {"id": 1}, "text": t}} for i, t in
                enumerate(["/catadd 생활용품 세제", "/catdel 전자제품 갤럭시", "/category"])]
    app.handle_commands()
    assert app.categories() == {"생활용품": ["세제"]}   # 전자제품은 키워드가 비어 삭제됨
    assert "[생활용품]" in tg.sent[-1]
