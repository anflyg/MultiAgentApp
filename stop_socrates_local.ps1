Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

$RunDir = Join-Path $RootDir ".run"
$ApiPidFile = Join-Path $RunDir "memory_api.pid"
$NgrokPidFile = Join-Path $RunDir "ngrok.pid"
$NgrokUrlFile = Join-Path $RunDir "ngrok_public_url.txt"

function Stop-ProcessFromPidFile {
    param(
        [string]$Name,
        [string]$PidFile
    )
    if (-not (Test-Path $PidFile)) {
        Write-Host "$Name: ingen PID-fil."
        return
    }

    $pidText = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $pidText) {
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "$Name: tom PID-fil, borttagen."
        return
    }

    $pidValue = 0
    if (-not [int]::TryParse($pidText, [ref]$pidValue)) {
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "$Name: ogiltig PID-fil, borttagen."
        return
    }

    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stoppar $Name ($pidValue)..."
        Stop-Process -Id $pidValue -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 300
        if (Get-Process -Id $pidValue -ErrorAction SilentlyContinue) {
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "$Name: process $pidValue körs inte."
    }
    Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
}

Write-Host "== Stoppar Socrates lokalt (Windows) =="
Stop-ProcessFromPidFile -Name "ngrok" -PidFile $NgrokPidFile
Stop-ProcessFromPidFile -Name "memory-api" -PidFile $ApiPidFile

if (Test-Path $NgrokUrlFile) {
    Remove-Item -Path $NgrokUrlFile -Force -ErrorAction SilentlyContinue
    Write-Host "Tog bort sparad ngrok-URL: $NgrokUrlFile"
}

Write-Host "Klart."
