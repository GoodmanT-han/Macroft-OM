@echo off
setlocal
chcp 65001 >nul 2>&1
title CNN BBC G1 - 每日新闻简报
set "PYTHONUTF8=1"
set "NEWS_FLAGS=--open"
if /I "%~1"=="--scheduled" set "NEWS_FLAGS="
set "NEWS_EXIT=1"
set "NEWS_PY_ARGS="

echo 正在启动 CNN、BBC、G1 每日新闻简报...
if not exist "%~dp0news_digest.py" (
    echo 找不到 news_digest.py。请完整解压 ZIP，再从同一文件夹启动 start.cmd。
    goto finish
)

set "NEWS_CHECK=import sys, certifi; from zoneinfo import ZoneInfo; ZoneInfo('America/Sao_Paulo'); sys.exit(sys.version_info < (3, 10))"
set "NEWS_PY=%~dp0.venv\Scripts\python.exe"
if exist "%NEWS_PY%" (
    "%NEWS_PY%" -c "%NEWS_CHECK%" >nul 2>&1
    if not errorlevel 1 goto run
)
set "NEWS_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%NEWS_PY%" (
    "%NEWS_PY%" -c "%NEWS_CHECK%" >nul 2>&1
    if not errorlevel 1 goto run
)

set "NEWS_PY=py.exe"
set "NEWS_PY_ARGS=-3"
"%NEWS_PY%" %NEWS_PY_ARGS% -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto check_system
set "NEWS_PY=python.exe"
set "NEWS_PY_ARGS="
"%NEWS_PY%" -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto check_system
echo 未找到可用的 Python 3.10 或更新版本。请按 README.md 安装 Python 后重试。
goto finish

:check_system
"%NEWS_PY%" %NEWS_PY_ARGS% -c "%NEWS_CHECK%" >nul 2>&1
if not errorlevel 1 goto run
if not exist "%~dp0requirements.txt" (
    echo 找不到 requirements.txt。请完整解压 ZIP 后重试。
    goto finish
)
echo 首次运行，正在为这个文件夹安装所需组件...
"%NEWS_PY%" %NEWS_PY_ARGS% -m venv "%~dp0.venv"
if errorlevel 1 goto setup_failed
set "NEWS_PY=%~dp0.venv\Scripts\python.exe"
set "NEWS_PY_ARGS="
"%NEWS_PY%" -m pip --disable-pip-version-check install --timeout 15 --retries 1 -r "%~dp0requirements.txt"
if errorlevel 1 goto setup_failed

:run
echo 正在读取新闻源...
"%NEWS_PY%" %NEWS_PY_ARGS% -u "%~dp0news_digest.py" %NEWS_FLAGS%
set "NEWS_EXIT=%ERRORLEVEL%"
if not "%NEWS_EXIT%"=="0" echo 运行遇到问题，请查看上面的错误信息。
goto finish

:setup_failed
echo 组件安装失败。请查看上面的错误信息。

:finish
if defined NEWS_FLAGS pause
exit /b %NEWS_EXIT%
