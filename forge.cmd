@echo off
rem forge.cmd -- Windows batch wrapper for the Forge CLI
rem Usage: forge <command> [options]
rem This is equivalent to: python forge <command>

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [error] Python not found. Install from https://www.python.org/downloads/windows/
    exit /b 1
)

python "%~dp0forge" %*
