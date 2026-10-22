import os, requests, urllib.parse as u
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36","Accept-Language":"ko-KR,ko;q=0.9"}
q=u.quote("갤럭시 버즈3 프로"); q2=u.quote("현대 엑스티어")
urls={
 "ppomppu4":"https://www.ppomppu.co.kr/rss.php?id=ppomppu4",
 "quasar_rss":"https://quasarzone.com/bbs/qb_saleinfo/rss",
 "quasar_html":"https://quasarzone.com/bbs/qb_saleinfo",
 "clien_rss":"https://www.clien.net/service/board/jirum/rss",
 "clien_html":"https://www.clien.net/service/board/jirum",
 "coolenjoy_rss":"https://coolenjoy.net/bbs/rss.php?bo_table=jirum",
 "eomisae_rss":"https://eomisae.co.kr/fs/rss",
 "fmkorea":"https://www.fmkorea.com/hotdeal",
 "arca":"https://arca.live/b/hotdeal",
 "enuri_search":f"https://www.enuri.com/search.jsp?keyword={q}",
 "enuri_search2":f"https://www.enuri.com/search.jsp?keyword={q2}",
 "enuri_m":f"https://m.enuri.com/m/search.jsp?keyword={q}",
}
os.makedirs("out",exist_ok=True)
for k,url in urls.items():
    try:
        r=requests.get(url,headers=H,timeout=20)
        open(f"out/{k}.txt","wb").write(r.content)
        print(k,r.status_code,len(r.content),r.headers.get("content-type"))
    except Exception as e: print(k,"ERR",e)
