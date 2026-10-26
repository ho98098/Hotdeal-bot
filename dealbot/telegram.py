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
        return r.json().get("result", {}).get("message_id")

    def edit(self, message_id, text):
        r = requests.post(f"{self.base}/editMessageText",
                          json={"chat_id": self.chat_id, "message_id": message_id, "text": text}, timeout=15)
        return r.ok

    def set_commands(self, commands):
        """입력창에 '/' 를 치면 뜨는 명령어 메뉴 등록. commands: [(명령, 설명)]"""
        r = requests.post(f"{self.base}/setMyCommands",
                          json={"commands": [{"command": c, "description": d} for c, d in commands]}, timeout=15)
        return r.ok

    def updates(self, offset=0, wait=0):
        """wait 초 동안 새 메시지를 기다림 (롱 폴링: 메시지가 오면 즉시 반환)"""
        r = requests.get(f"{self.base}/getUpdates", params={"offset": offset, "timeout": wait}, timeout=wait + 15)
        r.raise_for_status()
        return r.json().get("result", [])
