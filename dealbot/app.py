"""한 번의 확인 주기(run_once)와 반복 실행."""
import json
import logging
import time

from . import market, sources

log = logging.getLogger("dealbot")
won = lambda n: f"{n:,}원"

COMMANDS = [
    ("add", "관심 제품 등록 (예: /add 갤럭시 버즈3 프로)"),
    ("remove", "관심 제품 삭제"),
    ("list", "관심 제품 목록"),
    ("history", "관심 제품 가격 추이"),
    ("price", "지금 다나와·에누리 최저가 조회"),
    ("block", "제외 키워드 추가 (예: /block 렌탈)"),
    ("unblock", "제외 키워드 삭제"),
    ("blocklist", "제외 키워드 목록"),
    ("category", "감시 카테고리와 키워드 보기"),
    ("catadd", "카테고리 키워드 추가 (예: /catadd 식품 라면)"),
    ("catdel", "카테고리 키워드 삭제"),
    ("status", "봇 상태와 최근 확인 결과"),
    ("check", "지금 바로 전체 확인"),
    ("help", "명령어 목록"),
]

HELP = (
    "명령어\n"
    "/add 제품명 - 관심 제품 등록\n"
    "/remove 제품명 - 관심 제품 삭제\n"
    "/list - 관심 제품 목록\n"
    "/history 제품명 - 관심 제품 가격 추이\n"
    "/block 단어 - 이 단어가 든 글은 알림 안 함\n"
    "/unblock 단어 · /blocklist - 제외 키워드 관리\n"
    "/price 제품명 - 지금 다나와·에누리 시세 조회\n"
    "/status - 봇 상태와 최근 확인 결과\n"
    "/category - 감시 카테고리와 키워드 보기\n"
    "/catadd 카테고리 키워드 - 키워드 추가\n"
    "/catdel 카테고리 키워드 - 키워드 삭제\n"
    "/check - 지금 바로 전체 확인"
)


