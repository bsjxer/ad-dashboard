# -*- coding: utf-8 -*-
"""각 계정에 '스코프 프록시 키'를 발급해 accounts.json에 저장한다.
 - proxy_key 는 원본 쿠팡 키가 아니라, 이 게이트웨이 전용 랜덤 키.
 - 이미 있으면 건드리지 않음(재발급하려면 해당 계정의 proxy_key 를 지우고 다시 실행).
실행:  python gen_keys.py
"""
import json
import os
import secrets

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(HERE, "accounts.json")

with open(PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

changed = 0
for name, acc in cfg["accounts"].items():
    if not acc.get("proxy_key"):
        acc["proxy_key"] = "cpg_" + secrets.token_urlsafe(24)
        changed += 1

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print("발급/유지 완료 (신규 %d개)" % changed)
for name, acc in cfg["accounts"].items():
    print("  %-8s %s  key=%s" % (name, acc["vendor_id"], acc["proxy_key"]))
