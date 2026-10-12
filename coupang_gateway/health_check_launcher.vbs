' Task Scheduler에서 콘솔 창 없이(hidden) 게이트웨이 자가점검을 실행하는 런처.
' 스케줄러가 cmd/bat을 직접 띄우면 세션/콘솔 teardown으로 python이 Ctrl+C(0xC000013A)로
' 죽는 문제가 있어(duskjin 아침 수집에서 실제 발생), wscript로 분리해 hidden 실행한다.
'
' 주의 1: 이 파일은 반드시 ANSI(CP949)로 저장할 것. UTF-8로 저장하면 wscript가 아래
'   한글 경로를 깨뜨려 "파일 이름, 디렉터리 이름 또는 볼륨 레이블 구문이 잘못되었습니다"로
'   실패한다(2026-09-07 실제 발생). 작업 스케줄러 등록 XML도 같은 이유로 UTF-16이어야 한다.
' 주의 2: 큰따옴표는 Chr(34)로 붙인다. VBS 안에서 따옴표를 이스케이프하면 읽기 어렵고
'   실제로 한 번 틀렸다.
'
' --fix   : 서버가 죽어 있으면 start_gateway.ps1로 재기동
' --notify: IP/프로필/방화벽/NLA 등 사람이 고쳐야 하는 문제가 남으면 알림창
Set sh = CreateObject("WScript.Shell")
q    = Chr(34)
py   = "C:\Users\bsjxe\AppData\Local\Programs\Python\Python313\python.exe"
here = "C:\Users\bsjxe\Desktop\승진\클로드코드\coupang_gateway"
cmd  = "cmd /c set PYTHONIOENCODING=utf-8&& " & q & py & q & " " & q & here & "\check_gateway_health.py" & q & " --fix --notify"
sh.Run cmd, 0, False
