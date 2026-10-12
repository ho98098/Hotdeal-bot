"""한 번의 확인 주기(run_once)와 반복 실행."""
import logging
import time

from . import market, sources

log = logging.getLogger("dealbot")
won = lambda n: f"{n:,}원"

HELP = (
    "명령어\n"
    "/add 제품명 - 관심 제품 등록\n"
    "/remove 제품명 - 관심 제품 삭제\n"
    "/list - 관심 제품 목록\n"
    "/price 제품명 - 지금 다나와 시세 조회\n"
    "/status - 봇 상태와 최근 확인 결과\n"
    "/check - 지금 바로 전체 확인"
)


class App:
    def __init__(self, cfg, store, tg, search_fn=None, fetch_fn=None):
        self.cfg, self.store, self.tg = cfg, store, tg
        self.search = search_fn or market.search
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
                self.tg.send(f"등록했어요: {arg}\n다음 확인부터 시세를 비교합니다.")
            elif cmd == "/remove" and arg:
                ok = self.store.watch_remove(arg)
                self.tg.send(f"삭제했어요: {arg}" if ok else f"목록에 없어요: {arg}")
            elif cmd == "/list":
                rows = self.store.watch_list()
                self.tg.send("관심 제품\n" + "\n".join(f"- {r[0]}" for r in rows) if rows else "등록된 관심 제품이 없어요.")
            elif cmd == "/price" and arg:
                self.tg.send(self.price_report(arg))
            elif cmd == "/status":
                self.tg.send(self.status_report())
            elif cmd == "/check":
                want_check = True
            elif cmd in ("/start", "/help"):
                self.tg.send(HELP)
        return want_check

    def lookup(self, query):
        query = market.clean_query(query) or query
        try:
            items = market.relevant(self.search(query), query)
            self.lookup_ok += 1
            return items
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
            return f"'{query}' 와 맞는 상품을 다나와에서 찾지 못했어요. 모델명을 더 정확히 적어 주세요."
        top = items[0]
        lines = [f"[다나와] {top['title']}", f"국내 정품 최저가: {won(top['price'])}"]
        if top.get("overseas"):
            lines.append(f"해외구매 최저가: {won(top['overseas'])}")
        lines.append("(카드할인·쿠폰 적용 전 가격)")
        others = [f"- {it['title']}: {won(it['price'])}" for it in items[1:3]]
        if others:
            lines += ["", "비슷한 상품"] + others
        return "\n".join(lines + [top["link"]])

    def status_report(self):
        g = lambda k: self.store.get_meta(k, "-")
        return (f"마지막 확인: {g('last_run')}\n"
                f"게시판 새 글 {g('last_new')}개 중 카테고리 해당 {g('last_matched')}개, 시세 비교 {g('last_compared')}개\n"
                f"오늘 보낸 특가 알림: {g('alerts_' + time.strftime('%Y-%m-%d'))}건\n"
                f"관심 제품 {len(self.store.watch_list())}개, 확인 주기 {self.cfg.get('interval_minutes', 5)}분")

    # ---------- 핫딜 게시판 ----------
    def check_boards(self):
        cats = self.cfg.get("categories", {})
        min_price = int(self.cfg.get("min_price", 0))
        sent = new = matched = compared = 0
        for src in self.cfg.get("sources", []):
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
                d.category = sources.match_category(d.title, cats)
                if not d.category or d.price < max(min_price, 1):
                    continue
                matched += 1
                items = self.lookup(d.name)
                ref, top = market.market_price(items or [])
                if not ref:
                    continue
                compared += 1
                # 해외직구 특가는 다나와 해외구매 최저가와 비교
                ovs_deal = any(k in d.title for k in ("해외", "직구", "관부가세", "관세"))
                basis = "국내 정품"
                if ovs_deal and top.get("overseas"):
                    ref, basis = top["overseas"], "해외구매"
                off = market.discount(d.price, ref)
                # 70% 넘게 싸면 다른 상품(부속품 등)과 비교됐을 가능성이 커서 제외
                if self.threshold <= off < 0.7:
                    self.tg.send(
                        f"[{d.category}] 시세보다 {off:.0%} 저렴\n{d.name}\n"
                        f"특가 {won(d.price)} / 다나와 {basis} 최저 {won(ref)}\n비교 상품: {top['title']}\n"
                        f"{d.mall or '-'} · {d.source}\n{d.link}"
                    )
                    sent += 1
            time.sleep(self.delay)
        if new:  # 첫 실행 등으로 새 글이 없으면 직전 통계 유지
            for k, v in (("last_new", new), ("last_matched", matched), ("last_compared", compared)):
                self.store.set_meta(k, v)
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
            self.store.add_price(key, low["price"])
            ref = hist or now_med                       # 기록이 부족한 초반엔 현재 판매가 중앙값
            off = market.discount(low["price"], ref)
            if self.threshold <= off < 0.7 and (last_alert is None or low["price"] < last_alert):
                basis = "최근 30일 시세" if hist else "현재 다나와 최저가"
                self.tg.send(
                    f"[관심 제품] {basis}보다 {off:.0%} 저렴\n{low['title']}\n"
                    f"지금 {won(low['price'])} / 기준 {won(ref)}\n{low['mall']}\n{low['link']}"
                )
                self.store.watch_set_alert(name, low["price"])
                sent += 1
            elif last_alert is not None and off < self.threshold:
                self.store.watch_set_alert(name, None)  # 가격이 돌아오면 다음 하락 때 다시 알림
        return sent

    def run_once(self):
        n = self.check_boards() + self.check_watchlist()
        self.store.set_meta("last_run", time.strftime("%m-%d %H:%M", time.gmtime(time.time() + 9 * 3600))  # 한국 시간)
        if n:
            k = "alerts_" + time.strftime("%Y-%m-%d")
            self.store.set_meta(k, int(self.store.get_meta(k, 0)) + n)
        # 시세 조회가 전부 실패하면 (사이트 차단 등) 하루 한 번 알려줌
        if self.lookup_fail and not self.lookup_ok:
            today = time.strftime("%Y-%m-%d")
            if self.store.get_meta("fail_notice") != today:
                self.store.set_meta("fail_notice", today)
                self.tg.send(f"주의: 이번 확인에서 다나와 시세 조회가 {self.lookup_fail}번 모두 실패했어요.")
        return n

    def serve(self, hours=5.7, save=None, save_every=600):
        """GitHub Actions 상시 실행: 명령은 즉시 응답, 특가는 interval 마다 확인, 정해진 시간 뒤 종료."""
        interval = float(self.cfg.get("interval_minutes", 5)) * 60
        end = time.time() + hours * 3600
        next_run = last_save = 0
        while time.time() < end:
            try:
                force = self.handle_commands(wait=25)
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
                save()
                last_save = time.time()
        if save:
            save()

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
