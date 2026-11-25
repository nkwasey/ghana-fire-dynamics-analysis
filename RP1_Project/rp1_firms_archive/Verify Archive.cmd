@echo off
setlocal
title Ghana Fire Archive - Verify Prepared Files
where conda >nul 2>&1
if errorlevel 1 (
  echo Open Anaconda Prompt and create the environment using environment.yml first.
  pause
  exit /b 1
)
call conda run --no-capture-output -n ghana-fire-archive python "%~dp0archive.py" verify --config "%~dp0configs\archive.yaml" %*
set "ARCHIVE_EXIT=%ERRORLEVEL%"
if not "%ARCHIVE_EXIT%"=="0" pause
exit /b %ARCHIVE_EXIT%
