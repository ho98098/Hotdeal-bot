import sys
sys.path.insert(0, "..")
from dealbot import sources
for src in [{"name":"루리웹","url":"https://bbs.ruliweb.com/market/board/1020","type":"ruliweb"},
            {"name":"클리앙","url":"https://www.clien.net/service/board/jirum","type":"clien"},
            {"name":"어미새","url":"https://eomisae.co.kr/fs/rss"},
            {"name":"뽐뿌","url":"https://www.ppomppu.co.kr/rss.php?id=ppomppu"}]:
    ds = sources.fetch_source(src)
    for d in ds[3:5]:
        try:
            r = sources.fetch_reaction(d.link)
            r = r and {k: (v if k != "texts" else [t[:15] for t in v[:3]]) for k, v in r.items()}
        except Exception as e:
            r = f"실패 {e}"
        print(src["name"], "| 목록:", d.votes, d.downvotes, d.comments, "| 상세:", r, "|", d.title[:25])
