@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "NEWS_FLAGS=--open"
if /I "%~1"=="--scheduled" set "NEWS_FLAGS="
set "NEWS_BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%NEWS_BUNDLED_PYTHON%" (
    "%NEWS_BUNDLED_PYTHON%" "%~dp0news_digest.py" %NEWS_FLAGS%
    goto done
)
where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0news_digest.py" %NEWS_FLAGS%
    goto done
)
where python.exe >nul 2>nul
if not errorlevel 1 (
    python "%~dp0news_digest.py" %NEWS_FLAGS%
    goto done
)
echo Python 3.10+ is required. See README.md.
if defined NEWS_FLAGS pause
exit /b 1

:done
set "NEWS_EXIT=%ERRORLEVEL%"
if not "%NEWS_EXIT%"=="0" if defined NEWS_FLAGS pause
exit /b %NEWS_EXIT%
