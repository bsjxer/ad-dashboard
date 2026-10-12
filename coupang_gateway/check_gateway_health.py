# -*- coding: utf-8 -*-
"""게이트웨이가 '담당자 입장에서' 살아있는지 점검한다.

왜 필요한가 (2026-09-07):
  담당자들이 며칠 동안 접속 오류를 겪었는데 이 PC에서는 아무 이상이 없어 보였다.
  원인은 둘이 동시에 터진 것이었다 —
    (1) DHCP 임대 갱신으로 사내 IP가 192.168.0.19 -> 192.168.0.30 으로 바뀌어
        배포된 URL이 죽었고,
    (2) 같은 시점에 네트워크 프로필이 '공용'으로 재분류되어, IP를 되돌려도
        방화벽(Domain/Private 전용 규칙)이 인바운드를 막았다.
  둘 다 127.0.0.1 로는 멀쩡히 동작하기 때문에 이 PC에서 확인하면 정상으로 보인다.
  그래서 이 스크립트는 전부 **배포된 URL(EXPECTED_IP)** 기준으로 점검한다.

점검 항목: 사내 IP / 네트워크 프로필 / 방화벽 규칙 / 자동실행 등록 / 8000 리슨 /
          담당자 URL 실호출 / 잘못된 키 차단(403)

사용법:
  python check_gateway_health.py            # 점검만 (계정 1개로 실호출)
  python check_gateway_health.py --all      # 등록된 전 계정으로 실호출
  python check_gateway_health.py --fix      # 서버가 죽어 있으면 재기동 후 재점검
  python check_gateway_health.py --notify   # 문제가 있으면 화면에 알림창

문제가 있으면 exit 1. IP/프로필/방화벽처럼 시스템 설정을 바꿔야 하는 항목은
**자동으로 고치지 않고** 무엇을 어떻게 바꿔야 하는지만 알려준다(잘못 건드리면
이 PC가 사내망에서 떨어져 아침 수집까지 같이 죽는다).
"""
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "gateway_health.log")

EXPECTED_IP = "192.168.0.19"   # 담당자들에게 배포된 URL의 주소. 바꾸면 URL 재배포 필요.
PORT = 8000
EXPECTED_MAC = "A0-AD-9F-B2-49-2D"   # 공유기 DHCP 고정 할당 요청 시 쓰는 값
RUN_KEY_NAME = "CoupangGateway"      # 로그인 자동실행 등록 이름
OK_PROFILES = ("Private", "Domain")  # 방화벽 규칙이 허용하는 프로필

results = []   # (통과여부, 항목, 상세)


def check(passed, name, detail):
    results.append((bool(passed), name, detail))
    print("  [%s] %s: %s" % ("OK " if passed else "FAIL", name, detail))
    return bool(passed)


def ps(command):
    """PowerShell 실행. 한글 인터페이스명이 섞여도 안 깨지게 UTF-8로 받는다."""
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command
    p = subprocess.run(["powershell", "-NoProfile", "-Command", full],
                       capture_output=True)
    return p.stdout.decode("utf-8", "replace").strip()


