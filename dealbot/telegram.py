"""텔레그램 봇: 알림 전송과 명령 수신."""
import requests


class Telegram:
    def __init__(self, token, chat_id):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)

    def send(self, text):
        r = requests.post(
            f"{self.base}/sendMessage",
            json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": False},
            timeout=15,
        )
        r.raise_for_status()

    def updates(self, offset=0):
        r = requests.get(f"{self.base}/getUpdates", params={"offset": offset, "timeout": 0}, timeout=15)
        r.raise_for_status()
        return r.json().get("result", [])
