@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "CONFIRM=0"
for %%I in ("%~dp0..") do set "ROOT=%%~fI"

:parse_args
if "%~1"=="" goto parsed_args
if /I "%~1"=="--yes" (
  set "CONFIRM=1"
  shift
  goto parse_args
)
if /I "%~1"=="-h" goto usage
if /I "%~1"=="--help" goto usage
echo Unknown argument: %~1 1>&2
goto usage_error

:usage
echo Usage: %~nx0 [--yes]
echo Dry-run is the default. Pass --yes to delete only the allowlisted local artifacts.
exit /b 0

:usage_error
echo Usage: %~nx0 [--yes] 1>&2
exit /b 2

:parsed_args
call :DeleteDir "apps/web/.next" || exit /b 1
call :DeleteDir "apps/web/node_modules/.vite" || exit /b 1
call :DeleteFile "apps/web/tsconfig.tsbuildinfo" || exit /b 1

set "CACHE_DIR=%ROOT%\services\scanner\var\cache"
set "CACHE_FOUND=0"
if exist "%CACHE_DIR%\" (
  for %%F in ("%CACHE_DIR%\*.json") do (
    if exist "%%~fF" (
      set "CACHE_FOUND=1"
      call :DeleteCacheFile "%%~fF" || exit /b 1
    )
  )
)

if "%CACHE_FOUND%"=="0" echo SKIP missing services/scanner/var/cache/*.json

if "%CONFIRM%"=="1" (
  echo Cleanup complete.
) else (
  echo Dry-run only. Re-run with --yes to delete the listed paths.
)
exit /b 0

:AssertAllowed
set "CHECK=%~1"
if "%CHECK%"=="apps/web/.next/" exit /b 0
if "%CHECK%"=="apps/web/node_modules/.vite/" exit /b 0
if "%CHECK%"=="apps/web/tsconfig.tsbuildinfo" exit /b 0
if /I "%CHECK:~0,27%"=="services/scanner/var/cache/" if /I "%CHECK:~-5%"==".json" exit /b 0
echo Refusing cleanup target outside allowlist: %CHECK% 1>&2
exit /b 1

:PrintTarget
if "%CONFIRM%"=="1" (
  echo DELETE %~1
) else (
  echo DRY-RUN would delete %~1
)
exit /b 0

:DeleteDir
set "REL=%~1"
set "DISPLAY=%REL%/"
call :AssertAllowed "%DISPLAY%" || exit /b 1
set "TARGET=%ROOT%\%REL:/=\%"
if exist "%TARGET%\" (
  call :PrintTarget "%DISPLAY%"
  if "%CONFIRM%"=="1" rmdir /s /q "%TARGET%"
) else (
  echo SKIP missing %DISPLAY%
)
exit /b 0

:DeleteFile
set "REL=%~1"
call :AssertAllowed "%REL%" || exit /b 1
set "TARGET=%ROOT%\%REL:/=\%"
if exist "%TARGET%" (
  call :PrintTarget "%REL%"
  if "%CONFIRM%"=="1" del /f /q "%TARGET%"
) else (
  echo SKIP missing %REL%
)
exit /b 0

:DeleteCacheFile
set "TARGET=%~1"
for %%N in ("%TARGET%") do set "NAME=%%~nxN"
set "REL=services/scanner/var/cache/%NAME%"
call :AssertAllowed "%REL%" || exit /b 1
call :PrintTarget "%REL%"
if "%CONFIRM%"=="1" del /f /q "%TARGET%"
exit /b 0
