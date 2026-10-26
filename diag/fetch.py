import os, sys, requests
sys.path.insert(0, "..")
from dealbot import sources
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36","Accept-Language":"ko-KR,ko;q=0.9"}
os.makedirs("out", exist_ok=True)
picks = {
 "pp": sources.fetch_source({"name":"뽐뿌","url":"https://www.ppomppu.co.kr/rss.php?id=ppomppu"}),
 "ru": sources.fetch_source({"name":"루리웹","url":"https://bbs.ruliweb.com/market/board/1020","type":"ruliweb"}),
 "cl": sources.fetch_source({"name":"클리앙","url":"https://www.clien.net/service/board/jirum","type":"clien"}),
 "eo": sources.fetch_source({"name":"어미새","url":"https://eomisae.co.kr/fs/rss"}),
}
for k, ds in picks.items():
    ds = sorted(ds, key=lambda d: -d.comments)  # 댓글 있는 글 우선
    for i, d in enumerate(ds[:2]):
        url = d.link.replace("http://www.ppomppu", "https://www.ppomppu")
        try:
            r = requests.get(url, headers=H, timeout=20)
            open(f"out/{k}{i}.html", "wb").write(r.content)
            print(k, i, r.status_code, len(r.content), url, d.title[:30])
        except Exception as e:
            print(k, i, "ERR", e)
    if k == "pp":
        for i, d in enumerate(ds[:2]):
            m = d.link.split("no=")[-1]
            for name, u in [("m", f"https://m.ppomppu.co.kr/new/bbs_view.php?id=ppomppu&no={m}")]:
                try:
                    r = requests.get(u, headers=H, timeout=20)
                    open(f"out/pp{name}{i}.html", "wb").write(r.content)
                    print("pp-" + name, i, r.status_code, len(r.content))
                except Exception as e:
                    print("pp-" + name, "ERR", e)
