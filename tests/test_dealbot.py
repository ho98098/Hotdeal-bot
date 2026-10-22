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
    def send(self, t):
        self.sent.append(t)
        return len(self.sent)
    def edit(self, mid, t):
        self.sent[mid - 1] = t
        return True
    def set_commands(self, c): self.commands = c
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
    for i in range(5, -1, -1):              # 5일 전부터 같은 가격 -> 기록은 1건만
        app.store.add_price("watch:갤럭시 버즈3 프로", 100000, time.time() - i * 86400)
    assert len(app.store.price_series("watch:갤럭시 버즈3 프로")) == 1
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


def test_new_sources_and_enuri():
    import pathlib
    d = pathlib.Path(__file__).parent / "fixtures"
    cl = sources.parse_clien((d / "clien.html").read_text("utf-8"))
    assert len(cl) > 20 and cl[0].link.startswith("https://www.clien.net/service/board/jirum/")
    assert any("네이버 멤버쉽" in x.title for x in cl)
    eo = sources.parse_rss((d / "eomisae.xml").read_bytes(), "어미새")
    assert eo and eo[0].price == 43070
    en = market.parse_enuri((d / "enuri_m.html").read_text("utf-8"))
    assert en[0]["price"] == 217990 and all("중고" not in i["title"] for i in en)
    ex = market.relevant(market.parse_enuri((d / "enuri_pc.html").read_text("utf-8")), "현대 엑스티어")
    assert ex and "엑스티어" in ex[0]["title"]


def test_lookup_picks_cheapest_site(tmp_path):
    def search(q):
        return [{"title": q, "price": 220000, "overseas": 170000, "mall": "다나와", "link": "d"},
                {"title": q, "price": 217990, "overseas": 0, "mall": "에누리", "link": "e"}]
    app, tg = make(search, tmp_path)
    items = app.lookup("갤럭시 버즈3 프로")
    assert items[0]["mall"] == "에누리"
    rep = app.price_report("갤럭시 버즈3 프로")
    assert rep.index("[에누리]") < rep.index("[다나와]") and "해외구매 170,000원" in rep


@pytest.mark.parametrize("t,exp", [
    ("오즈랜드 두부과자 40g 12봉", {"g": 480, "ea": 12}),
    ("다향 훈제오리슬라이스 200g x 10", {"g": 2000, "ea": 10}),
    ("국내산 깻잎김치 500g", {"g": 500}),
    ("깨끗한나라 3겹 30m 30롤", {"m": 900, "ea": 30}),
    ("오리온 초코파이 96P 1872g(2박스)", {"g": 1872, "ea": 96}),
    ("코카콜라 제로 355ml 24캔", {"ml": 8520, "ea": 24}),
    ("엑스티어 알파 1.5L", {"ml": 1500}),
    ("TEAMGROUP DDR5 32GB (16GBx2)", {"ea": 2}),
    ("갤럭시 버즈3 프로 SM-R630N", {}),
    ("아이패드 프로11 m4 256GB", {}),
    ("네이버 멤버십 3개월 무료", {}),
])
def test_quantity(t, exp):
    assert market.quantity(t) == exp


def test_qty_ratio():
    assert market.qty_ratio("두부과자 40g 12봉", "두부과자 40g 5봉") == 2.4
    assert market.qty_ratio("깻잎김치 500g", "깻잎김치 1kg") == 0.5
    assert market.qty_ratio("갤럭시 버즈3 프로", "갤럭시 버즈3 프로 SM-R630N") is None


def test_boards_quantity_and_unmatched(tmp_path):
    rss = """<rss><channel>
<item><title>[G마켓] 두부과자 40g 12봉 (9,900원/무료)</title><link>http://x/a</link></item>
<item><title>[카톡선물하기] 갤럭시 기프티콘 이벤트 (1,360원/무료)</title><link>http://x/b</link></item>
</channel></rss>""".encode()
    def search(q):
        if "두부" in q:
            return [{"title": "두부과자 40g 5봉", "price": 6000, "overseas": 0, "mall": "다나와", "link": "d"}]
        return []
    cfg = {"categories": {"식품": ["과자"], "전자": ["갤럭시"]}, "sources": [{"name": "뽐뿌", "url": "u"}],
           "discount_threshold": 0.15, "request_delay_seconds": 0}
    tg = FakeTG()
    app = App(cfg, Store(str(tmp_path / "q.db")), tg, search_fn=search,
              fetch_fn=lambda s: sources.parse_rss(rss, s["name"]))
    assert app.check_boards() == 2
    # 5봉 6,000원 -> 12봉 환산 14,400원, 9,900원은 31% 저렴
    assert "31% 저렴" in tg.sent[0] and "14,400원" in tg.sent[0] and "2.4배" in tg.sent[0]
    assert "시세 비교 불가" in tg.sent[1]


