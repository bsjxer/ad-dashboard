# -*- coding: utf-8 -*-
"""Meta 공식 Ad Library API(ads_archive)로 실제 무엇이 조회되는지 점검한다.

그래프 API 탐색기에서 액세스 토큰을 만들어 붙여넣고 실행:

  python api_check.py --token EAAG...            # 한국/EU 비교 점검
  python api_check.py --token EAAG... --country KR --q 쿠팡

한국 상업광고가 안 나오면 collect.py(광고 라이브러리 페이지 수집)를 쓰면 됩니다.
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx

API = "https://graph.facebook.com/v25.0/ads_archive"
FIELDS = ("id,page_id,page_name,ad_creation_time,ad_delivery_start_time,"
          "ad_delivery_stop_time,ad_creative_bodies,ad_creative_link_titles,"
          "ad_creative_link_captions,ad_snapshot_url,publisher_platforms")


def probe(token, country, q, ad_type="ALL", limit=5):
    params = {
        "access_token": token,
        "ad_reached_countries": json.dumps([country]),
        "ad_type": ad_type,
        "search_terms": q,
        "fields": FIELDS,
        "limit": limit,
        "ad_active_status": "ALL",
    }
    try:
        r = httpx.get(API, params=params, timeout=40)
        body = r.json()
    except Exception as e:
        return {"http": "-", "error": "%s: %s" % (type(e).__name__, e)}
    if "error" in body:
        e = body["error"]
        return {"http": r.status_code,
                "error": "[%s/%s] %s" % (e.get("code"), e.get("error_subcode"),
                                         e.get("message"))}
    data = body.get("data", [])
    return {"http": r.status_code, "count": len(data),
            "sample": [{"page_name": d.get("page_name"),
                        "start": d.get("ad_delivery_start_time"),
                        "body": (d.get("ad_creative_bodies") or [""])[0][:60]}
                       for d in data[:3]]}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--token", required=True, help="그래프 API 탐색기 액세스 토큰")
    p.add_argument("--country", help="이 국가만 점검 (기본: KR/DE/IE 비교)")
    p.add_argument("--q", default="쿠팡", help="검색어")
    a = p.parse_args()

    cases = ([(a.country, "ALL"), (a.country, "POLITICAL_AND_ISSUE_ADS")]
             if a.country else
             [("KR", "ALL"), ("KR", "POLITICAL_AND_ISSUE_ADS"),
              ("DE", "ALL"), ("IE", "ALL")])

    print("검색어: %s\n" % a.q)
    for country, ad_type in cases:
        res = probe(a.token, country, a.q, ad_type)
        head = "%-3s %-26s HTTP %s" % (country, ad_type, res.get("http"))
        if "error" in res:
            print("%s  →  실패: %s" % (head, res["error"]))
        else:
            print("%s  →  %d건" % (head, res["count"]))
            for s in res["sample"]:
                print("      · %s | %s | %s" % (s["page_name"], s["start"], s["body"]))
    print("\n※ ALL 로 한국 상업광고가 0건/오류라면 API 로는 불가능한 것이 맞고,"
          "\n   collect.py (광고 라이브러리 페이지 수집)를 쓰면 됩니다.")


if __name__ == "__main__":
    main()
