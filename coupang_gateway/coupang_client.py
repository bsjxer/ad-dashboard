# -*- coding: utf-8 -*-
"""쿠팡 Wing OpenAPI 호출 (HMAC 서명). 계정별 키로 서명해서 쿠팡에 요청한다."""
import hmac
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import quote

import requests

BASE = "https://api-gateway.coupang.com"


def _authorization(access_key, secret_key, method, path, query):
    """CEA HMAC-SHA256 Authorization 헤더 문자열 생성."""
    signed_date = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = signed_date + method + path + query
    signature = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        "CEA algorithm=HmacSHA256, access-key=%s, signed-date=%s, signature=%s"
        % (access_key, signed_date, signature)
    )


def call(account, method, path, query="", body=None, timeout=30):
    """account = {access_key, secret_key, vendor_id}
    쿠팡 응답의 (status_code, text) 반환."""
    method = method.upper()
    auth = _authorization(account["access_key"], account["secret_key"], method, path, query)
    url = BASE + path + (("?" + query) if query else "")
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json;charset=UTF-8",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = requests.request(method, url, headers=headers, data=data, timeout=timeout)
    return r.status_code, r.text


ORDER_STATUSES = ["ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY", "NONE_TRACKING"]


def orders_by_product(account, date_str):
    """지정일(createdAt) 주문을 제품별로 집계해 매출(salesPrice×shippingCount)·수량 반환.
    duskjin 데일리리포트와 동일 방식(판매자배송 ordersheets, 전 상태 합산).
    성공: (200, {productId 또는 name: {name, productId, quantity, amount}})."""
    vendor = account["vendor_id"]
    path = "/v2/providers/openapi/apis/api/v4/vendors/%s/ordersheets" % vendor
    prod = {}
    for status in ORDER_STATUSES:
        token = None
        while True:
            q = ("createdAtFrom=%s&createdAtTo=%s&status=%s&maxPerPage=50"
                 % (date_str, date_str, status))
            if token:
                q += "&nextToken=%s" % token
            # 429 대비 간단 재시도
            for attempt in range(4):
                sc, text = call(account, "GET", path, q)
                if sc == 429 and attempt < 3:
                    import time
                    time.sleep(2 * (attempt + 1))
                    continue
                break
            if sc != 200:
                return sc, text
            obj = json.loads(text)
            for o in obj.get("data") or []:
                for it in o.get("orderItems") or []:
                    name = it.get("sellerProductName") or it.get("vendorItemName") or "(무명)"
                    pid = it.get("sellerProductId") or it.get("productId")
                    cnt = it.get("shippingCount") or 0
                    amt = int((it.get("salesPrice") or 0) * cnt)
                    key = pid or name
                    if key not in prod:
                        prod[key] = {"productName": name, "productId": pid, "quantity": 0, "amount": 0}
                    prod[key]["quantity"] += cnt
                    prod[key]["amount"] += amt
            token = obj.get("nextToken")
            if not token:
                break
    return 200, prod


def call_all_pages(account, path, query_template, params, page_cap=200):
    """token 페이지네이션(hasNext/nextToken)을 끝까지 순회해 data 를 모두 합쳐 반환.
    query_template 은 {token} 을 포함해야 하며, 나머지 자리는 params 로 채운다.
    성공: (200, [합쳐진 data 리스트]) / 실패: (statuscode, 원본 text)."""
    items = []
    token = ""
    for _ in range(page_cap):
        p = dict(params)
        p["token"] = quote(token, safe="")   # nextToken 안전 인코딩
        query = query_template.format(**p)
        sc, text = call(account, "GET", path, query)
        if sc != 200:
            return sc, text
        obj = json.loads(text)
        items.extend(obj.get("data") or [])
        if obj.get("hasNext") and obj.get("nextToken"):
            token = obj["nextToken"]
        else:
            break
    return 200, items
