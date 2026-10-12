# 특가 알림 봇

핫딜 게시판(뽐뿌, 루리웹)의 새 글과 등록한 관심 제품을 네이버 쇼핑 시세와 비교합니다.
시세보다 15% 이상 싸면 텔레그램으로 알려줍니다. GitHub Actions에서 15분마다 자동으로 실행됩니다.

## 설정 (Settings > Secrets and variables > Actions > New repository secret)
- `TELEGRAM_BOT_TOKEN` : BotFather에서 받은 봇 토큰
- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` : 네이버 개발자센터 검색 API 키
- `TELEGRAM_CHAT_ID` : 비워두면 봇에게 처음 /start 를 보낸 채팅이 자동으로 등록됩니다

## 텔레그램 명령 (다음 실행 때 반영, 최대 15분)
`/add 제품명`, `/remove 제품명`, `/list`, `/check`

## 바꿀 수 있는 것
`config.yaml`에서 카테고리 키워드, 할인 기준, 게시판 목록을 바꿀 수 있습니다.
확인 주기는 `.github/workflows/dealbot.yml`의 cron에서 바꿉니다.
