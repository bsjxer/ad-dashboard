# run_and_restore.ps1
# 스케줄러가 이 스크립트를 실행 → 수집 작업 실행 → PC를 "이전 상태"로 복귀.
# 하루 2회(예: 03:00, 08:00) 실행 시나리오 지원.
#
#  - 완전종료였음(RTC로 부팅): 첫 실행 후엔 [절전]으로 대기 → 마지막 실행 후 [완전종료]
#  - 절전이었음(타이머로 기상):   실행 후 다시 [절전]
#  - 켜둔 상태(사용자가 켜둠):    아무것도 안 함 (절대 안 끔)
#  - 사람이 쓰는 중(최근 입력):   아무것도 안 함
#
# 사용:
#   첫 실행(03시):    ... -File run_and_restore.ps1 -Job "python ...\collect.py"
#   마지막 실행(08시): ... -File run_and_restore.ps1 -Job "python ...\collect.py" -IsLastRun

param(
  [Parameter(Mandatory=$true)][string]$Job,   # 실행할 수집 명령
  [switch]$IsLastRun,                          # 그날의 마지막 실행이면 지정
  [int]$IdleGuardSeconds = 120                 # 최근 N초 내 사람 입력 있으면 복귀 안 함(안전장치)
)

$ErrorActionPreference = "Continue"
$log    = Join-Path $PSScriptRoot "run_and_restore.log"
$marker = Join-Path $PSScriptRoot ".started_from_off"   # "오늘은 완전종료에서 시작" 표식
function Log($m){ "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Tee-Object -FilePath $log -Append | Out-Null }

# --- 1) 진입 상태 판별 ---------------------------------------------------------
$uptimeMin = ((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalMinutes
$coldBoot  = $uptimeMin -lt 6
$lastWake  = (powercfg -lastwake | Out-String)
$timerWake = $lastWake -match "타이머|Timer"

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
$idleSec     = [Idle]::Seconds()
$userPresent = $idleSec -lt $IdleGuardSeconds

# 진입 상태 분류: OFF(완전종료→RTC부팅) / SLEEP(절전→타이머기상) / AWAKE(원래 켜져있음)
if     ($coldBoot -and -not $timerWake) { $entry = "OFF" }
elseif ($timerWake)                     { $entry = "SLEEP" }
else                                    { $entry = "AWAKE" }

# 완전종료에서 시작했으면 표식 남김(중간에 절전으로 바뀌어도 하루 내내 기억)
if ($entry -eq "OFF") { New-Item -ItemType File -Path $marker -Force | Out-Null }

Log "start | uptimeMin=$([math]::Round($uptimeMin,1)) entry=$entry idleSec=$idleSec userPresent=$userPresent isLastRun=$IsLastRun markerExists=$(Test-Path $marker)"

# --- 2) 수집 작업 실행 ---------------------------------------------------------
try {
  Log "job start: $Job"
  cmd /c $Job 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
  Log "job done (exit=$LASTEXITCODE)"
} catch {
  Log "job ERROR: $_"
}

# --- 3) 이전 상태로 복귀 -------------------------------------------------------
function Do-Sleep    { Log "restore -> sleep";    rundll32.exe powrprof.dll,SetSuspendState 0,1,0 }
function Do-Shutdown { Log "restore -> shutdown"; Stop-Computer -Force }

if ($userPresent) {
  Log "user present -> leave as-is"
  if ($IsLastRun) { Remove-Item $marker -ErrorAction SilentlyContinue }
  exit 0
}

if (-not $IsLastRun) {
  # 첫 실행(03시): 다음 실행(08시)을 위해 저전력으로 대기시켜 둔다
  if ($entry -eq "OFF" -or $entry -eq "SLEEP") { Do-Sleep }   # 절전으로 대기 → 08시 타이머가 깨움
  else { Log "was awake (left on) -> leave as-is" }           # 켜둔 PC는 안 건드림
}
else {
  # 마지막 실행(08시): 원래 상태로 최종 복귀
  $startedFromOff = Test-Path $marker
  Remove-Item $marker -ErrorAction SilentlyContinue
  if     ($startedFromOff)     { Do-Shutdown }                 # 완전종료에서 시작 → 완전종료로
  elseif ($entry -eq "SLEEP")  { Do-Sleep }                   # 절전에서 시작 → 절전으로
  else { Log "was awake (left on) -> leave as-is" }           # 켜둔 PC는 안 건드림
}
