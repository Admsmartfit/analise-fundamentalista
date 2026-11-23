# Desinstalador do TradingAgents B3 (chamado por "Aplicativos instalados" do Windows)
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = Join-Path $Root 'data'

Write-Host ""
Write-Host "  Desinstalar TradingAgents B3 ($Root)" -ForegroundColor Yellow
$ok = Read-Host "  Confirmar desinstalação? (S/N) [N]"
if ($ok -notmatch '^[sSyY]') { exit 0 }

$py = Join-Path $Root 'runtime\python.exe'
$launcher = Join-Path $Root 'app\launcher.py'
if ((Test-Path $py) -and (Test-Path $launcher)) {
    $env:TA_DATA_DIR = $Data
    & $py $launcher --stop 2>$null | Out-Null
    Start-Sleep -Seconds 2
}

$programs = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'
foreach ($lnk in @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'TradingAgents B3.lnk'),
        (Join-Path $programs 'TradingAgents B3.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Startup')) 'TradingAgents B3 (servidor).lnk'))) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
}
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TradingAgentsB3' -Recurse -Force -ErrorAction SilentlyContinue

foreach ($d in @('runtime', 'app', 'app_old', 'app_new', 'app_failed')) {
    $p = Join-Path $Root $d
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
foreach ($f in @('TradingAgents.ico')) {
    $p = Join-Path $Root $f
    if (Test-Path $p) { Remove-Item -Force $p }
}

$apagar = Read-Host "  Apagar também os DADOS (banco com chaves de API, histórico, backups)? (S/N) [N]"
if ($apagar -match '^[sSyY]') {
    Remove-Item -Recurse -Force $Data
    Write-Host "  Dados apagados." -ForegroundColor Green
} else {
    Write-Host "  Dados mantidos em: $Data" -ForegroundColor Green
}
Remove-Item -Force (Join-Path $Root 'uninstall.ps1') -ErrorAction SilentlyContinue
if (-not (Get-ChildItem $Root -ErrorAction SilentlyContinue)) { Remove-Item $Root -Force }
Write-Host "  TradingAgents B3 desinstalado." -ForegroundColor Green
Start-Sleep -Seconds 3
