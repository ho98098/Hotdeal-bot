import sys, yaml
sys.path.insert(0, "..")
from dealbot import sources, market
cfg = yaml.safe_load(open("../config.yaml", encoding="utf-8"))
for src in cfg["sources"]:
    try:
        ds = sources.fetch_source(src)
        print(src["name"], len(ds), "개 |", ds[0].title[:40] if ds else "-", "|", ds[0].price if ds else "")
    except Exception as e:
        print(src["name"], "실패", e)
for q in ["갤럭시 버즈3 프로", "현대 엑스티어", "오즈랜드 두부과자 40g 12봉"]:
    try:
        tops, rest = market.best_per_mall(market.search_all(q), q)
        print(q, "=>", [(t["mall"], t["price"], t["title"][:30]) for t in tops])
    except Exception as e:
        print(q, "실패", e)