def test_popular_real_pages(tmp_path):
    import pathlib
    d = pathlib.Path(__file__).parent / "fixtures"
    ru = sources.parse_ruliweb((d / "ruliweb_list.html").read_text("utf-8"))
    best = [x for x in ru if "멤버십 3개월" in x.title][0]
    assert (best.votes, best.comments) == (39, 23) and best.link.endswith("/read/108246")
    cl = sources.parse_clien((d / "clien.html").read_text("utf-8"))
    assert any(x.votes > 0 for x in cl) and any(x.comments > 0 for x in cl)
    cfg = {"popular": [{"name": "루리웹", "url": "u", "type": "ruliweb", "min_votes": 20}], "request_delay_seconds": 0}
    tg = FakeTG()
    pages = {"n": ru}
    app = App(cfg, Store(str(tmp_path / "p.db")), tg, search_fn=lambda q: [], fetch_fn=lambda s: pages["n"])
    assert app.check_popular() == 0                      # 처음엔 기존 인기글로 알림 폭탄 안 보냄
    new = sources.Deal("루리웹", "루리웹:999", "[쿠팡] 새 인기 특가", "새 인기 특가", "쿠팡", 0, "http://r/999", votes=25, comments=9)
    pages["n"] = ru + [new]
    assert app.check_popular() == 1 and "추천 25" in tg.sent[0]
    assert app.check_popular() == 0


def test_watch_alltime_low_and_history(tmp_path):
    price = {"v": 100000}
    app, tg = make(lambda q: items(price["v"], title=q), tmp_path)
    app.store.watch_add("갤럭시 버즈3 프로")
    for i, p in enumerate([100000, 99000, 98000]):
        app.store.add_price("watch:갤럭시 버즈3 프로", p, time.time() - (3 - i) * 86400)
    price["v"] = 96000                                    # 이전 최저 98,000원보다 2% 낮음
    assert app.check_watchlist() == 1 and "등록 후 최저가 갱신" in tg.sent[0]
    assert app.check_watchlist() == 0                     # 같은 가격 재알림 없음
    rep = app.history_report("버즈3")
    assert "지금 96,000원" in rep and "등록 후 최저 96,000원" in rep and "일별 최저가" in rep


def test_ruliweb_ended_and_title_ended():
    import pathlib
    ru = sources.parse_ruliweb((pathlib.Path(__file__).parent / "fixtures" / "ruliweb_list.html").read_text("utf-8"))
    ended = [d for d in ru if d.ended]
    assert ended and len(ended) < len(ru) / 2
    assert sources.is_ended("[종료] [쿠팡] 라면 40봉") and sources.is_ended("[쿠팡] 라면 (품절)")
    assert not sources.is_ended("[쿠팡] 종료 임박 라면")


def test_dedupe_block_ended(tmp_path):
    rss = lambda title, link: f"<rss><channel><item><title>{title}</title><link>{link}</link></item></channel></rss>".encode()
    pages = {
        "뽐뿌": rss("[G마켓] 삼성 갤럭시 버즈3 프로 (150,000원/무료)", "http://p/1"),
        "루리웹": rss("[지마켓] 갤럭시 버즈3 프로 150,000원", "http://r/1")
                 .replace(b"</channel>", rss("[쿠팡] 갤럭시 탭 렌탈 (9,900원)", "http://r/2")[14:-16] + b"</channel>"),
        "클리앙": rss("[종료] [쿠팡] 갤럭시 워치 (99,000원)", "http://c/1"),
    }
    cfg = {"categories": {"전자": ["갤럭시"]}, "request_delay_seconds": 0, "discount_threshold": 0.15,
           "sources": [{"name": n, "url": "u"} for n in pages]}
    tg = FakeTG()
    app = App(cfg, Store(str(tmp_path / "d.db")), tg,
              search_fn=lambda q: items(200000, 210000, title=q) if "버즈" in q else [],
              fetch_fn=lambda s: sources.parse_rss(pages[s["name"]], s["name"]))
    tg.queue = [{"update_id": 1, "message": {"chat": {"id": 1}, "text": "/block 렌탈"}}]
    app.handle_commands()
    assert app.check_boards() == 1                     # 버즈3 1건만 (중복·렌탈·종료 제외)
    alert = [t for t in tg.sent if "버즈3" in t]
    assert len(alert) == 1 and "같은 특가: 루리웹" in alert[0]