def load_accounts():
    with open(os.path.join(HERE, "accounts.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    items = cfg["accounts"] if isinstance(cfg, dict) and "accounts" in cfg else cfg
    if isinstance(items, dict):
        items = [dict(name=k, **v) for k, v in items.items()]
    return items


def check_network():
    ips = ps("(Get-NetIPAddress -AddressFamily IPv4 |"
             " Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }"
             " ).IPAddress")
    ip_list = [x.strip() for x in ips.splitlines() if x.strip()]
    check(EXPECTED_IP in ip_list, "사내 IP",
          (", ".join(ip_list) or "없음")
          + ("" if EXPECTED_IP in ip_list else
             " -> 담당자 URL은 %s 기준입니다. 윈도우 설정에서 수동 IP를 %s로 되돌리거나,"
             " 공유기에서 MAC %s를 %s로 고정 할당하세요."
             % (EXPECTED_IP, EXPECTED_IP, EXPECTED_MAC, EXPECTED_IP)))

    # 프로필은 EXPECTED_IP가 붙은 인터페이스 것으로 본다(무선 등 다른 프로필이 섞일 수 있음).
    cat = ps("$i = (Get-NetIPAddress -AddressFamily IPv4 -IPAddress '%s'"
             " -ErrorAction SilentlyContinue).InterfaceIndex;"
             " if ($i) { (Get-NetConnectionProfile -InterfaceIndex $i).NetworkCategory }"
             " else { (Get-NetConnectionProfile | Select-Object -First 1).NetworkCategory }"
             % EXPECTED_IP)
    check(cat in OK_PROFILES, "네트워크 프로필",
          (cat or "알 수 없음")
          + ("" if cat in OK_PROFILES else
             " -> 공용이면 방화벽이 담당자 접속을 막습니다."
             " 설정 > 네트워크 및 인터넷 > 이더넷 > 네트워크 프로필 유형 >"
             " '개인 네트워크'로 바꾸세요."))

    rules = ps("Get-NetFirewallRule -Direction Inbound -Enabled True |"
               " ForEach-Object { $f = $_ | Get-NetFirewallPortFilter;"
               " if ($f.LocalPort -eq %d -and $_.Action -eq 'Allow')"
               " { $_.DisplayName + '|' + $_.Profile } }" % PORT)
    covering = [r.strip() for r in rules.splitlines() if r.strip()
                and (cat in r.split("|", 1)[-1] or "Any" in r.split("|", 1)[-1])]
    check(covering, "방화벽 %d 인바운드" % PORT,
          covering[0] if covering else
          "현재 프로필(%s)을 허용하는 규칙 없음 -> 담당자 접속이 막힙니다."
          " setup_gateway.ps1을 관리자로 다시 실행하세요." % cat)

    # NLA(Network Location Awareness)가 꺼져 있으면 윈도우가 네트워크를 식별하지 못해
    # 프로필이 '공용'으로 되돌아간다. 개인 네트워크로 바꿔도 안 붙어 있으면 여기가 원인.
    nla = ps("(Get-Service NlaSvc -ErrorAction SilentlyContinue).Status")
    nla_start = ps("(Get-Service NlaSvc -ErrorAction SilentlyContinue).StartType")
    check(nla == "Running", "NLA 서비스",
          "%s / 시작유형 %s" % (nla or "없음", nla_start or "?")
          + ("" if nla == "Running" else
             " -> 이게 꺼져 있으면 네트워크 프로필이 계속 '공용'으로 되돌아갑니다."
             " 관리자 PowerShell에서:"
             " Set-Service NlaSvc -StartupType Automatic; Start-Service NlaSvc"))

    run_key = ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'"
                 " -Name '%s' -ErrorAction SilentlyContinue).'%s'" % (RUN_KEY_NAME, RUN_KEY_NAME))
    check(run_key, "로그인 자동실행 등록",
          "등록됨" if run_key else
          "'%s' 없음 -> 재부팅하면 게이트웨이가 안 뜹니다."
          " setup_gateway.ps1을 관리자로 실행하세요." % RUN_KEY_NAME)


def listening():
    return bool(ps("(Get-NetTCPConnection -LocalPort %d -State Listen"
                   " -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess" % PORT))


def check_server(fix):
    up = listening()
    if not up and fix:
        print("  ...서버가 죽어 있어 start_gateway.ps1로 재기동합니다.")
        ps("& '%s'" % os.path.join(HERE, "start_gateway.ps1"))
        for _ in range(10):
            time.sleep(0.7)
            if listening():
                up = True
                break
    check(up, "%d 포트 리슨" % PORT,
          "리슨 중" if up else
          "죽어 있음 -> start_gateway.ps1 실행(--fix 옵션으로 자동 재기동 가능)")
    return up


def check_calls(accounts, test_all):
    """담당자가 실제로 쓰는 URL 형식으로 호출한다(127.0.0.1이 아니라 배포된 IP)."""
    date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    targets = [a for a in accounts if a.get("proxy_key")]
    if not test_all:
        targets = targets[:1]
    missing = [a.get("name") for a in accounts if not a.get("proxy_key")]
    if missing:
        check(False, "프록시 키", "키 없는 계정: %s -> gen_keys.py 실행" % ", ".join(missing))

    for a in targets:
        url = "http://%s:%d/sales?key=%s&date=%s" % (EXPECTED_IP, PORT, a["proxy_key"], date)
        label = "담당자 URL 호출 [%s]" % a.get("name")
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                j = json.loads(r.read().decode())
            check(True, label, "%s 총매출 %s원 / %s건"
                  % (date, format(j.get("total") or 0, ","), j.get("count")))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:150]
            hint = (" -> 쿠팡 Wing에 이 PC 공인 IP 등록이 풀렸을 수 있습니다"
                    " (check_accounts.py로 전 계정 확인)" if e.code in (401, 403) else "")
            check(False, label, "HTTP %s %s%s" % (e.code, body, hint))
        except Exception as e:  # noqa: BLE001
            check(False, label, "실패: %s" % e)

    try:
        urllib.request.urlopen(
            "http://%s:%d/sales?key=cpg_health_probe_invalid" % (EXPECTED_IP, PORT), timeout=30)
        check(False, "접근제어", "잘못된 키가 통과함 -> server.py 키 검증 확인 필요")
    except urllib.error.HTTPError as e:
        check(e.code == 403, "접근제어",
              "잘못된 키 -> HTTP %s%s" % (e.code, "" if e.code == 403 else " (403이어야 정상)"))
    except Exception as e:  # noqa: BLE001
        check(False, "접근제어", "확인 실패: %s" % e)


def notify(failed_names):
    msg = ("쿠팡 게이트웨이 점검 실패`n`n" + "`n".join(failed_names)
           + "`n`n담당자들이 데이터를 못 받고 있을 수 있습니다.").replace("'", "")
    ps("Add-Type -AssemblyName System.Windows.Forms;"
       " [System.Windows.Forms.MessageBox]::Show(\"%s\", \"쿠팡 게이트웨이\") | Out-Null" % msg)


def main(argv):
    test_all = "--all" in argv
    fix = "--fix" in argv
    want_notify = "--notify" in argv

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("==== 쿠팡 게이트웨이 점검 %s ====" % stamp)
    accounts = load_accounts()
    check_network()
    if check_server(fix):
        check_calls(accounts, test_all)
    else:
        print("  (서버가 죽어 있어 호출 점검은 건너뜁니다)")

    failed = ["%s: %s" % (name, detail) for ok, name, detail in results if not ok]
    verdict = ("정상 (%d개 항목)" % len(results) if not failed
               else "문제 %d건 / 전체 %d건" % (len(failed), len(results)))
    print("---- %s ----" % verdict)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (stamp, verdict))
        for line in failed:
            f.write("    - %s\n" % line)

    if failed:
        if want_notify:
            notify(["- " + name for ok, name, _ in results if not ok])
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