class App:
    def __init__(self, cfg, store, tg, search_fn=None, fetch_fn=None):
        self.cfg, self.store, self.tg = cfg, store, tg
        self.search = search_fn or market.search_all
        self.lookup_ok = self.lookup_fail = 0
        self.fetch = fetch_fn or sources.fetch_source
        self.threshold = float(cfg.get("discount_threshold", 0.15))
        self.delay = float(cfg.get("request_delay_seconds", 2))

    # ---------- 텔레그램 명령 ----------
    def handle_commands(self, wait=0):
        """새 명령을 처리. /check 가 있었으면 True."""
        offset = int(self.store.get_meta("tg_offset", 0))
        want_check = False
        for u in self.tg.updates(offset, wait) if wait else self.tg.updates(offset):
            self.store.set_meta("tg_offset", u["update_id"] + 1)
            msg = u.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != self.tg.chat_id:
                continue  # 내 채팅이 아니면 무시
            text = (msg.get("text") or "").strip()
            cmd, _, arg = text.partition(" ")
            cmd, arg = cmd.split("@")[0].lower(), arg.strip()
            if cmd == "/add" and arg:
                self.store.watch_add(arg)
                self.tg.send(self.add_report(arg))
            elif cmd == "/remove" and arg:
                ok = self.store.watch_remove(arg)
                self.tg.send(f"삭제했어요: {arg}" if ok else f"목록에 없어요: {arg}")
            elif cmd == "/list":
                rows = self.store.watch_list()
                self.tg.send("관심 제품\n" + "\n".join(
                    f"- {r[0]}" + (f" (알림 보낸 가격 {won(r[1])})" if r[1] else "") for r in rows)
                    if rows else "등록된 관심 제품이 없어요. /add 제품명 으로 등록하세요.")
            elif cmd == "/block" and arg:
                bl = self.blocked()
                if arg not in bl:
                    bl.append(arg)
                self.store.set_meta("blocked", json.dumps(bl, ensure_ascii=False))
                self.tg.send(f"'{arg}' 이 들어간 글은 앞으로 알리지 않아요.\n제외 키워드: {', '.join(bl)}")
            elif cmd == "/unblock" and arg:
                bl = self.blocked()
                ok = arg in bl
                if ok:
                    bl.remove(arg)
                self.store.set_meta("blocked", json.dumps(bl, ensure_ascii=False))
                self.tg.send(f"'{arg}' 제외를 풀었어요." if ok else f"제외 목록에 '{arg}' 가 없어요.")
            elif cmd == "/blocklist":
                bl = self.blocked()
                self.tg.send("제외 키워드: " + ", ".join(bl) if bl else "제외 키워드가 없어요. /block 단어 로 추가하세요.")
            elif cmd == "/history":
                self.tg.send(self.history_report(arg))
            elif cmd == "/price" and arg:
                self.tg.send(self.price_report(arg))
            elif cmd in ("/category", "/categories", "/카테고리"):
                cats = self.categories()
                self.tg.send("\n\n".join(f"[{c}]\n" + ", ".join(k) for c, k in cats.items()) or "카테고리가 없어요.")
            elif cmd in ("/catadd", "/catdel") and len(arg.split()) >= 2:
                cat, kw = arg.split(None, 1)
                cats = self.categories()
                kws = cats.setdefault(cat, [])
                if cmd == "/catadd":
                    if kw not in kws:
                        kws.append(kw)
                    msg = f"[{cat}] 에 '{kw}' 추가했어요."
                else:
                    msg = f"[{cat}] 에서 '{kw}' 삭제했어요." if kw in kws else f"[{cat}] 에 '{kw}' 가 없어요."
                    if kw in kws:
                        kws.remove(kw)
                    if not kws:
                        cats.pop(cat, None)
                self.store.set_meta("categories", json.dumps(cats, ensure_ascii=False))
                self.tg.send(msg)
            elif cmd == "/status":
                self.tg.send(self.status_report())
            elif cmd == "/check":
                want_check = True
            elif cmd in ("/start", "/help"):
                self.tg.send(HELP)
        return want_check

    def tick(self):
        """오래 걸리는 확인 도중에도 명령에 바로 답하도록 틈틈이 호출."""
        if getattr(self, "_in_tick", False) or not getattr(self, "serving", False):
            return
        self._in_tick = True
        try:
            if self.handle_commands():
                self._force = True
        except Exception:
            log.exception("명령 처리 오류")
        finally:
            self._in_tick = False
        self.store.set_meta("heartbeat", time.time())

    def lookup(self, query):
        self.tick()
        query = market.clean_query(query) or query
        try:
            tops, rest = market.best_per_mall(self.search(query), query)
            self.lookup_ok += 1
            return tops + rest  # 첫 항목 = 사이트별 대표 중 가장 싼 것
        except Exception as e:
            self.lookup_fail += 1
            log.warning("시세 조회 실패 %s: %s", query, e)
            return None
        finally:
            time.sleep(self.delay)

    def price_report(self, query):
        items = self.lookup(query)
        if items is None:
            return f"'{query}' 시세 조회에 실패했어요. 잠시 뒤 다시 시도해 주세요."
        if not items:
            return f"'{query}' 와 맞는 상품을 다나와·에누리에서 찾지 못했어요. 모델명을 더 정확히 적어 주세요."
        malls = {}
        for it in items:
            malls.setdefault(it["mall"], it)
        lines = [f"'{query}' 현재 최저가"]
        for m, it in sorted(malls.items(), key=lambda x: x[1]["price"]):
            lines += ["", f"[{m}] {won(it['price'])}", it["title"]]
            if it.get("overseas"):
                lines.append(f"해외구매 {won(it['overseas'])}")
            lines.append(it["link"])
        lines += self.shop_lines(query)
        lines += ["", "(국내 정품 기준, 카드할인·쿠폰 적용 전)"]
        return "\n".join(lines)


    def _find_watch(self, arg):
        names = [r[0] for r in self.store.watch_list()]
        if not arg and len(names) == 1:
            return names[0]
        if arg in names:
            return arg
        hits = [n for n in names if arg and (arg in n or n in arg)]
        return hits[0] if len(hits) == 1 else None

    def history_report(self, arg):
        name = self._find_watch(arg)
        if not name:
            names = [r[0] for r in self.store.watch_list()]
            return "관심 제품 이름을 적어 주세요.\n" + "\n".join(f"- {n}" for n in names) if names \
                else "등록된 관심 제품이 없어요. /add 제품명 으로 등록하세요."
        key = f"watch:{name}"
        rows = self.store.price_series(key)
        if not rows:
            return f"'{name}' 은 아직 가격 기록이 없어요. 다음 확인 뒤에 다시 보세요."
        kst = lambda ts: time.gmtime(ts + 9 * 3600)
        now = time.time()
        cur = rows[-1][1]
        lo_ts, lo = min(rows, key=lambda r: (r[1], -r[0]))
        lines = [f"[{name}] 가격 추이", f"지금 {won(cur)} ({time.strftime('%m-%d %H:%M', kst(rows[-1][0]))}부터)",
                 f"등록 후 최저 {won(lo)} ({time.strftime('%m-%d', kst(lo_ts))}) · 기록 {(now - rows[0][0]) / 86400:.0f}일 · 가격 변동 {len(rows) - 1}번"]
        for days in (7, 30):
            ps = [p for _, _, p in self.store.price_periods(key, now - days * 86400, now)]
            if ps:
                lines.append(f"최근 {days}일 최저 {won(min(ps))} / 최고 {won(max(ps))}")
        daily = []
        for k in range(6, -1, -1):  # 최근 7일, 그날 유지된 가격 중 최저
            day0 = (int((now + 9 * 3600) // 86400) - k) * 86400 - 9 * 3600
            ps = [p for s0, e0, p in self.store.price_periods(key) if s0 < day0 + 86400 and e0 > day0]
            if ps:
                daily.append((time.strftime("%m-%d", kst(day0)), min(ps)))
        if len(daily) > 1:
            lo7, hi7 = min(v for _, v in daily), max(v for _, v in daily)
            lines += ["", "일별 최저가"]
            for d, v in daily:
                bar = "▇" * (1 + int(7 * (v - lo7) / (hi7 - lo7))) if hi7 > lo7 else "▇"
                lines.append(f"{d} {bar} {won(v)}")
        return "\n".join(lines)

    def shop_lines(self, query):
        """쿠팡·알리 API 키가 있으면 /price 에 함께 표시."""
        from . import shops
        out = []
        q = market.clean_query(query) or query
        for label, fn, ok in (("쿠팡", shops.coupang_search, shops.coupang_keys()),
                              ("알리 (해외배송)", shops.ali_search, shops.ali_keys())):
            if not ok:
                continue
            try:
                found = market.relevant(fn(q), q)
            except Exception as e:
                log.warning("%s 검색 실패: %s", label, e)
                out += ["", f"[{label}] 조회 실패"]
                continue
            if found:
                top = min(found[:5], key=lambda x: x["price"])
                out += ["", f"[{label}] {won(top['price'])}", top["title"], top["link"]]
        return out

    def add_report(self, name):
        """관심 제품 등록 직후 지금 찾은 상품과 가격을 보여주고 첫 기록으로 저장."""
        items = self.lookup(name)
        if items is None:
            return f"등록했어요: {name}\n지금은 시세 조회에 실패해서, 다음 확인 때 다시 찾아볼게요."
        if not items:
            return (f"등록했어요: {name}\n다만 다나와·에누리에서 맞는 상품을 못 찾았어요. "
                    f"모델명을 더 정확히 적어 다시 등록해 주세요. (/remove {name})")
        top = items[0]
        self.store.add_price(f"watch:{name}", top["price"])
        return (f"등록했어요: {name}\n지금 이 상품으로 비교합니다\n"
                f"[{top['mall']}] {top['title']}\n현재 최저가 {won(top['price'])}\n{top['link']}\n"
                f"엉뚱한 상품이면 /remove {name} 후 모델명을 넣어 다시 등록하세요.")

    def blocked(self):
        return json.loads(self.store.get_meta("blocked") or "[]")

    def is_blocked(self, title):
        low = title.lower()
        return any(w.lower() in low for w in self.blocked())

    # ---------- 같은 특가 묶기 ----------
    def notify(self, text, name, price, source):
        """최근 24시간 안에 같은 특가(이름이 비슷하고 가격이 같음)를 보냈으면 새로 보내지 않고
        기존 메시지에 출처만 덧붙임. 새로 보냈으면 True."""
        recent = [r for r in json.loads(self.store.get_meta("recent_alerts") or "[]") if time.time() - r["ts"] < 86400]
        toks = market._tokens(market.clean_query(name) or name)
        for r in recent:
            # 가격이 같거나 3% 이내로 비싸면 같은 특가 (더 싸면 새로 알림)
            same_price = (not price and not r["price"]) or (price and r["price"] and r["price"] <= price <= 1.03 * r["price"])
            overlap = len(toks & set(r["toks"])) / max(1, min(len(toks), len(r["toks"])))
            cheaper = price and r["price"] and price < r["price"]
            if overlap >= 0.7 and cheaper:
                r["toks"] = []          # 더 싼 새 특가로 대체: 이전 기록은 비교 대상에서 제외
                continue
            if same_price and overlap >= 0.7:
                if source not in r["sources"]:
                    r["sources"].append(source)
                    if r.get("msg_id"):
                        self.tg.edit(r["msg_id"], r["text"] + "\n(같은 특가: " + ", ".join(r["sources"][1:]) + ")")
                self.store.set_meta("recent_alerts", json.dumps(recent, ensure_ascii=False))
                return False
        msg_id = self.tg.send(text)
        recent.append({"ts": time.time(), "toks": sorted(toks), "price": price, "msg_id": msg_id,
                       "text": text, "sources": [source]})
        self.store.set_meta("recent_alerts", json.dumps(recent[-200:], ensure_ascii=False))
        return True

    def status_report(self):
        g = lambda k: self.store.get_meta(k, "-")
        hb = self.store.get_meta("heartbeat")
        alive = f"{int(time.time() - float(hb))}초 전" if hb else "-"
        return (f"봇 응답 확인: {alive}\n마지막 특가 확인: {g('last_run')}\n"
                f"게시판 새 글 {g('last_new')}개 중 카테고리 해당 {g('last_matched')}개, 시세 비교 {g('last_compared')}개\n"
                f"오늘 보낸 특가 알림: {g('alerts_' + time.strftime('%Y-%m-%d'))}건\n"
                f"관심 제품 {len(self.store.watch_list())}개, 확인 주기 {self.cfg.get('interval_minutes', 5)}분")

    def categories(self):
        """텔레그램으로 바꾼 카테고리가 있으면 그것을, 없으면 config.yaml 값을 사용."""
        saved = self.store.get_meta("categories")
        return json.loads(saved) if saved else {k: list(v) for k, v in self.cfg.get("categories", {}).items()}

    # ---------- 핫딜 게시판 ----------
    def check_boards(self):
        cats = self.categories()
        min_price = int(self.cfg.get("min_price", 0))
        sent = new = matched = compared = 0
        for src in self.cfg.get("sources", []):
            every = float(src.get("interval_minutes", 0)) * 60   # API 호출 제한이 있는 곳은 더 드물게
            last_key = "src_last:" + src["name"]
            if every and time.time() - float(self.store.get_meta(last_key, 0)) < every:
                continue
            if every:
                self.store.set_meta(last_key, time.time())
            try:
                deals = self.fetch(src)
            except Exception as e:
                log.warning("수집 실패 %s: %s", src.get("name"), e)
                continue
            for d in deals:
                if self.store.is_seen(d.id):
                    continue
                self.store.mark_seen(d.id)
                new += 1
                if d.ended or self.is_blocked(d.title):
                    continue
                d.category = sources.match_category(d.title, cats)
                if not d.category or (d.price and d.price < min_price):
                    continue
                matched += 1
                items = self.lookup(d.name) if d.price else None
                ref, top = market.market_price(items or [])
                if not ref:
                    # 가격비교 사이트에 없는 특가(기프티콘·앱 쿠폰 등)도 카테고리에 맞으면 알림
                    if self.cfg.get("notify_unmatched", True):
                        sent += self.notify(
                            f"[{d.category}] 새 핫딜 (시세 비교 불가)\n{d.name}\n"
                            + (f"특가 {won(d.price)}\n" if d.price else "")
                            + f"{d.mall or '-'} · {d.source}\n{d.link}", d.name, d.price, d.source)
                    continue
                compared += 1
                # 수량이 다르면 특가 수량 기준으로 시세 환산 (예: 12봉 vs 5봉)
                qnote = ""
                r = market.qty_ratio(d.name, top["title"]) \
                    if d.category in self.cfg.get("unit_compare_categories", ["식품", "생활용품"]) else None
                if r and abs(r - 1) > 0.01:
                    ref = int(ref * r)
                    if top.get("overseas"):
                        top = dict(top, overseas=int(top["overseas"] * r))
                    qnote = f"\n(수량 환산: 비교 상품의 {r:g}배 기준)"
                # 해외직구 특가는 다나와 해외구매 최저가와 비교
                ovs_deal = d.mall == "알리" or any(k in d.title for k in ("해외", "직구", "관부가세", "관세"))
                basis = "국내 정품"
                if ovs_deal and top.get("overseas"):
                    ref, basis = top["overseas"], "해외구매"
                off = market.discount(d.price, ref)
                # 70% 넘게 싸면 다른 상품(부속품 등)과 비교됐을 가능성이 커서 제외
                if self.threshold <= off < 0.7:
                    sent += self.notify(
                        f"[{d.category}] 시세보다 {off:.0%} 저렴\n{d.name}\n"
                        f"특가 {won(d.price)} / {top['mall']} {basis} 최저 {won(ref)}\n비교 상품: {top['title']}{qnote}\n"
                        f"{d.mall or '-'} · {d.source}\n{d.link}", d.name, d.price, d.source)
            time.sleep(self.delay)
        if new:  # 첫 실행 등으로 새 글이 없으면 직전 통계 유지
            for k, v in (("last_new", new), ("last_matched", matched), ("last_compared", compared)):
                self.store.set_meta(k, v)
        return sent

    # ---------- 인기 핫딜 ----------
    def check_popular(self):
        """추천이 많이 붙은 글은 카테고리·시세와 상관없이 알림 (루리웹·클리앙 목록 화면)."""
        sent = 0
        first = self.store.get_meta("popular_init") is None
        for src in self.cfg.get("popular", []):
            try:
                deals = self.fetch(src)
            except Exception as e:
                log.warning("인기글 수집 실패 %s: %s", src.get("name"), e)
                continue
            for d in deals:
                key = "pop:" + d.id
                if d.votes < int(src.get("min_votes", 20)) or self.store.is_seen(key):
                    continue
                self.store.mark_seen(key)
                if first or d.ended or self.is_blocked(d.title):
                    continue  # 처음 켤 때 기존 인기글, 종료된 특가, 제외 키워드는 건너뜀
                sent += self.notify(f"[인기 핫딜] 추천 {d.votes} · 댓글 {d.comments}\n{d.title}\n{d.source}\n{d.link}",
                                    d.name, d.price, d.source)
            time.sleep(self.delay)
        self.store.set_meta("popular_init", 1)
        return sent

    # ---------- 관심 제품 ----------
    def check_watchlist(self):
        sent = 0
        for name, last_alert in self.store.watch_list():
            now_med, low = market.market_price(self.lookup(name) or [])
            if not low:
                continue
            key = f"watch:{name}"
            hist = self.store.history_median(key)      # 내가 쌓은 최저가 기록의 30일 중앙값
            past = self.store.price_series(key)
            self.store.add_price(key, low["price"])
            ref = hist or now_med                       # 기록이 부족한 초반엔 현재 판매가 중앙값
            off = market.discount(low["price"], ref)
            # 등록 후 최저가 갱신: 하루 이상 기록이 있고, 이전 최저보다 1% 이상 낮을 때
            prev_min = min(p for _, p in past) if past else None
            atl = (prev_min and time.time() - past[0][0] >= 86400 and low["price"] <= prev_min * 0.99
                   and str(low["price"]) != self.store.get_meta(f"atl:{name}"))
            cheap = self.threshold <= off < 0.7 and (last_alert is None or low["price"] < last_alert)
            if atl or cheap:
                head = []
                if atl:
                    head.append(f"등록 후 최저가 갱신 (이전 최저 {won(prev_min)})")
                    self.store.set_meta(f"atl:{name}", low["price"])
                if cheap:
                    basis = "최근 30일 시세" if hist else "현재 최저가"
                    head.append(f"{basis}보다 {off:.0%} 저렴")
                self.tg.send(
                    f"[관심 제품] " + " · ".join(head) + f"\n{low['title']}\n"
                    f"지금 {won(low['price'])} / 기준 {won(ref)}\n{low['mall']}\n{low['link']}"
                )
                if cheap:
                    self.store.watch_set_alert(name, low["price"])
                sent += 1
            elif last_alert is not None and off < self.threshold:
                self.store.watch_set_alert(name, None)  # 가격이 돌아오면 다음 하락 때 다시 알림
        return sent

    def run_once(self):
        n = self.check_boards() + self.check_popular() + self.check_watchlist()
        # 한국 시간으로 기록
        self.store.set_meta("last_run", time.strftime("%m-%d %H:%M", time.gmtime(time.time() + 9 * 3600)))
        if n:
            k = "alerts_" + time.strftime("%Y-%m-%d")
            self.store.set_meta(k, int(self.store.get_meta(k, 0)) + n)
        # 시세 조회가 전부 실패하면 (사이트 차단 등) 하루 한 번 알려줌
        if self.lookup_fail and not self.lookup_ok:
            today = time.strftime("%Y-%m-%d")
            if self.store.get_meta("fail_notice") != today:
                self.store.set_meta("fail_notice", today)
                self.tg.send(f"주의: 이번 확인에서 시세 조회가 {self.lookup_fail}번 모두 실패했어요.")
        return n

    def serve(self, hours=5.7, save=None, save_every=600):
        """GitHub Actions 상시 실행: 명령은 즉시 응답, 특가는 interval 마다 확인, 정해진 시간 뒤 종료."""
        interval = float(self.cfg.get("interval_minutes", 5)) * 60
        end = time.time() + hours * 3600
        next_run = last_save = 0
        self.serving, self._force = True, False
        hb = self.store.get_meta("heartbeat")
        gap = time.time() - float(hb) if hb else 0
        if gap > float(self.cfg.get("stall_minutes", 40)) * 60:
            kst = time.strftime("%m-%d %H:%M", time.gmtime(float(hb) + 9 * 3600))
            self.tg.send(f"봇이 {gap / 60:.0f}분 동안 멈춰 있다가 다시 시작했어요. (마지막 응답 {kst})\n"
                         f"그 사이 올라온 글은 지금부터 확인합니다.")
        self.store.set_meta("heartbeat", time.time())
        try:
            self.tg.set_commands(COMMANDS)
        except Exception:
            log.warning("명령어 메뉴 등록 실패")
        try:
            self._serve_loop(end, interval, save, save_every)
        finally:
            if save:
                save()

    def _serve_loop(self, end, interval, save, save_every):
        next_run = last_save = 0
        while time.time() < end:
            try:
                self.store.set_meta("heartbeat", time.time())
                force = self.handle_commands(wait=25) or self._force
                self._force = False
                if force or time.time() >= next_run:
                    n = self.run_once()
                    log.info("확인 완료, 알림 %d건", n)
                    if force:
                        self.tg.send(f"확인 완료: 알림 {n}건")
                    next_run = time.time() + interval
            except Exception:
                log.exception("실행 중 오류")
                time.sleep(10)
            if save and time.time() - last_save > save_every:
                try:
                    save()
                except Exception:
                    log.exception("저장 오류")
                last_save = time.time()

    def run_forever(self):
        interval = float(self.cfg.get("interval_minutes", 10)) * 60
        next_run = 0
        while True:
            try:
                force = self.handle_commands()
                if force or time.time() >= next_run:
                    n = self.run_once()
                    log.info("확인 완료, 알림 %d건", n)
                    if force:
                        self.tg.send(f"확인 완료: 알림 {n}건")
                    next_run = time.time() + interval
            except Exception:
                log.exception("주기 실행 중 오류")
            time.sleep(5)
