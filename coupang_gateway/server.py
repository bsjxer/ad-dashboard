# -*- coding: utf-8 -*-
"""
쿠팡 Wing 게이트웨이 (사내 LAN용)

이 PC(쿠팡에 등록된 IP)에서만 쿠팡을 호출하고,
같은 네트워크의 팀원들은 이 서버를 통해 데이터를 받아간다.

실행:  python server.py
팀원 접속:  http://<이PC의_사내IP>:8000/...

엔드포인트
  GET  /health                      상태 + 등록 계정 목록
  GET  /accounts                    등록된 계정 이름 목록
  GET  /call?account=<name>&path=<쿠팡경로>&query=<쿼리>&method=GET
                                    지정 계정 키로 서명해 쿠팡 호출(범용 통로)
  POST /call?account=...&path=...   본문(JSON)을 그대로 전달 (일부 리포트 API는 POST)
"""
import json
import os
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode, unquote, unquote_to_bytes

import coupang_client

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = {"accounts": {}, "gateway_token": ""}
PORT = int(os.environ.get("COUPANG_GATEWAY_PORT", "8000"))

# 첫 화면에 계정별로 노출할 GET API 목록.
#  slug = 주소에 쓰는 짧은 이름 (예: /가론지/상품목록)
#  {vendor} 자리에 업체코드가 들어간다.
# (검증된 조회형 API. 광고성과/판매정산 등 POST형은 전용 엔드포인트로 추후 추가)
GET_APIS = [
    {"slug": "settlement", "label": "판매정산(주간총액)",
     "path": "/v2/providers/marketplace_openapi/apis/api/v1/settlement-histories",
     "query": "vendorId={vendor}&revenueRecognitionYearMonth={month}",
     # ?month=YYYY-MM 로 월 지정, 생략하면 이번 달
     "note": "월 지정: ?month=YYYY-MM (생략 시 이번 달)"},
    {"slug": "revenue", "label": "제품별매출(매출내역)", "paged": True,
     "path": "/v2/providers/openapi/apis/api/v1/revenue-history",
     "query": "vendorId={vendor}&recognitionDateFrom={from}&recognitionDateTo={to}&maxPerPage=50&token={token}",
     # ?from=YYYY-MM-DD&to=YYYY-MM-DD (생략 시 최근 7일). 각 주문의 items[]에 제품별 판매액/수량/수수료
     "note": "기간 지정: ?from=YYYY-MM-DD&to=YYYY-MM-DD (생략 시 최근 7일)"},
]
API_BY_SLUG = {a["slug"]: a for a in GET_APIS}


def build_link(account_name, path, query):
    params = {"account": account_name, "path": path}
    if query:
        params["query"] = query
    return "/call?" + urlencode(params)


