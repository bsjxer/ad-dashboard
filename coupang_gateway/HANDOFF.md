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

## 2026-09-07 장애 / 자가점검 추가

**증상**: 담당자들이 며칠 동안 접속 오류. 이 PC에서는 `127.0.0.1:8000`으로 멀쩡히 동작해서
정상으로 보였다. 원인이 **셋이 겹쳐** 있었다.

1. **사내 IP 변경** — DHCP 임대 갱신으로 `192.168.0.19` -> `192.168.0.30`.
   배포된 URL이 전부 죽음. 윈도우 수동 IP로 `.19` 복구.
2. **네트워크 프로필이 '공용'** — 방화벽 규칙 `Coupang Gateway 8000`은 Domain/Private
   전용이라, 공용이면 담당자 인바운드가 막힌다. IP를 되돌려도 여전히 안 된다.
3. **NLA(Network Location Awareness) 서비스가 Stopped/Manual** — 위 2번의 진짜 원인.
   NLA가 죽어 있으면 윈도우가 네트워크를 식별하지 못해, 개인 네트워크로 바꿔도 몇 분 뒤
   공용으로 되돌린다. `Set-Service NlaSvc -StartupType Automatic; Start-Service NlaSvc`
   (관리자) 후 다시 개인 네트워크로 지정 -> 유지됨.

쿠팡 Wing API 쪽은 처음부터 멀쩡했다(9계정 전부 OK, 공인 IP `112.217.194.106` 허용 유지).

**자가점검 `check_gateway_health.py` 신설** — 전부 **담당자가 쓰는 URL(EXPECTED_IP)** 기준으로
본다. `127.0.0.1`로 보면 이번 장애가 안 보였기 때문이다.
점검: 사내 IP / 네트워크 프로필 / 방화벽 규칙 / NLA / 로그인 자동실행 / 8000 리슨 /
담당자 URL 실호출 / 잘못된 키 403. 문제 있으면 exit 1, 로그는 `gateway_health.log`.
`--all` 전 계정 호출, `--fix` 서버 죽었으면 재기동, `--notify` 문제 시 알림창.
IP/프로필/방화벽/NLA 같은 시스템 설정은 **자동으로 안 고치고 조치 방법만 출력**한다.

**작업 스케줄러 `Coupang Gateway Health`** — 매일 09:00 + 로그온 2분 뒤,
`health_check_launcher.vbs`(wscript hidden) -> `--fix --notify`.

⚠️ **한글 경로 함정(실제로 걸렸음)**: 이 프로젝트 경로에 한글(`승진\클로드코드`)이 들어 있어서
- `health_check_launcher.vbs`는 **반드시 ANSI(CP949)로 저장**해야 한다. UTF-8로 저장하면
  wscript가 안의 한글 경로를 깨뜨린다.
- 작업 등록 XML은 **UTF-16**이어야 한다. PowerShell 5.1은 BOM 없는 UTF-8 .ps1을 ANSI로
  읽어서, 스크립트로 XML을 만들면 경로가 깨진 채 등록된다(실행 시 "파일 이름, 디렉터리
  이름 또는 볼륨 레이블 구문이 잘못되었습니다" 팝업).
- VBS 안에서 큰따옴표는 `Chr(34)`로 붙인다.

**남은 것**: 공유기(192.168.0.1) DHCP에서 MAC `A0-AD-9F-B2-49-2D`를 `192.168.0.19`로
고정 할당 요청함(2026-09-07, 경영팀). 지금은 윈도우 수동 IP라 공유기가 같은 주소를 다른
기기에 주면 충돌한다.
