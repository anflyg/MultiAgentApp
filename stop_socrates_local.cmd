@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_socrates_local.ps1"
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Stop misslyckades med exit code %EXIT_CODE%.
)
exit /b %EXIT_CODE%
