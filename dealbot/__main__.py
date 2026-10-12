"""실행: python -m dealbot [run|once|action|test]
비밀값은 환경변수(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)가
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
            tg.send("연결됐어요! 이제 이 채팅으로 특가 알림을 보냅니다.\n\n" + HELP)
            return str(chat["id"])
    return None


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    if not cfg["telegram"].get("bot_token"):
        sys.exit("텔레그램 봇 토큰이 없습니다.")
    store = Store(cfg.get("db_path", "dealbot.db"))
    tg = Telegram(cfg["telegram"]["bot_token"], cfg["telegram"].get("chat_id") or "")
    if not tg.chat_id:
        tg.chat_id = claim_owner(tg, store) or ""
        if not tg.chat_id:
            print("아직 봇에게 /start 를 보낸 채팅이 없습니다. 텔레그램에서 봇에게 /start 를 보내주세요.")
            return
    if not cfg["naver"].get("client_id"):
        logging.warning("네이버 API 키가 없어 시세 비교를 건너뜁니다. 명령만 처리합니다.")
        App(cfg, store, tg, search_fn=lambda q: []).handle_commands()
        return
    app = App(cfg, store, tg)
    if cmd == "test":
        tg.send("특가 알림 봇 연결 확인")
    elif cmd == "once":
        print("알림", app.run_once(), "건")
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
