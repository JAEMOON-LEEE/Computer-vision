param([ValidateSet('start','stop','status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$RuntimeRoot = Join-Path $env:USERPROFILE '.twinsight\postgresql-17'
$Control = Join-Path $RuntimeRoot 'pgsql\bin\pg_ctl.exe'
if (-not (Test-Path -LiteralPath $Control)) { throw 'Local PostgreSQL runtime missing. See docs/postgresql.md for Docker setup.' }
$DataDirectory = Join-Path $RuntimeRoot 'data'
if ($Action -eq 'start') {
    & $Control -D $DataDirectory status *> $null
    if ($LASTEXITCODE -eq 0) { Write-Output 'PostgreSQL is already running'; exit 0 }
    & $Control -D $DataDirectory -l (Join-Path $RuntimeRoot 'postgres.log') -w start -o '-h 127.0.0.1 -p 5432'
} elseif ($Action -eq 'stop') {
    & $Control -D $DataDirectory -m fast -w stop
} else {
    & $Control -D $DataDirectory status
}
exit $LASTEXITCODE
