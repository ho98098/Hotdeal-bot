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
    "/check - 지금 바로 확인"
)


class App:
    def __init__(self, cfg, store, tg, search_fn=None, fetch_fn=None):
        self.cfg, self.store, self.tg = cfg, store, tg
        n = cfg.get("naver", {})
        self.search = search_fn or (lambda q: market.search(q, n["client_id"], n["client_secret"]))
        self.fetch = fetch_fn or sources.fetch_source
        self.threshold = float(cfg.get("discount_threshold", 0.15))
        self.delay = float(cfg.get("request_delay_seconds", 2))

    # ---------- 텔레그램 명령 ----------
    def handle_commands(self):
        """새 명령을 처리. /check 가 있었으면 True."""
        offset = int(self.store.get_meta("tg_offset", 0))
        want_check = False
        for u in self.tg.updates(offset):
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
            elif cmd == "/check":
                want_check = True
            elif cmd in ("/start", "/help"):
                self.tg.send(HELP)
        return want_check

    # ---------- 핫딜 게시판 ----------
    def check_boards(self):
        cats = self.cfg.get("categories", {})
        min_price = int(self.cfg.get("min_price", 0))
        sent = 0
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
                d.category = sources.match_category(d.title, cats)
                if not d.category or d.price < max(min_price, 1):
                    continue
                try:
                    items = market.relevant(self.search(d.name), d.name)
                except Exception as e:
                    log.warning("시세 조회 실패 %s: %s", d.name, e)
                    continue
                ref, _ = market.market_price(items)
                time.sleep(self.delay)
                if not ref:
                    continue
                off = market.discount(d.price, ref)
                # 90% 넘게 싸면 다른 상품(부속품 등)과 비교됐을 가능성이 커서 제외
                if self.threshold <= off < 0.9:
                    self.tg.send(
                        f"[{d.category}] 시세보다 {off:.0%} 저렴\n{d.name}\n"
                        f"특가 {won(d.price)} / 시세 {won(ref)}\n"
                        f"{d.mall or '-'} · {d.source}\n{d.link}"
                    )
                    sent += 1
            time.sleep(self.delay)
        return sent

    # ---------- 관심 제품 ----------
    def check_watchlist(self):
        sent = 0
        for name, last_alert in self.store.watch_list():
            try:
                items = market.relevant(self.search(name), name)
            except Exception as e:
                log.warning("시세 조회 실패 %s: %s", name, e)
                continue
            now_med, low = market.market_price(items)
            time.sleep(self.delay)
            if not low:
                continue
            key = f"watch:{name}"
            hist = self.store.history_median(key)      # 내가 쌓은 최저가 기록의 30일 중앙값
            self.store.add_price(key, low["price"])
            ref = hist or now_med                       # 기록이 부족한 초반엔 현재 판매가 중앙값
            off = market.discount(low["price"], ref)
            if self.threshold <= off < 0.9 and (last_alert is None or low["price"] < last_alert):
                basis = "최근 30일 시세" if hist else "현재 판매가 중앙값"
                self.tg.send(
                    f"[관심 제품] {basis}보다 {off:.0%} 저렴\n{low['title']}\n"
                    f"최저가 {won(low['price'])} / 시세 {won(ref)}\n{low['mall']}\n{low['link']}"
                )
                self.store.watch_set_alert(name, low["price"])
                sent += 1
            elif last_alert is not None and off < self.threshold:
                self.store.watch_set_alert(name, None)  # 가격이 돌아오면 다음 하락 때 다시 알림
        return sent

    def run_once(self):
        return self.check_boards() + self.check_watchlist()

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
