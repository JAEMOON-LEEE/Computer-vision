$ErrorActionPreference = 'Stop'
$labState = Join-Path $PSScriptRoot 'runs\validation-lab\runtime.json'
if (-not (Test-Path -LiteralPath $labState)) { Write-Output '검증 대시보드 실행 기록이 없습니다.'; exit 0 }
$labRuntime = Get-Content -LiteralPath $labState -Raw | ConvertFrom-Json
$labStarted = [DateTimeOffset]::Parse($labRuntime.started_at)
$labProcesses = Get-CimInstance Win32_Process
$labStopIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($labRootId in @($labRuntime.api_pid, $labRuntime.frontend_pid)) {
    $labProcess = $labProcesses | Where-Object { $_.ProcessId -eq $labRootId } | Select-Object -First 1
    if (-not $labProcess) { continue }
    $labAgeGap = [Math]::Abs((([DateTimeOffset]$labProcess.CreationDate) - $labStarted).TotalSeconds)
    if ($labAgeGap -gt 15 -or ($labProcess.CommandLine -notlike '*backend.app.main:app*' -and $labProcess.CommandLine -notlike '*node_modules/vite/bin/vite.js*')) { throw '실행 기록과 현재 프로세스가 달라 자동 종료하지 않았습니다.' }
    [void]$labStopIds.Add([int]$labRootId)
}
do {
    $labAdded = $false
    foreach ($labProcess in $labProcesses) {
        if ($labStopIds.Contains([int]$labProcess.ParentProcessId) -and $labStopIds.Add([int]$labProcess.ProcessId)) { $labAdded = $true }
    }
} while ($labAdded)
foreach ($labStopId in $labStopIds) { Stop-Process -Id $labStopId -ErrorAction SilentlyContinue }
Write-Output '이 대시보드의 API·화면 프로세스만 종료했습니다. 결과 파일은 D드라이브에 보존됩니다.'
