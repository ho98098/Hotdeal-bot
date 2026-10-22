import sys, yaml
sys.path.insert(0, "..")
from dealbot import sources, market
cfg = yaml.safe_load(open("../config.yaml", encoding="utf-8"))
for src in cfg["popular"]:
    ds = sources.fetch_source(src)
    top = sorted(ds, key=lambda d: -d.votes)[:3]
    print(src["name"], len(ds), "개, 추천 상위:", [(d.votes, d.comments, d.title[:25]) for d in top])
for src in cfg["sources"][:3]:
    for d in sources.fetch_source(src)[:15]:
        q = market.quantity(d.name)
        if q: print("수량", q, "|", d.name[:40])
