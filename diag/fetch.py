import re, requests
H={"User-Agent":"Mozilla/5.0 (personal deal watcher)"}
ids=["ppomppu2","ppomppu3","ppomppu5","ppomppu6","ppomppu7","ppomppu8","ppomppu9","ppomppu10","pmarket","pmarket2","coupon","event","ali","alibaba","aliexpress","temu","coupang"]
for i in ids:
    try:
        r=requests.get(f"https://www.ppomppu.co.kr/rss.php?id={i}",headers=H,timeout=15)
        t=re.search(rb"<title>(.*?)</title>",r.content)
        items=re.findall(rb"<item>\s*<title>(.*?)</title>",r.content)[:2]
        print(i,r.status_code,len(r.content),(t.group(1).decode("utf-8","ignore") if t else "-"),[x.decode("utf-8","ignore")[:40] for x in items])
    except Exception as e: print(i,"ERR",e)
