# 쿠팡 게이트웨이 - 핸드오프

## 무엇인가
사무실 PC(쿠팡에 등록된 고정 IP)에서만 쿠팡 Wing API를 호출하고, 같은 사내 LAN의 담당자들이
**계정별 스코프 프록시 키가 든 단일 URL**로 데이터를 받아가는 게이트웨이.
담당자는 원본 쿠팡 키·IP 등록 불필요. 대표님 틱톡 게이트웨이와 같은 방식.

## 접속 방식 (담당자)
```
http://192.168.0.19:8000/sales?key=cpg_<계정별키>&date=2026-08-03
```
- `key` 가 계정을 지정 → 그 계정만 조회. 틀린/없는 키 → 403.
- **`/sales` = 제품별 일별 매출** (판매분석/데일리리포트와 동일 방식):
  ordersheets 주문을 제품별로 `salesPrice×shippingCount` 합산, createdAt=지정일, 전 배송상태 합산.
  응답 `{ account, date, total(총매출), count, data:[{productName, productId, quantity, amount}] }`
- `date` 생략 시 **어제**.
- **⚠️ 판매자배송 기준(로켓그로스 제외).** 로켓그로스는 실시간 공개 API가 없음(rg/orders는 출고 기준이라 최근 2주 0). 데일리리포트가 추적하는 판매자배송 제품은 판매분석과 일치.
- 정산(주간총액): `/settlement?key=...&month=YYYY-MM`
- 이 URL 하나만 프로그램/클로드코드/엑셀에 붙이면 됨.
- 검증: 드래프터 2026-08-03 총 27,865,150 (제품별 = Wing 판매분석과 일치). duskjin `scripts/collect_coupang.py`와 동일 로직.

## 파일
| 파일 | 역할 |
|------|------|
| `server.py` | 게이트웨이 서버(첫화면=API문서). 무설치(파이썬 내장 + requests). |
| `coupang_client.py` | 쿠팡 HMAC 서명 + 호출 |
| `accounts.json` | **원본 쿠팡 키 + 프록시 키. 커밋 금지(.gitignore).** 시크릿. |
| `accounts.example.json` | 등록 양식 |
| `gen_keys.py` | 계정별 프록시 키(cpg_...) 발급/유지 |
| `check_accounts.py` | 전체 계정 인증/IP 통과 점검 |
| `start_gateway.ps1` | 게이트웨이 조용히 실행(중복 방지) |
| `setup_gateway.ps1` | 자동실행(로그인) + 방화벽 8000 (관리자 1회) |
| `gen_handout.py` | (구버전) 계정별 자체실행 코드 생성 - 현재 미사용 |
| `wake_window.ps1` | (구버전) 시간대 자동 개방 - 현재 미사용 |

## 실행 / 배포
1. 최초 1회(관리자): `powershell -ExecutionPolicy Bypass -File setup_gateway.ps1`
   → 로그인 시 자동실행 + 방화벽 8000 허용.
2. 담당자에게 각자 URL 배포(위 형식). 키는 `accounts.json`의 `proxy_key`.
3. PC 켜져 있을 때만 동작(사내망).

## 현재 상태 (2026-08-03)
- 계정 9개 등록 + 인증/IP 통과 확인.
- 프록시 키 9개 발급 완료. 접근제어(403) 검증됨.
- 엔드포인트: `sales`(제품별 일별 매출=ordersheets 집계, 데일리리포트 방식), `settlement`(정산 주간총액).
- 매출 정의: ordersheets 주문상품 salesPrice×shippingCount, createdAt=대상일, 전 상태 합산 (판매자배송만).
- 로켓그로스는 실시간 API 없음(rg/orders 출고기준 지연). revenue-history(매출인식)는 시차 커서 미사용.
- setup_gateway.ps1 실행 완료(자동실행 + 방화벽).

## 확장 방법
`server.py`의 `GET_APIS`에 slug 추가(예: orders, ads) → `/<slug>?key=...`로 동일 동작.
쿠팡 엔드포인트 경로/파라미터는 실호출로 확인 후 등록(예: settlement은 marketplace_openapi settlement-histories).

## 키 관리
- 담당자 키 폐기/재발급: `accounts.json`에서 그 계정 `proxy_key` 삭제 → `python gen_keys.py` → 새 키만 재배포.
- 쿠팡 키 갱신(180일): `accounts.json`의 access/secret 교체 → 담당자 URL 그대로. 서버 자동 리로드.

## ⚠️ 주의 - 시크릿 백업
`accounts.json`은 gitignore라 원격에 안 올라감. 다른 PC에서 복구하려면 이 파일을 별도 안전 경로에
따로 백업해야 함(현재 이 프로젝트엔 자동 드라이브 동기화 없음).
