@echo off
setlocal EnableExtensions

set "DRY_RUN=0"
for %%I in ("%~dp0..") do set "ROOT=%%~fI"

:parse_args
if "%~1"=="" goto parsed_args
if /I "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
  goto parse_args
)
if /I "%~1"=="-h" goto usage
if /I "%~1"=="--help" goto usage
echo Unknown argument: %~1 1>&2
goto usage_error

:usage
echo Usage: %~nx0 [--dry-run]
echo Copies services/scanner/market_mate.db to services/scanner/backups/ without deleting old backups.
exit /b 0

:usage_error
echo Usage: %~nx0 [--dry-run] 1>&2
exit /b 2

:parsed_args
set "SRC_REL=services/scanner/market_mate.db"
set "BACKUP_DIR_REL=services/scanner/backups"
set "SRC=services\scanner\market_mate.db"
set "BACKUP_DIR=services\scanner\backups"

pushd "%ROOT%" || exit /b 1

if not exist "%SRC%" (
  echo Database not found: %SRC_REL% 1>&2
  popd
  exit /b 1
)

git -C . check-ignore -q "%BACKUP_DIR_REL%/"
if errorlevel 1 (
  echo Refusing backup because %BACKUP_DIR_REL%/ is not ignored by git. 1>&2
  popd
  exit /b 1
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "STAMP=%%I"
set "DEST_REL=%BACKUP_DIR_REL%/market_mate.db.%STAMP%.bak"
set "DEST=%BACKUP_DIR%\market_mate.db.%STAMP%.bak"

if exist "%DEST%" (
  echo Refusing to overwrite existing backup: %DEST_REL% 1>&2
  popd
  exit /b 1
)

if "%DRY_RUN%"=="1" (
  echo DRY-RUN would create %BACKUP_DIR_REL%/ if missing
  echo DRY-RUN would copy %SRC_REL% to %DEST_REL%
  popd
  exit /b 0
)

if not exist "%BACKUP_DIR%\" mkdir "%BACKUP_DIR%"
copy /B "%SRC%" "%DEST%" >nul
if errorlevel 1 (
  popd
  exit /b 1
)
echo Backed up %SRC_REL% to %DEST_REL%
popd
