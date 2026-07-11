param(
  [Parameter(Mandatory=$true)][string]$Step,
  [string]$SeniorToken = $env:SENIOR_TOKEN,
  [string]$BackendUrl  = "http://localhost:8000",
  [string]$BackendLog  = "C:\Users\user\Desktop\family-shield\backend.log",
  [string]$Pkg         = "ru.familyshield.app",
  [string]$Activity    = "ru.familyshield.app/.MainActivity",
  [string]$ApkPath     = "C:\Users\user\Desktop\family-shield\android\app\build\outputs\apk\debug\app-debug.apk"
)

$ErrorActionPreference = "Continue"
function Say($m)  { Write-Host "`n>>> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Warn($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }

function Require-Adb {
  $d = adb devices | Select-String -Pattern "`tdevice$"
  if (-not $d) { Bad "adb: no device connected"; exit 1 }
  Ok ("adb device: " + $d[0].ToString().Split()[0])
}

function Step-Install {
  Say "Step 1: clear + install + launch"
  Require-Adb
  adb shell pm clear $Pkg | Out-Null
  Ok "pm clear"
  if (Test-Path $ApkPath) { adb install -r $ApkPath; Ok "APK installed" }
  else { Warn "APK not found at $ApkPath - install via Android Studio Run" }
  adb shell am start -n $Activity | Out-Null
  Ok "MainActivity started - now on phone choose RELATIVE role"
  Say "logcat starting in 3 sec, Ctrl+C to stop"
  Start-Sleep 3
  adb logcat -c
  adb logcat *:S FirebaseMessaging:V AlertNotifier:V FullScreenIntent:V "$Pkg`:V" AndroidRuntime:E
}

function Trigger-Scam {
  if (-not $SeniorToken) { Bad "SENIOR_TOKEN empty"; return $null }
  $body = '{"transcript":"Zdravstvujte, eto sluzhba bezopasnosti banka. S vashego scheta pytayutsya spisat dengi. Srochno perevedite sredstva na bezopasnyj schet, prodiktujte kod iz SMS."}'
  try {
    $r = Invoke-RestMethod -Method Post -Uri "$BackendUrl/api/debug/analyze" `
         -Headers @{ Authorization = "Bearer $SeniorToken" } `
         -ContentType "application/json" -Body $body
    Ok "Scam triggered"
    $r | ConvertTo-Json -Depth 5 | Write-Host
    return $r
  } catch { Bad ("Trigger error: " + $_); return $null }
}

function Step-Foreground {
  Say "Step 4: foreground alert"
  Require-Adb
  Ok "Make sure relative app is OPEN (RelativeHomeScreen)"
  Read-Host "Press Enter when ready"
  Trigger-Scam | Out-Null
  Say "Look at phone: full-screen AlertActivity should appear"
  Start-Sleep 5
  adb logcat -d *:S FirebaseMessaging:V AlertNotifier:V | Select-Object -Last 40
}

function Step-Killed {
  Say "Step 5: KILLED PROCESS (main test)"
  Require-Adb
  adb shell am start -n $Activity | Out-Null
  Start-Sleep 2
  Say "Killing process softly (adb am kill == swipe from recents)"
  adb shell am kill $Pkg
  Start-Sleep 1
  Read-Host "Swipe app from recents manually for cleanliness, then Enter"
  adb logcat -c
  Trigger-Scam | Out-Null
  Say "Waiting 15 sec for FCM push..."
  Start-Sleep 15
  $log = adb logcat -d *:S FirebaseMessaging:V AlertNotifier:V "$Pkg`:V"
  if ($log -match "onMessageReceived") { Ok "onMessageReceived fired (process woke up)" } else { Bad "onMessageReceived NOT found" }
  if ($log -match "AlertNotifier|AlertActivity") { Ok "Alert started" } else { Warn "Alert not visible in logs" }
  $log | Select-Object -Last 40 | Write-Host
  Say "On phone: full-screen alert must be visible. Tap it - AlertScreen with correct call_id must open."
}

function Step-Lockscreen {
  Say "Step 6: lockscreen alert"
  Require-Adb
  adb shell am kill $Pkg
  Ok "Process killed"
  Say "Locking screen in 3 sec - do not touch phone"
  Start-Sleep 3
  adb shell input keyevent KEYCODE_POWER
  Start-Sleep 2
  Trigger-Scam | Out-Null
  Say "Phone screen must turn ON and show full-screen alert over lockscreen."
}

function Step-Logs {
  Say ("Analyzing backend log: " + $BackendLog)
  if (-not (Test-Path $BackendLog)) { Warn "log not found - run: uvicorn ... 2>&1 | Tee-Object -FilePath backend.log"; return }
  $lines = Get-Content $BackendLog -Tail 500
  $pl = $lines | Select-String "FCM v1 payload:" | Select-Object -Last 1
  if (-not $pl) { Bad "'FCM v1 payload:' not found in last 500 lines"; return }
  $json = $pl.Line -replace ".*FCM v1 payload:\s*",""
  Ok "Payload found:"
  Write-Host $json
  try {
    $p = $json | ConvertFrom-Json
    if ($p.message.notification) { Bad "notification key present - must be absent" } else { Ok "no notification key" }
    if ($p.message.data.type -eq "scam_alert") { Ok "data.type == scam_alert" } else { Bad ("data.type = " + $p.message.data.type) }
    if ($p.message.data.call_id) { Ok ("data.call_id = " + $p.message.data.call_id) } else { Bad "call_id empty" }
    if ($p.message.android.priority -eq "HIGH") { Ok "priority == HIGH" } else { Bad ("priority = " + $p.message.android.priority) }
    if ($p.message.android.ttl -eq "60s") { Ok "ttl == 60s" } else { Bad ("ttl = " + $p.message.android.ttl) }
  } catch { Bad ("JSON parse error: " + $_) }
  $tl = $lines | Select-String "save_relative_fcm_token" | Select-Object -Last 1
  if ($tl) {
    if ($tl.Line -match "[A-Za-z0-9_\-]{60,}") { Bad "suspicious long sequence in token line - maybe not masked" }
    else { Ok "token in log looks masked" }
    Write-Host ("  " + $tl.Line)
  } else { Warn "save_relative_fcm_token not found - relative not registered yet?" }
}

switch ($Step.ToLower()) {
  "1"       { Step-Install }
  "4"       { Step-Foreground }
  "5"       { Step-Killed }
  "6"       { Step-Lockscreen }
  "logs"    { Step-Logs }
  "trigger" { Trigger-Scam | Out-Null }
  default   { Bad ("unknown step: " + $Step + ". use: 1|4|5|6|logs|trigger") }
}