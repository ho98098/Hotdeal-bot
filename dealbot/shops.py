"""쇼핑몰 공식 API: 쿠팡 파트너스, 알리익스프레스 제휴.
키는 환경변수(GitHub Secrets)로 넣으며, 키가 없으면 조용히 건너뜁니다."""
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse

import requests

from .sources import Deal

log = logging.getLogger("dealbot")

# ---------------- 쿠팡 파트너스 ----------------
COUPANG_HOST = "https://api-gateway.coupang.com"
COUPANG_BASE = "/v2/providers/affiliate_open_api/apis/openapi/v1"


def coupang_keys():
    ak, sk = os.environ.get("COUPANG_ACCESS_KEY", ""), os.environ.get("COUPANG_SECRET_KEY", "")
    return (ak, sk) if ak and sk else None


def coupang_auth(method, path, query, ak, sk, now=None):
    """쿠팡 Open API 서명 (HmacSHA256, signed-date 는 UTC yyMMddTHHmmssZ)."""
    dt = time.strftime("%y%m%dT%H%M%SZ", time.gmtime(time.time() if now is None else now))
    msg = dt + method + path + query
    sig = hmac.new(sk.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={ak}, signed-date={dt}, signature={sig}"


def coupang_get(path, params, timeout=15):
    keys = coupang_keys()
    if not keys:
        return None
    query = urllib.parse.urlencode(params)
    r = requests.get(COUPANG_HOST + path + ("?" + query if query else ""),
                     headers={"Authorization": coupang_auth("GET", path, query, *keys),
                              "Content-Type": "application/json;charset=UTF-8"}, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if str(body.get("rCode", "0")) not in ("0", "200"):
        raise RuntimeError(f"쿠팡 API 오류: {body.get('rCode')} {body.get('rMessage')}")
    return body.get("data")


def _coupang_item(p):
    return {"title": p.get("productName", ""), "price": int(p.get("productPrice") or 0), "overseas": 0,
            "mall": "쿠팡", "link": p.get("productUrl", ""), "id": str(p.get("productId", "")),
            "rocket": bool(p.get("isRocket"))}


def coupang_goldbox():
    """쿠팡 골드박스(오늘의 특가) -> Deal 목록."""
    data = coupang_get(COUPANG_BASE + "/products/goldbox", {})
    deals = []
    for p in data or []:
        it = _coupang_item(p)
        if it["price"]:
            name = it["title"] + (" (로켓배송)" if it["rocket"] else "")
            deals.append(Deal("쿠팡 골드박스", f"coupang:{it['id']}:{it['price']}", name, it["title"],
                              "쿠팡", it["price"], it["link"]))
    return deals


def coupang_search(keyword, limit=5):
    """쿠팡 상품 검색 (시간당 호출 제한이 있어 /price 에서만 사용)."""
    data = coupang_get(COUPANG_BASE + "/products/search", {"keyword": keyword, "limit": limit})
    prods = (data or {}).get("productData", []) if isinstance(data, dict) else (data or [])
    return [it for it in (_coupang_item(p) for p in prods) if it["price"]]


# ---------------- 알리익스프레스 제휴 ----------------
ALI_URL = "https://api-sg.aliexpress.com/sync"


def ali_keys():
    k, s = os.environ.get("ALI_APP_KEY", ""), os.environ.get("ALI_APP_SECRET", "")
    return (k, s, os.environ.get("ALI_TRACKING_ID", "")) if k and s else None


def ali_sign(params, secret):
    """알리 Open Platform 서명: 파라미터를 이름순으로 '이름값' 이어붙여 HMAC-SHA256, 대문자 hex."""
    msg = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest().upper()


def ali_call(method, extra, timeout=20):
    keys = ali_keys()
    if not keys:
        return None
    key, secret, tid = keys
    params = {"method": method, "app_key": key, "sign_method": "sha256",
              "timestamp": str(int(time.time() * 1000)), "format": "json", "v": "2.0",
              "target_currency": "KRW", "target_language": "KO", "ship_to_country": "KR", **extra}
    if tid:
        params["tracking_id"] = tid
    params["sign"] = ali_sign(params, secret)
    r = requests.post(ALI_URL, data=params, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if "error_response" in body:
        e = body["error_response"]
        raise RuntimeError(f"알리 API 오류: {e.get('code')} {e.get('msg')}")
    return body


def _ali_products(body):
    """응답 구조: {<method>_response: {resp_result: {result: {products: {product: [...]}}}}}"""
    for v in (body or {}).values():
        if isinstance(v, dict) and "resp_result" in v:
            res = v["resp_result"]
            if isinstance(res, str):
                res = json.loads(res)
            prods = ((res.get("result") or {}).get("products") or {})
            return prods.get("product", prods) if isinstance(prods, dict) else prods
    return []


def _won(v):
    try:
        return int(float(str(v).replace(",", "")))
    except ValueError:
        return 0


def _ali_item(p):
    return {"title": p.get("product_title", ""), "price": _won(p.get("target_sale_price") or p.get("sale_price")),
            "original": _won(p.get("target_original_price") or p.get("original_price")),
            "overseas": 0, "mall": "알리", "id": str(p.get("product_id", "")),
            "link": p.get("promotion_link") or p.get("product_detail_url", "")}


def ali_hot(page_size=50):
    """알리 인기 할인 상품 -> Deal 목록 (해외 배송 상품)."""
    body = ali_call("aliexpress.affiliate.hotproduct.query",
                    {"page_size": page_size, "sort": "LAST_VOLUME_DESC"})
    deals = []
    for p in _ali_products(body):
        it = _ali_item(p)
        if it["price"]:
            deals.append(Deal("알리", f"ali:{it['id']}:{it['price']}", "[해외] " + it["title"], it["title"],
                              "알리", it["price"], it["link"]))
    return deals


def ali_search(keyword, page_size=10):
    body = ali_call("aliexpress.affiliate.product.query",
                    {"keywords": keyword, "page_size": page_size, "sort": "SALE_PRICE_ASC"})
    return [it for it in (_ali_item(p) for p in _ali_products(body)) if it["price"]]
