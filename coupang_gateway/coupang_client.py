# -*- coding: utf-8 -*-
"""쿠팡 Wing OpenAPI 호출 (HMAC 서명). 계정별 키로 서명해서 쿠팡에 요청한다."""
import hmac
import hashlib
import json
from datetime import datetime, timezone

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
