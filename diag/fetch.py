import os, requests
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36","Accept-Language":"ko-KR,ko;q=0.9"}
urls={
 "pp_list":"https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu",
 "pp_hot":"https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu&hotlist_flag=999",
 "ruli_list":"https://bbs.ruliweb.com/market/board/1020",
 "ruli_best":"https://bbs.ruliweb.com/market/board/1020?view_best=1",
 "pp_rss":"https://www.ppomppu.co.kr/rss.php?id=ppomppu",
 "ruli_rss":"https://bbs.ruliweb.com/market/board/1020/rss",
}
os.makedirs("out",exist_ok=True)
for k,url in urls.items():
    try:
        r=requests.get(url,headers=H,timeout=20); open(f"out/{k}.txt","wb").write(r.content)
        print(k,r.status_code,len(r.content),r.headers.get("content-type"))
    except Exception as e: print(k,"ERR",e)
