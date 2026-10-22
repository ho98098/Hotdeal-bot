# 특가 알림 봇

핫딜 게시판(뽐뿌, 루리웹)의 새 글과 등록한 관심 제품을 다나와 시세와 비교합니다.
시세보다 15% 이상 싸면 텔레그램으로 알려줍니다. GitHub Actions에서 상시 실행됩니다 (명령은 즉시 응답, 특가는 5분마다 확인).

## 설정 (Settings > Secrets and variables > Actions > New repository secret)
- `TELEGRAM_BOT_TOKEN` : BotFather에서 받은 봇 토큰
- `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY` : 쿠팡 파트너스 Open API 키 (선택, 최종 승인 후 발급)
- `ALI_APP_KEY`, `ALI_APP_SECRET`, `ALI_TRACKING_ID` : 알리익스프레스 제휴 API 키 (선택)
- `TELEGRAM_CHAT_ID` : 비워두면 봇에게 처음 /start 를 보낸 채팅이 자동으로 등록됩니다

## 텔레그램 명령
`/add 제품명`, `/remove 제품명`, `/list`, `/history 제품명`, `/price 제품명`, `/block 단어`, `/unblock 단어`, `/blocklist`, `/status`, `/category`, `/catadd 카테고리 키워드`, `/catdel 카테고리 키워드`, `/check`

## 바꿀 수 있는 것
`config.yaml`에서 카테고리 키워드, 할인 기준, 게시판 목록을 바꿀 수 있습니다.
확인 주기는 `.github/workflows/dealbot.yml`의 cron에서 바꿉니다.

참고: 네이버 쇼핑 검색 API는 2026-07-31 종료되어 다나와 검색 결과를 사용합니다.

## 알림 종류
- 카테고리 특가: 다나와·에누리 최저가보다 15% 이상 싸면 (수량이 다르면 환산해서 비교)
- 시세 비교 불가: 카테고리에 맞지만 가격비교 사이트에 없는 특가 (`notify_unmatched`)
- 인기 핫딜: 루리웹 추천 20 이상, 클리앙 추천 10 이상 (`popular`)
- 관심 제품: 30일 시세보다 15% 이상 싸거나 등록 후 최저가를 갱신하면
- 같은 특가가 여러 게시판에 올라오면 알림 1건으로 묶고 출처만 덧붙임 (더 싸면 새로 알림)
- 봇이 40분 넘게 멈췄다 다시 시작하면 알림
- 관심 제품 가격은 바뀔 때만 기록
- 종료·품절 표시가 붙은 글과 제외 키워드(`/block`)가 든 글은 알리지 않음
