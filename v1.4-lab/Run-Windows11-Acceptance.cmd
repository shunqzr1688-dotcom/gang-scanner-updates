@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0windows_acceptance.ps1" %*
set "GANG_TEST_EXIT=%ERRORLEVEL%"
echo.
echo Windows 11 acceptance exit code: %GANG_TEST_EXIT%
pause
exit /b %GANG_TEST_EXIT%