DOC_HEAD = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>쿠팡 게이트웨이 API</title>
<style>
 body{font-family:'Malgun Gothic',system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#222;line-height:1.5}
 h1{font-size:22px} h2{font-size:16px;margin-top:28px;border-bottom:1px solid #eee;padding-bottom:4px}
 table{border-collapse:collapse;width:100%;margin:8px 0} th,td{border-bottom:1px solid #eee;padding:7px 8px;text-align:left;font-size:14px}
 th{color:#666;font-size:12px} .vendor{font-family:monospace}
 pre{background:#f6f8fa;padding:12px;border-radius:6px;overflow-x:auto;font-size:12.5px}
 code{font-family:Consolas,monospace} .ep{font-family:monospace;background:#eef;padding:1px 5px;border-radius:3px}
 .muted{color:#888;font-size:13px}
 @media(prefers-color-scheme:dark){body{background:#1a1a1a;color:#ddd}th,td{border-color:#333}h2{border-color:#333}pre{background:#111}.ep{background:#243}}
</style></head><body>"""


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_index(host):
    base = "http://" + host
    accts = CONFIG["accounts"]
    settle = base + "/settlement?key=cpg_당신의키&month=2026-06"

    py = (
        "import requests\n"
        "URL = \"" + base + "/settlement?key=cpg_당신의키\"   # 담당자 전용 URL(관리자에게 수령)\n\n"
        "data = requests.get(URL).json()[\"data\"]            # 이번 달\n"
        "print(data)\n\n"
        "# 특정 월\n"
        "data = requests.get(URL + \"&month=2026-06\").json()[\"data\"]\n"
    )
    pq = (
        "// Excel: 데이터 > 웹에서 / Power Query\n"
        "let\n"
        "    resp = Json.Document(Web.Contents(\"" + settle + "\")),\n"
        "    rows = resp[data],\n"
        "    t = Table.FromRecords(rows)\n"
        "in\n"
        "    t\n"
    )
    curl = "curl \"" + settle + "\""

    html = [DOC_HEAD]
    html.append("<h1>쿠팡 게이트웨이 API</h1>")
    html.append("<p class='muted'>Base URL: <code>" + base + "</code> · 사내망 전용 · 응답은 JSON</p>")

    html.append("<h2>사용법</h2>")
    html.append("<p>관리자에게 받은 <b>담당자 전용 URL</b>(서버+키 포함)을 그대로 프로그램/클로드코드에 붙여넣으면 됩니다. "
                "그 키로는 담당 계정만 조회되고, 다른 계정은 403입니다.</p>")

    html.append("<h2>엔드포인트</h2>")
    html.append("<table><thead><tr><th>메서드</th><th>경로</th><th>설명</th></tr></thead><tbody>"
                "<tr><td>GET</td><td><span class='ep'>/settlement?key=cpg_...</span></td>"
                "<td>판매정산(주간 총액). <code>&amp;month=YYYY-MM</code> (생략 시 이번 달)</td></tr>"
                "<tr><td>GET</td><td><span class='ep'>/revenue?key=cpg_...</span></td>"
                "<td>제품별 매출(매출내역). <code>&amp;from=YYYY-MM-DD&amp;to=YYYY-MM-DD</code> (생략 시 최근 7일). "
                "각 주문 items[]에 제품명·수량·판매액·수수료·정산액</td></tr>"
                "<tr><td>GET</td><td><span class='ep'>/accounts</span></td><td>계정 목록(이름만, JSON)</td></tr>"
                "</tbody></table>")

    html.append("<h2>응답 형식</h2>")
    html.append("<pre><code>{ \"status_code\": 200, \"data\": [ ...쿠팡 원본 응답... ] }</code></pre>")

    html.append("<h2>예시 · Python</h2><pre><code>" + _esc(py) + "</code></pre>")
    html.append("<h2>예시 · Excel(Power Query)</h2><pre><code>" + _esc(pq) + "</code></pre>")
    html.append("<h2>예시 · curl</h2><pre><code>" + _esc(curl) + "</code></pre>")

    html.append("<p class='muted'>※ 원본 쿠팡 키는 서버에만 있고 URL엔 없습니다(프록시 키). "
                "쿠팡 키가 갱신돼도 담당자 URL은 그대로. 키 유출 시 관리자가 해당 키만 재발급하면 됩니다. "
                "계정 " + str(len(accts)) + "개 등록됨.</p>")
    html.append("</body></html>")
    return "\n".join(html)


ACCOUNTS_PATH = os.path.join(HERE, "accounts.json")
_config_mtime = [0.0]


def load_config():
    global CONFIG
    with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
    CONFIG.setdefault("accounts", {})
    CONFIG.setdefault("gateway_token", "")
    try:
        _config_mtime[0] = os.path.getmtime(ACCOUNTS_PATH)
    except OSError:
        pass


def maybe_reload():
    """accounts.json이 바뀌면 자동으로 다시 읽는다.
    → 관리자가 키만 교체하면 서버 재시작 없이 즉시 반영(팀원 URL은 그대로)."""
    try:
        m = os.path.getmtime(ACCOUNTS_PATH)
    except OSError:
        return
    if m != _config_mtime[0]:
        try:
            load_config()
            print("accounts.json reloaded -> %s" % list(CONFIG["accounts"]))
        except Exception as e:
            print("reload failed (기존 설정 유지): %s" % e)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self):
        need = CONFIG.get("gateway_token", "")
        if not need:
            return True  # 토큰 미설정 = LAN 내 자유 접근
        return self.headers.get("X-Token", "") == need

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, verb):
        maybe_reload()   # 계정 파일 변경 시 자동 반영
        u = urlparse(self.path)
        route = u.path
        q = parse_qs(u.query)

        if route == "/" and verb == "GET":
            host = self.headers.get("Host") or ("127.0.0.1:%d" % PORT)
            html = render_index(host).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if route == "/health":
            return self._send(200, {"status": "ok", "accounts": list(CONFIG["accounts"])})
        if route == "/accounts":
            return self._send(200, {"accounts": list(CONFIG["accounts"])})

        if route == "/call":
            if not self._token_ok():
                return self._send(401, {"error": "invalid token"})
            account_name = q.get("account", [None])[0]
            path = q.get("path", [None])[0]
            query = q.get("query", [""])[0]
            method = q.get("method", [verb])[0]
            if account_name not in CONFIG["accounts"]:
                return self._send(404, {"error": "unknown account",
                                        "have": list(CONFIG["accounts"])})
            if not path:
                return self._send(400, {"error": "path required"})

            body = None
            if verb == "POST":
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                if raw:
                    body = json.loads(raw.decode("utf-8"))
            try:
                sc, text = coupang_client.call(
                    CONFIG["accounts"][account_name], method, path, query, body
                )
            except Exception as e:
                return self._send(502, {"error": "coupang call failed", "detail": str(e)})
            try:
                data = json.loads(text)
            except ValueError:
                data = text
            return self._send(sc, {"status_code": sc, "data": data})

        # 스코프 프록시 키 방식:  /<slug>?key=cpg_xxx[&month=YYYY-MM]
        # 키가 계정을 지정 → 그 계정만 조회. 틀리거나 없으면 403.
        parts = [p for p in route.split("/") if p]
        if len(parts) == 1 and parts[0] in API_BY_SLUG:
            slug = parts[0]
            key = q.get("key", [None])[0]
            key_map = {a.get("proxy_key"): (n, a)
                       for n, a in CONFIG["accounts"].items() if a.get("proxy_key")}
            if not key or key not in key_map:
                return self._send(403, {"error": "invalid or missing key"})
            name, acc = key_map[key]
            now = datetime.now()

            # 이미 배포된 /settlement URL 하나로 [정산 총액 + 제품별 매출] 모두 반환
            if slug == "settlement":
                month = q.get("month", [now.strftime("%Y-%m")])[0]
                # 1) 정산(주간 총액)
                try:
                    ssc, stext = coupang_client.call(
                        acc, "GET", API_BY_SLUG["settlement"]["path"],
                        "vendorId=%s&revenueRecognitionYearMonth=%s" % (acc["vendor_id"], month))
                    sobj = json.loads(stext)
                    settlement = sobj.get("data") if isinstance(sobj, dict) else sobj
                except Exception as e:
                    return self._send(502, {"error": "settlement call failed", "detail": str(e)})
                # 2) 제품별 매출(매출내역) - 해당 월 범위(또는 from/to 지정)
                y, m = int(month[:4]), int(month[5:7])
                nextm = ("%d-01-01" % (y + 1)) if m == 12 else ("%d-%02d-01" % (y, m + 1))
                mend = datetime.strptime(nextm, "%Y-%m-%d") - timedelta(days=1)
                dfrom = q.get("from", [month + "-01"])[0]
                dto = q.get("to", [(mend if mend < now else now).strftime("%Y-%m-%d")])[0]
                rparams = {"vendor": acc["vendor_id"], "from": dfrom, "to": dto}
                try:
                    rsc, rev = coupang_client.call_all_pages(
                        acc, API_BY_SLUG["revenue"]["path"], API_BY_SLUG["revenue"]["query"], rparams)
                except Exception as e:
                    return self._send(502, {"error": "revenue call failed", "detail": str(e)})
                if rsc != 200:
                    try:
                        rev = json.loads(rev)
                    except ValueError:
                        pass
                    revenue = {"from": dfrom, "to": dto, "error": rev}
                else:
                    revenue = {"from": dfrom, "to": dto, "count": len(rev), "data": rev}
                return self._send(200, {
                    "status_code": 200, "account": name, "month": month,
                    "settlement": settlement, "revenue": revenue,
                })

            # 그 외 슬러그 (revenue 단독 등)
            api = API_BY_SLUG[slug]
            fmt = {
                "vendor": acc["vendor_id"],
                "month": q.get("month", [now.strftime("%Y-%m")])[0],
                "from": q.get("from", [(now - timedelta(days=6)).strftime("%Y-%m-%d")])[0],
                "to": q.get("to", [now.strftime("%Y-%m-%d")])[0],
            }
            path = api["path"].format(**fmt)
            try:
                if api.get("paged"):
                    sc, result = coupang_client.call_all_pages(acc, path, api["query"], fmt)
                    if sc != 200:
                        try:
                            result = json.loads(result)
                        except ValueError:
                            pass
                        return self._send(sc, {"status_code": sc, "data": result})
                    return self._send(200, {"status_code": 200, "count": len(result), "data": result})
                else:
                    query = api["query"].format(**fmt)
                    sc, text = coupang_client.call(acc, "GET", path, query)
            except Exception as e:
                return self._send(502, {"error": "coupang call failed", "detail": str(e)})
            try:
                data = json.loads(text)
            except ValueError:
                data = text
            return self._send(sc, {"status_code": sc, "data": data})

        self._send(404, {"error": "not found",
                         "routes": ["/", "/health", "/accounts", "/<slug>?key=..."]})

    def log_message(self, fmt, *args):
        # 접근 로그 (필요시)
        try:
            print("%s - %s" % (self.address_string(), fmt % args))
        except Exception:
            pass


def main():
    load_config()
    print("Coupang gateway  port=%d  accounts=%s  token=%s"
          % (PORT, list(CONFIG["accounts"]),
             "ON" if CONFIG.get("gateway_token") else "off"))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
