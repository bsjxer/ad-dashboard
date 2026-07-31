# wake_window.ps1
# "접속 개방 시간대"를 여는 스크립트.
#  - 스케줄러가 지정 시각(예: 03:00, 08:00)에 이 스크립트를 실행(필요시 절전에서 깨움)
#  - 게이트웨이를 켜고, 지정한 시간(분)만큼 PC를 깨어 있게 유지 → 그 동안 다른 IP가 호출 가능
#  - 시간대가 끝나면 원래 상태로 복귀
#       원래 절전   -> 다시 절전
#       원래 완전종료 -> (마지막 창이면) 완전종료 / (첫 창이면) 절전으로 대기해 다음 창 대비
#       사용자가 쓰는 중 -> 그대로 켜둠 (절대 안 끔)
#
# 사용:
#   첫 창(03시):    ... -File wake_window.ps1 -Minutes 60
#   마지막 창(08시): ... -File wake_window.ps1 -Minutes 60 -IsLastRun

param(
  [int]$Minutes = 60,
  [switch]$IsLastRun,
  [int]$IdleGuardSeconds = 120
)

$ErrorActionPreference = "Continue"
$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$log    = Join-Path $here "wake_window.log"
$marker = Join-Path $here ".started_from_off"
function Log($m){ "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Tee-Object -FilePath $log -Append | Out-Null }

# --- 사람 입력 경과시간 측정용 ---
Add-Type @"
using System; using System.Runtime.InteropServices;
public class Idle {
  [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
  public static uint Seconds() {
    var i = new LASTINPUTINFO(); i.cbSize=(uint)Marshal.SizeOf(i);
    if(!GetLastInputInfo(ref i)) return 0;
    return ((uint)Environment.TickCount - i.dwTime)/1000;
  }
}
"@

# --- 진입 상태 판별 ---
$uptimeMin = ((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalMinutes
$coldBoot  = $uptimeMin -lt 6
$timerWake = ((powercfg -lastwake | Out-String) -match "타이머|Timer")
if     ($coldBoot -and -not $timerWake) { $entry = "OFF" }
elseif ($timerWake)                     { $entry = "SLEEP" }
else                                    { $entry = "AWAKE" }
if ($entry -eq "OFF") { New-Item -ItemType File -Path $marker -Force | Out-Null }
Log "window OPEN | entry=$entry isLast=$IsLastRun minutes=$Minutes"

# --- 게이트웨이 켜기 ---
& (Join-Path $here "start_gateway.ps1")

# --- 창이 열린 동안 절전 방지 ---
Add-Type -Namespace Win -Name Power -MemberDefinition @"
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
"@
$ES_CONTINUOUS = [uint32]2147483648   # 0x80000000
$ES_SYSTEM_REQUIRED = [uint32]1        # 0x00000001
[Win.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED) | Out-Null

Start-Sleep -Seconds ($Minutes * 60)   # 이 시간 동안 PC 깨어 있음 = 팀원 호출 가능

[Win.Power]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null   # 절전 방지 해제
Log "window CLOSE"

# --- 원래 상태로 복귀 ---
# 창이 끝난 시점에 사람이 쓰고 있으면(최근 입력) 절대 안 건드림
if ([Idle]::Seconds() -lt $IdleGuardSeconds) {
  Log "user present -> leave as-is"
  if ($IsLastRun) { Remove-Item $marker -ErrorAction SilentlyContinue }
  exit 0
}

function Do-Sleep    { Log "restore -> sleep";    rundll32.exe powrprof.dll,SetSuspendState 0,1,0 }
function Do-Shutdown { Log "restore -> shutdown"; Stop-Computer -Force }

if (-not $IsLastRun) {
  # 첫 창(03시): 다음 창(08시)을 위해 저전력 대기
  if ($entry -eq "OFF" -or $entry -eq "SLEEP") { Do-Sleep }
  else { Log "was awake (left on) -> leave as-is" }
}
else {
  # 마지막 창(08시): 하루 최종 복귀
  $startedFromOff = Test-Path $marker
  Remove-Item $marker -ErrorAction SilentlyContinue
  if     ($startedFromOff)    { Do-Shutdown }
  elseif ($entry -eq "SLEEP") { Do-Sleep }
  else { Log "was awake (left on) -> leave as-is" }
}
