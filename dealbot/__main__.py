"""실행: python -m dealbot [run|once|action|test]
비밀값은 환경변수(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)가
config.yaml 보다 우선합니다. GitHub Actions 에서는 저장소 Secrets 로 넣습니다."""
import logging
import os
import sys

import yaml

from .app import App, HELP
from .store import Store
from .telegram import Telegram


def load_config(path="config.yaml"):
    cfg = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    tg, nv = cfg.setdefault("telegram", {}), cfg.setdefault("naver", {})
    for sect, key, env in [(tg, "bot_token", "TELEGRAM_BOT_TOKEN"), (tg, "chat_id", "TELEGRAM_CHAT_ID"),
                           (nv, "client_id", "NAVER_CLIENT_ID"), (nv, "client_secret", "NAVER_CLIENT_SECRET")]:
        if os.environ.get(env):
            sect[key] = os.environ[env].strip()
        elif str(sect.get(key, "")).startswith("여기에"):
            sect[key] = ""
    return cfg


def _git(*args, inp=None):
    import subprocess
    r = subprocess.run(["git", *args], input=inp, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def restore_db(path):
    """data 브랜치에 저장된 최신 기록을 가져옴 (없으면 기존 파일 사용)."""
    if _git("fetch", "-q", "origin", "data") is not None:
        import subprocess
        blob = subprocess.run(["git", "show", "FETCH_HEAD:dealbot.db"], capture_output=True)
        if blob.returncode == 0 and blob.stdout:
            open(path, "wb").write(blob.stdout)
            logging.info("data 브랜치에서 기록 복원 (%d bytes)", len(blob.stdout))


def save_db(store, path):
    """열린 DB를 복사해 data 브랜치에 한 커밋으로 덮어씀 (작업 파일·main 브랜치는 건드리지 않음)."""
    import sqlite3
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "dealbot_snapshot.db")
    dst = sqlite3.connect(tmp)
    store.db.commit()
    store.db.backup(dst)
    dst.close()
    blob = _git("hash-object", "-w", tmp)
    tree = blob and _git("mktree", inp=f"100644 blob {blob}\tdealbot.db\n")
    commit = tree and _git("commit-tree", tree, "-m", "가격 기록")
    ok = commit and _git("push", "-q", "-f", "origin", f"{commit}:refs/heads/data") is not None
    logging.info("기록 저장: %s", bool(ok))


def claim_owner(tg, store):
    """chat_id 가 비어 있으면 봇에게 처음 /start 를 보낸 개인 채팅을 주인으로 등록."""
    owner = store.get_meta("owner_chat_id")
    if owner:
        return owner
    for u in tg.updates(0):
        chat = (u.get("message") or {}).get("chat", {})
        if chat.get("type") == "private":
            store.set_meta("owner_chat_id", chat["id"])
            tg.chat_id = str(chat["id"])
            tg.send("연결됐어요! 이제 이 채팅으로 특가 알림을 보냅니다.")
            return str(chat["id"])
    return None


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    if cmd == "dump":  # 진단용: 다나와 원본 페이지 저장
        import requests as rq
        from . import market
        os.makedirs("debug", exist_ok=True)
        for i, q in enumerate(sys.argv[2:]):
            r = rq.get(market.URL, params={"query": q}, headers=market.HEADERS, timeout=15)
            open(f"debug/danawa{i}.html", "w", encoding="utf-8").write(r.text)
            print(q, r.status_code, len(r.text), market.parse_danawa(r.text)[:5])
        return
    if not cfg["telegram"].get("bot_token"):
        sys.exit("텔레그램 봇 토큰이 없습니다.")
    store_path = cfg.get("db_path", "dealbot.db")
    if cmd in ("serve", "action") and os.environ.get("GITHUB_ACTIONS"):
        restore_db(store_path)
    store = Store(store_path)
    tg = Telegram(cfg["telegram"]["bot_token"], cfg["telegram"].get("chat_id") or "")
    if not tg.chat_id:
        tg.chat_id = claim_owner(tg, store) or ""
        if not tg.chat_id:
            print("아직 봇에게 /start 를 보낸 채팅이 없습니다. 텔레그램에서 봇에게 /start 를 보내주세요.")
            return
    app = App(cfg, store, tg)
    if cmd == "test":
        tg.send("특가 알림 봇 연결 확인")
    elif cmd == "once":
        print("알림", app.run_once(), "건")
    elif cmd == "serve":  # GitHub Actions 상시 실행
        import signal
        # 취소(새 실행으로 교체)될 때도 기록을 저장하고 끝나도록
        signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            app.serve(hours=float(os.environ.get("SERVE_HOURS", 5.7)), save=lambda: save_db(store, store_path))
        except KeyboardInterrupt:
            logging.info("종료 요청으로 멈춤")
    elif cmd == "action":  # GitHub Actions: 명령 처리 + 한 번 확인 후 종료
        forced = app.handle_commands()
        n = app.run_once()
        logging.info("알림 %d건", n)
        if forced:
            tg.send(f"확인 완료: 알림 {n}건")
    else:
        app.run_forever()


if __name__ == "__main__":
    main()
