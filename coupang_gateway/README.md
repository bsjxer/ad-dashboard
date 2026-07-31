# 쿠팡 게이트웨이 (사내 LAN용)

이 PC(쿠팡에 등록된 IP)에서만 쿠팡 Wing API를 호출하고,
같은 네트워크의 팀원들은 이 서버를 통해 데이터를 받아간다.
팀원은 쿠팡 API 키를 몰라도 되고, 모든 호출은 이 PC의 IP로 나간다.

## 구성 파일
| 파일 | 역할 |
|------|------|
| `server.py` | 게이트웨이 서버 (첫 화면 = 계정·API 링크 목록) |
| `coupang_client.py` | 쿠팡 HMAC 서명 + 호출 |
| `accounts.json` | 계정 키 저장 (**커밋 금지**, .gitignore 처리됨) |
| `accounts.example.json` | 계정 등록 양식 |
| `check_accounts.py` | 전체 계정 인증/IP 통과 점검 |
| `start_gateway.ps1` | 게이트웨이 조용히 실행(중복 방지) |
| `wake_window.ps1` | 지정 시간대 PC 깨워 개방 후 원래 상태 복귀 |
| `setup_gateway.ps1` | 자동실행+방화벽+시간대작업 1회 설치(관리자) |

## 접속
- 이 PC: http://127.0.0.1:8000/
- 팀원(사내망): http://192.168.0.19:8000/
- 범용 호출: `/call?account=<계정명>&path=<쿠팡경로>&query=<쿼리>`

## 계정 추가
`accounts.json`의 `accounts`에 항목 추가 → 게이트웨이 재시작. 그게 전부.

## 접속 가능 시간
- 매일 03:00~04:00, 08:00~09:00 자동 개방
- 그 외에도 이 PC가 켜져 있으면(사용 중 포함) 언제든 접속 가능
- PC가 절전/종료면 접속 불가 (위 시간대엔 자동으로 깨어남)

## 계정 점검
```
python check_accounts.py
```