def test_add_shows_current_price_and_menu(tmp_path):
    app, tg = make(lambda q: items(217990, title="삼성전자 " + q + " SM-R630N"), tmp_path)
    tg.queue = [{"update_id": 1, "message": {"chat": {"id": 1}, "text": "/add 갤럭시 버즈3 프로"}}]
    app.handle_commands()
    assert "현재 최저가 217,990원" in tg.sent[0]
    assert len(app.store.price_series("watch:갤럭시 버즈3 프로")) == 1
    app.serve(hours=0.00001)
    assert ("block", "제외 키워드 추가 (예: /block 렌탈)") in tg.commands



@pytest.mark.parametrize("t,exp", [
    ("[지마켓] 파이어엠블렘 만자천홍 98000+배송무료", 98000),
    ("[쿠팡] 라면 40봉 12,900/무배", 12900),
    ("[11번가] 생수 2L 24병 15900 무료배송", 15900),
    ("[Amazon.jp] DDR5 32GB (jpy 64980 / 무배,직배)", 0),
    ("[이베이] 노트북 (600$/배대지)", 0),
    ("DDR5 6000MHz 32GB", 0),
])
def test_price_without_won(t, exp):
    assert sources.parse_price(t) == exp


def test_dedupe_cheaper_realerts(tmp_path):
    app, tg = make(lambda q: [], tmp_path)
    assert app.notify("A", "삼성 갤럭시 버즈3 프로", 150000, "뽐뿌")
    assert not app.notify("B", "갤럭시 버즈3 프로", 152000, "루리웹")   # 3% 이내 비쌈 -> 묶음
    assert app.notify("C", "갤럭시 버즈3 프로", 149000, "클리앙")       # 더 쌈 -> 새 알림
    assert not app.notify("D", "갤럭시 버즈3 프로", 149000, "뽐뿌")     # 새 최저와 같음 -> 묶음
    assert tg.sent[0].startswith("A") and "같은 특가: 루리웹" in tg.sent[0] and tg.sent[1].startswith("C")


def test_change_only_records_and_compact(tmp_path):
    import sqlite3
    path = str(tmp_path / "c.db")
    st = Store(path)
    for i, p in enumerate([100, 100, 100, 90, 90, 100]):   # 예전 방식으로 쌓인 기록 흉내
        st.db.execute("INSERT INTO prices VALUES(?,?,?)", ("k", p, 1000 + i))
    st.db.commit()
    st2 = Store(path)                                       # 다시 열면 정리
    assert [p for _, p in st2.price_series("k")] == [100, 90, 100]
    assert st2.add_price("k", 100) is False and st2.add_price("k", 95) is True


def test_time_weighted_median(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    now = time.time()
    st.add_price("k", 100000, now - 10 * 86400)   # 9일 동안 100,000
    st.add_price("k", 50000, now - 1 * 86400)     # 하루 동안 50,000
    assert st.history_median("k") == 100000        # 기록 개수가 아니라 유지된 시간 기준


def test_stall_notice(tmp_path):
    app, tg = make(lambda q: [], tmp_path)
    app.store.set_meta("heartbeat", time.time() - 3 * 3600)
    app.serve(hours=0.00001)
    assert "180분 동안 멈춰" in tg.sent[0]
    tg.sent.clear()
    app.serve(hours=0.00001)                       # 바로 다시 시작하면 알림 없음
    assert not any("멈춰" in t for t in tg.sent)
