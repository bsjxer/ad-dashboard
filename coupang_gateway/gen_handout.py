# -*- coding: utf-8 -*-
"""accounts.json을 읽어 계정별 '자체 실행 호출 코드'를 handout/ 폴더에 하나씩 생성.
각 파일은 그 계정 키가 박힌 독립 실행 코드(외부 의존: requests 뿐)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "handout")
os.makedirs(OUT, exist_ok=True)

with open(os.path.join(HERE, "accounts.json"), "r", encoding="utf-8") as f:
    accounts = json.load(f)["accounts"]

TEMPLATE = '''# -*- coding: utf-8 -*-
# 쿠팡 판매정산 호출 코드 - {name} ({vendor})
# 준비: pip install requests
# 실행: python "{name}_판매정산.py"
#
# ※ 이 코드를 실행하는 PC의 공인 IP가 이 계정 쿠팡 Wing에 등록돼 있어야 함(아니면 403).
import hmac
import hashlib
import requests
from datetime import datetime, timezone

VENDOR_ID  = "{vendor}"
ACCESS_KEY = "{access}"
SECRET_KEY = "{secret}"


def _call(method, path, query=""):
    dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = dt + method + path + query
    signature = hmac.new(SECRET_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    auth = "CEA algorithm=HmacSHA256, access-key=%s, signed-date=%s, signature=%s" % (ACCESS_KEY, dt, signature)
    url = "https://api-gateway.coupang.com" + path + (("?" + query) if query else "")
    headers = {{"Authorization": auth, "Content-Type": "application/json;charset=UTF-8"}}
    return requests.get(url, headers=headers, timeout=30).json()


def get_settlement(month=None):
    """판매정산 조회. month 예: "2026-06" (생략하면 이번 달)."""
    if month is None:
        month = datetime.now().strftime("%Y-%m")
    path = "/v2/providers/marketplace_openapi/apis/api/v1/settlement-histories"
    query = "vendorId=%s&revenueRecognitionYearMonth=%s" % (VENDOR_ID, month)
    return _call("GET", path, query)


if __name__ == "__main__":
    result = get_settlement()            # 이번 달
    # result = get_settlement("2026-06")  # 특정 월
    print(result)
'''

made = []
for name, acc in accounts.items():
    code = TEMPLATE.format(name=name, vendor=acc["vendor_id"],
                           access=acc["access_key"], secret=acc["secret_key"])
    fname = "%s_판매정산.py" % name
    with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
        f.write(code)
    made.append(fname)

print("생성 완료 (%d개):" % len(made))
for m in made:
    print("  handout/" + m)
