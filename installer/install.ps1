# Instalador do TradingAgents B3 (executado pelo TradingAgentsB3-Setup-X.Y.Z.exe)
# Instala em %LOCALAPPDATA%\TradingAgentsB3 (não precisa de administrador):
#   runtime\  Python embutido + dependências
#   app\      código do sistema (trocado pelas atualizações)
#   data\     banco, .env, cache, backups e logs (NUNCA apagado por atualização)
param(
    [Parameter(Mandatory = $true)][string]$Payload,
    [string]$InstallDir = "$env:LOCALAPPDATA\TradingAgentsB3",
    [switch]$Silent,
    [string]$Port = '',
    # Para testes/instalação automatizada: sem atalhos, sem registro no Windows, sem abrir navegador
    [switch]$NoIntegration
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Step($msg) { Write-Host "  > $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "  OK $msg" -ForegroundColor Green }
function Ask($question, $default) {
    if ($Silent) { return $default }
    $r = Read-Host "  $question [$default]"
    if ([string]::IsNullOrWhiteSpace($r)) { return $default }
    return $r.Trim()
}
function Write-Utf8NoBom($path, $text) {
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

Clear-Host
Write-Host ""
Write-Host "  ==========================================================" -ForegroundColor Yellow
Write-Host "    TradingAgents B3 - Instalador" -ForegroundColor Yellow
Write-Host "  ==========================================================" -ForegroundColor Yellow
Write-Host "  Pasta de instalação: $InstallDir"
Write-Host ""

$Root = $InstallDir
$Data = Join-Path $Root 'data'
$isUpgrade = Test-Path (Join-Path $Data '.env')

try {
    # 1. Para o servidor se já estiver instalado
    $oldPy = Join-Path $Root 'runtime\python.exe'
    $oldLauncher = Join-Path $Root 'app\launcher.py'
    if ((Test-Path $oldPy) -and (Test-Path $oldLauncher)) {
        Step 'Parando o sistema em execução...'
        $env:TA_DATA_DIR = $Data
        & $oldPy $oldLauncher --stop 2>$null | Out-Null
        Start-Sleep -Seconds 2
    }

    # 2. Extrai o pacote
    Step 'Extraindo arquivos (pode levar 1-2 minutos)...'
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    $tmp = Join-Path $Root '_install_tmp'
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Payload, $tmp)

    foreach ($d in @('runtime', 'app')) {
        $dest = Join-Path $Root $d
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        Move-Item (Join-Path $tmp $d) $dest
    }
    foreach ($old in @('app_old', 'app_new', 'app_failed')) {
        $p = Join-Path $Root $old
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
    Copy-Item (Join-Path $tmp 'uninstall.ps1') (Join-Path $Root 'uninstall.ps1') -Force
    if (Test-Path (Join-Path $tmp 'TradingAgents.ico')) {
        Copy-Item (Join-Path $tmp 'TradingAgents.ico') (Join-Path $Root 'TradingAgents.ico') -Force
    }
    Ok 'Arquivos instalados.'

    # 3. Pasta de dados e configuração (só na primeira instalação)
    foreach ($d in @($Data, (Join-Path $Data 'logs'), (Join-Path $Data 'backups'), (Join-Path $Data 'updates'))) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
    }
    $envFile = Join-Path $Data '.env'
    if (-not $isUpgrade) {
        Write-Host ""
        Write-Host "  Configuração inicial (Enter aceita o valor entre colchetes):" -ForegroundColor Yellow
        $senha = Ask 'Senha do usuário admin do Cockpit' 'admin123'
        $porta = if ($Port) { $Port } else { Ask 'Porta do Cockpit' '8000' }
        $robo = Ask 'URL do Robô Técnico (webhook de decisões)' 'http://localhost:5000/webhook/decisao'
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $secret = [Convert]::ToBase64String($bytes)
        $canal = ''
        $canalFile = Join-Path $tmp 'channel.txt'
        if (Test-Path $canalFile) { $canal = (Get-Content $canalFile -Raw).Trim() }
        $conteudo = @"
# TradingAgents B3 - configuração local (gerado pelo instalador)
SECRET_KEY=$secret
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$senha
HOST=0.0.0.0
PORT=$porta
TECHNICAL_ROBOT_WEBHOOK_URL=$robo
UPDATE_CHANNEL=$canal
"@
        Write-Utf8NoBom $envFile $conteudo
        Ok "Configuração salva em $envFile"
    } else {
        Ok 'Configuração e dados existentes mantidos.'
    }

    # Banco inicial opcional (gerado com build.py --include-db): só se ainda não houver banco
    $seedDb = Join-Path $tmp 'seed\tradingagents.db'
    $dbFile = Join-Path $Data 'tradingagents.db'
    if ((Test-Path $seedDb) -and -not (Test-Path $dbFile)) {
        Copy-Item $seedDb $dbFile
        Ok 'Banco de dados (chaves, ativos e histórico) copiado.'
    }
    Remove-Item -Recurse -Force $tmp

    $pythonw = Join-Path $Root 'runtime\pythonw.exe'
    $launcher = Join-Path $Root 'app\launcher.py'
    $icon = Join-Path $Root 'TradingAgents.ico'
    $version = (Get-Content (Join-Path $Root 'app\VERSION') -Raw).Trim()

    if ($NoIntegration) {
        Step 'Iniciando o servidor (modo sem integração)...'
        $env:TA_DATA_DIR = $Data
        & (Join-Path $Root 'runtime\python.exe') $launcher --background
        Ok "TradingAgents B3 $version instalado em $Root"
        exit 0
    }

    # 4. Atalhos
    Step 'Criando atalhos...'
    $shell = New-Object -ComObject WScript.Shell
    function New-Shortcut($path, $arguments, $description) {
        $s = $shell.CreateShortcut($path)
        $s.TargetPath = $pythonw
        $s.Arguments = $arguments
        $s.WorkingDirectory = $Root
        $s.Description = $description
        if (Test-Path $icon) { $s.IconLocation = $icon }
        $s.Save()
    }
    $desktop = [Environment]::GetFolderPath('Desktop')
    $programs = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'
    New-Shortcut (Join-Path $desktop 'TradingAgents B3.lnk') "`"$launcher`"" 'Abrir o Cockpit do TradingAgents B3'
    New-Shortcut (Join-Path $programs 'TradingAgents B3.lnk') "`"$launcher`"" 'Abrir o Cockpit do TradingAgents B3'

    $startupLnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'TradingAgents B3 (servidor).lnk'
    $autoDefault = 'S'
    if ($isUpgrade -and -not (Test-Path $startupLnk)) { $autoDefault = 'N' }
    $auto = Ask 'Iniciar o servidor automaticamente ao ligar o Windows? (S/N)' $autoDefault
    if ($auto -match '^[sSyY]') {
        New-Shortcut $startupLnk "`"$launcher`" --background" 'Servidor TradingAgents B3 (24/7)'
        Ok 'Início automático com o Windows ativado.'
    } elseif (Test-Path $startupLnk) {
        Remove-Item $startupLnk -Force
    }

    # 5. Registro em "Aplicativos instalados" (desinstalação pelo Windows)
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TradingAgentsB3'
    New-Item -Path $key -Force | Out-Null
    $uninstallCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Root\uninstall.ps1`""
    Set-ItemProperty $key -Name DisplayName -Value 'TradingAgents B3'
    Set-ItemProperty $key -Name DisplayVersion -Value $version
    Set-ItemProperty $key -Name Publisher -Value 'TradingAgents B3'
    Set-ItemProperty $key -Name InstallLocation -Value $Root
    Set-ItemProperty $key -Name UninstallString -Value $uninstallCmd
    Set-ItemProperty $key -Name NoModify -Value 1 -Type DWord
    Set-ItemProperty $key -Name NoRepair -Value 1 -Type DWord
    if (Test-Path $icon) { Set-ItemProperty $key -Name DisplayIcon -Value $icon }

    # 6. Inicia
    Step 'Iniciando o sistema...'
    $env:TA_DATA_DIR = $Data
    Start-Process -FilePath $pythonw -ArgumentList "`"$launcher`"" -WorkingDirectory $Root
    Write-Host ""
    Write-Host "  ==========================================================" -ForegroundColor Green
    Write-Host "    TradingAgents B3 $version instalado com sucesso!" -ForegroundColor Green
    Write-Host "  ==========================================================" -ForegroundColor Green
    Write-Host "  O Cockpit vai abrir no navegador em alguns segundos."
    Write-Host "  Atalho criado na Área de Trabalho: 'TradingAgents B3'."
    Write-Host "  Dados e configuração: $Data"
    Write-Host ""
    if (-not $Silent) { Start-Sleep -Seconds 6 }
    exit 0
}
catch {
    Write-Host ""
    Write-Host "  ERRO na instalação: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    if (-not $Silent) { Read-Host '  Pressione Enter para fechar' | Out-Null }
    exit 1
}
