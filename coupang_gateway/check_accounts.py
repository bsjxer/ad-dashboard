# -*- coding: utf-8 -*-
"""등록된 모든 계정을 실제 호출해 인증/IP 통과 여부를 점검한다.
실행:  python check_accounts.py
"""
import json
import os
import sys

import requests

import coupang_client

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "accounts.json"), "r", encoding="utf-8") as f:
    cfg = json.load(f)

try:
    myip = requests.get("https://api.ipify.org", timeout=10).text
except Exception as e:
    myip = "unknown(%s)" % e
print("이 PC 공인 IP:", myip)
print("=" * 60)

ok, bad = 0, 0
for name, acc in cfg["accounts"].items():
    vendor = acc["vendor_id"]
    path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    query = "vendorId=%s&maxPerPage=1" % vendor
    try:
        sc, text = coupang_client.call(acc, "GET", path, query)
    except Exception as e:
        sc, text = "ERR", str(e)

    if sc == 200:
        ok += 1
        verdict = "OK"
    else:
        bad += 1
        if sc == 403:
            verdict = "IP 미등록(403) - 이 IP를 해당 계정 Wing에 추가 필요"
        elif sc == 401:
            verdict = "인증 실패(401) - 키 확인"
        else:
            verdict = "실패(%s): %s" % (sc, str(text)[:120])
    print("%-8s %-11s -> %s" % (name, vendor, verdict))

print("=" * 60)
print("정상 %d / 문제 %d (전체 %d)" % (ok, bad, ok + bad))
