Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

$DbPath = if ($env:DB_PATH) { $env:DB_PATH } else { ".\SocratesTest.db" }
$HostName = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$Port = [int](if ($env:PORT) { $env:PORT } else { "8001" })
$ApiToken = if ($env:MULTI_AGENT_APP_API_TOKEN) { $env:MULTI_AGENT_APP_API_TOKEN } else { "dev-secret" }

$LogDir = Join-Path $RootDir "logs"
$RunDir = Join-Path $RootDir ".run"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

$ApiLog = Join-Path $LogDir "memory_api.log"
$NgrokLog = Join-Path $LogDir "ngrok.log"
$ApiPidFile = Join-Path $RunDir "memory_api.pid"
$NgrokPidFile = Join-Path $RunDir "ngrok.pid"
$NgrokUrlFile = Join-Path $RunDir "ngrok_public_url.txt"

$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Fel: .venv\Scripts\python.exe saknas. Skapa venv och installera beroenden först."
}

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    throw "Fel: ngrok hittades inte i PATH."
}

function Stop-ProcessFromPidFile {
    param(
        [string]$Name,
        [string]$PidFile
    )
    if (-not (Test-Path $PidFile)) { return }
    $pidText = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $pidText) {
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        return
    }
    $pidValue = 0
    if (-not [int]::TryParse($pidText, [ref]$pidValue)) {
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        return
    }
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stoppar gammal $Name-process ($pidValue)..."
        Stop-Process -Id $pidValue -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 300
        if (Get-Process -Id $pidValue -ErrorAction SilentlyContinue) {
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
}

function Test-HealthStatusOk {
    param(
        [string]$BaseUrl
    )
    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/health" -Headers @{ Authorization = "Bearer $ApiToken" } -Method Get -TimeoutSec 3
        return ($null -ne $response -and $response.status -eq "ok")
    } catch {
        return $false
    }
}

function Get-ListeningPids {
    param(
        [int]$PortToCheck
    )
    $lines = netstat -ano -p tcp | Select-String -Pattern "LISTENING"
    $pidList = @()
    foreach ($line in $lines) {
        $text = ($line.ToString() -replace "\s+", " ").Trim()
        if ($text -match "[:\.]$PortToCheck\s") {
            $parts = $text.Split(" ")
            $pid = $parts[$parts.Length - 1]
            if ($pid -match "^\d+$" -and -not $pidList.Contains($pid)) {
                $pidList += $pid
            }
        }
    }
    return $pidList
}

function Get-NgrokPublicHttpsUrl {
    try {
        $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -Method Get -TimeoutSec 3
        foreach ($tunnel in $tunnels.tunnels) {
            if ($tunnel.public_url -and $tunnel.public_url.StartsWith("https://")) {
                return [string]$tunnel.public_url
            }
        }
        return ""
    } catch {
        return ""
    }
}

Write-Host "== Socrates local startup (Windows) =="
Write-Host "Projekt: $RootDir"
Write-Host "Databas: $DbPath"
Write-Host "API: http://$HostName`:$Port"
Write-Host ""

Stop-ProcessFromPidFile -Name "api" -PidFile $ApiPidFile
Stop-ProcessFromPidFile -Name "ngrok" -PidFile $NgrokPidFile

if (-not (Test-Path $DbPath)) {
    New-Item -Path $DbPath -ItemType File -Force | Out-Null
}

$portPids = Get-ListeningPids -PortToCheck $Port
if ($portPids.Count -gt 0) {
    throw "Fel: port $Port används redan av PID: $($portPids -join ', ')"
}

$env:PYTHONPATH = "src"
$env:MULTI_AGENT_APP_API_TOKEN = $ApiToken

& $VenvPython -c "from multi_agent_app.storage import Storage; s=Storage(db_path=r'$DbPath'); s.close(); print('Database ready:', r'$DbPath')"

Write-Host "Startar lokalt memory API..."
$apiProcess = Start-Process -FilePath $VenvPython -ArgumentList @("-m", "multi_agent_app.cli", "--db-path", $DbPath, "serve-memory-api", "--host", $HostName, "--port", "$Port") -PassThru -WindowStyle Hidden -RedirectStandardOutput $ApiLog -RedirectStandardError $ApiLog
$apiProcess.Id | Set-Content -Path $ApiPidFile
Start-Sleep -Milliseconds 400

if (-not (Get-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue)) {
    throw "Fel: API-processen avslutades direkt. Se logg: $ApiLog"
}

Write-Host "Väntar på lokalt API..."
$localOk = $false
for ($i = 0; $i -lt 20; $i++) {
    if (-not (Get-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue)) {
        throw "Fel: API-processen avslutades under uppstart. Se logg: $ApiLog"
    }
    if (Test-HealthStatusOk -BaseUrl "http://$HostName`:$Port") {
        $localOk = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $localOk) {
    throw "Fel: lokalt API svarar inte med status=ok. Se logg: $ApiLog"
}
Write-Host "Lokalt API svarar."

Write-Host "Startar ngrok..."
$ngrokProcess = Start-Process -FilePath "ngrok" -ArgumentList @("http", "$Port") -PassThru -WindowStyle Hidden -RedirectStandardOutput $NgrokLog -RedirectStandardError $NgrokLog
$ngrokProcess.Id | Set-Content -Path $NgrokPidFile

Write-Host "Väntar på ngrok inspect API..."
$publicUrl = ""
for ($i = 0; $i -lt 30; $i++) {
    $publicUrl = Get-NgrokPublicHttpsUrl
    if ($publicUrl) { break }
    Start-Sleep -Seconds 1
}
if (-not $publicUrl) {
    throw "Fel: kunde inte läsa publik ngrok-URL. Se logg: $NgrokLog"
}
$publicUrl | Set-Content -Path $NgrokUrlFile

Write-Host "Väntar på publik ngrok-endpoint..."
$publicOk = $false
for ($i = 0; $i -lt 20; $i++) {
    if (Test-HealthStatusOk -BaseUrl $publicUrl) {
        $publicOk = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $publicOk) {
    throw "Fel: publik health svarar inte med status=ok. Se loggar: $ApiLog och $NgrokLog"
}

Write-Host ""
Write-Host "===== KLART ====="
Write-Host "Lokal URL: http://$HostName`:$Port"
Write-Host "Publik URL: $publicUrl"
Write-Host "Publik URL sparad i: $NgrokUrlFile"
Write-Host "Loggar:"
Write-Host "  $ApiLog"
Write-Host "  $NgrokLog"
Write-Host ""
Write-Host "Stoppa med:"
Write-Host "  .\stop_socrates_local.ps1"
