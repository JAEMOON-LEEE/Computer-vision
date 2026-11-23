$ErrorActionPreference = 'Stop'
$labRepoRoot = $PSScriptRoot
if ((Split-Path -Qualifier $labRepoRoot) -ne 'D:') { throw '프로젝트를 D드라이브에서 실행해 주세요.' }
$labWorkspace = Split-Path -Parent $labRepoRoot
$labOutput = Join-Path $labRepoRoot 'runs\validation-lab'
New-Item -ItemType Directory -Path $labOutput -Force | Out-Null
$env:TEMP = Join-Path $labWorkspace 'tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $labWorkspace 'tools\pip-cache'
$env:YOLO_CONFIG_DIR = Join-Path $labWorkspace 'tools\ultralytics'
$env:TORCH_HOME = Join-Path $labWorkspace 'tools\torch-cache'
$env:HF_HOME = Join-Path $labWorkspace 'tools\huggingface-cache'
$env:XDG_CACHE_HOME = Join-Path $labWorkspace 'tools\cache'
$env:MPLCONFIGDIR = Join-Path $labWorkspace 'tools\matplotlib'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
# Use a dedicated local database for the existing dashboard, never the team DB.
$labDbPath = (Join-Path $labOutput 'dashboard.db').Replace('\', '/')
$env:DATABASE_URL = 'sqlite:///' + $labDbPath
$env:VITE_API_BASE = 'http://127.0.0.1:8001'
$labUrl = 'http://127.0.0.1:5174/lab'
try {
    $labHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/lab/health' -TimeoutSec 2
    $labFront = Invoke-WebRequest -Uri $labUrl -TimeoutSec 2 -UseBasicParsing
    if ($labHealth.service -eq 'manual-validation' -and $labFront.StatusCode -eq 200) { Write-Output $labUrl; exit 0 }
} catch { }
foreach ($labPort in @(8001,5174)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $labPort -ErrorAction SilentlyContinue) { throw "포트 $labPort 가 사용 중입니다. 기존 실행을 확인해 주세요." }
}
$labPython = Join-Path $labRepoRoot '.venv\Scripts\python.exe'
$labNode = (Get-Command node.exe).Source
if (-not (Test-Path -LiteralPath $labPython)) { throw '프로젝트 .venv를 먼저 설치해 주세요.' }
if (-not (Test-Path -LiteralPath (Join-Path $labRepoRoot 'frontend\node_modules\vite\bin\vite.js'))) { throw 'frontend에서 npm ci를 먼저 실행해 주세요.' }
$labApi = Start-Process -FilePath $labPython -ArgumentList @('-X','utf8','-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port','8001') -WorkingDirectory $labRepoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $labOutput 'api.stdout.log') -RedirectStandardError (Join-Path $labOutput 'api.stderr.log')
$labUi = Start-Process -FilePath $labNode -ArgumentList @('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5174','--strictPort') -WorkingDirectory (Join-Path $labRepoRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $labOutput 'ui.stdout.log') -RedirectStandardError (Join-Path $labOutput 'ui.stderr.log')
@{ api_pid=$labApi.Id; frontend_pid=$labUi.Id; url=$labUrl; logs=$labOutput; started_at=(Get-Date -Format o) } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $labOutput 'runtime.json') -Encoding utf8
$labReady = $false
for ($labAttempt=0; $labAttempt -lt 30; $labAttempt++) {
    try {
        $labCheckApi = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/lab/health' -TimeoutSec 1
        $labCheckUi = Invoke-WebRequest -Uri $labUrl -TimeoutSec 1 -UseBasicParsing
        if ($labCheckApi.service -eq 'manual-validation' -and $labCheckUi.StatusCode -eq 200) { $labReady = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 250
}
if (-not $labReady) { throw "시작을 확인하지 못했습니다. $labOutput 의 로그를 확인해 주세요." }
Write-Output $labUrl
