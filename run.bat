@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem AnNha launcher for Windows. Keep messages ASCII for cmd.exe compatibility.
pushd "%~dp0" || exit /b 1
if "%~1"=="" goto interactive
call :dispatch "%~1" "%~2"
set "ANNHA_EXIT=%errorlevel%"
popd
exit /b %ANNHA_EXIT%

:interactive
call :menu
popd
exit /b 0

:compose
docker compose --project-directory "%CD%" --env-file "%CD%\.env" -f "%CD%\compose.yaml" %*
exit /b %errorlevel%

:prepare
where docker >nul 2>&1
if errorlevel 1 (
  echo [LOI] Chua cai Docker. Hay cai Docker Desktop.
  exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  echo [LOI] Can Docker Compose v2 tro len.
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo [LOI] Docker chua chay. Hay mo Docker Desktop.
  exit /b 1
)
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  if errorlevel 1 exit /b 1
  echo [INFO] Da tao .env tu .env.example.
)
call :compose config --quiet
exit /b %errorlevel%

:dispatch
if /i "%~1"=="help" goto help
if /i "%~1"=="--help" goto help
if /i "%~1"=="-h" goto help
if /i "%~1"=="up" goto up
if /i "%~1"=="start" goto quick_start
if /i "%~1"=="stop" goto stop_app
if /i "%~1"=="recreate" goto recreate
if /i "%~1"=="status" goto status
if /i "%~1"=="logs" goto logs
if /i "%~1"=="web" goto web
if /i "%~1"=="mail" goto mail
if /i "%~1"=="check" goto check
echo [LOI] Lenh khong hop le. Dung run.bat help.
exit /b 2

:up
call :prepare
if errorlevel 1 exit /b 1
call :compose up --build -d --wait --wait-timeout 120
if errorlevel 1 exit /b 1
call :show_urls
exit /b 0

:quick_start
call :prepare
if errorlevel 1 exit /b 1
call :compose up -d --wait --wait-timeout 120
if errorlevel 1 exit /b 1
call :show_urls
exit /b 0

:stop_app
call :prepare
if errorlevel 1 exit /b 1
call :compose stop
exit /b %errorlevel%

:recreate
call :prepare
if errorlevel 1 exit /b 1
call :compose up -d --force-recreate --wait --wait-timeout 120
if errorlevel 1 exit /b 1
call :show_urls
exit /b 0

:status
call :prepare
if errorlevel 1 exit /b 1
call :compose ps --all
exit /b %errorlevel%

:logs
set "ANNHA_LOG_SERVICE="
if "%~2"=="" goto logs_ready
if /i "%~2"=="backend" set "ANNHA_LOG_SERVICE=backend"
if /i "%~2"=="frontend" set "ANNHA_LOG_SERVICE=frontend"
if /i "%~2"=="mqtt" set "ANNHA_LOG_SERVICE=mqtt"
if /i "%~2"=="mailpit" set "ANNHA_LOG_SERVICE=mailpit"
if not defined ANNHA_LOG_SERVICE (
  echo [LOI] Service log: backend, frontend, mqtt hoac mailpit.
  exit /b 2
)
:logs_ready
call :prepare
if errorlevel 1 exit /b 1
call :compose logs --tail 100 --follow %ANNHA_LOG_SERVICE%
exit /b %errorlevel%

:web
call :prepare
if errorlevel 1 exit /b 1
call :open_page frontend 80
exit /b %errorlevel%

:mail
call :prepare
if errorlevel 1 exit /b 1
call :open_page mailpit 8025
exit /b %errorlevel%

:check
call :prepare
if errorlevel 1 exit /b 1
echo [OK] Docker dang chay; cau hinh Compose hop le.
exit /b 0

:show_urls
set "ANNHA_WEB_ADDRESS="
set "ANNHA_MAIL_ADDRESS="
for /f "delims=" %%P in ('docker compose --project-directory "%CD%" --env-file "%CD%\.env" -f "%CD%\compose.yaml" port frontend 80 2^>nul') do set "ANNHA_WEB_ADDRESS=%%P"
for /f "delims=" %%P in ('docker compose --project-directory "%CD%" --env-file "%CD%\.env" -f "%CD%\compose.yaml" port mailpit 8025 2^>nul') do set "ANNHA_MAIL_ADDRESS=%%P"
if defined ANNHA_WEB_ADDRESS echo Ung dung AnNha: http://%ANNHA_WEB_ADDRESS%
if defined ANNHA_MAIL_ADDRESS echo Hop thu xac minh: http://%ANNHA_MAIL_ADDRESS%
exit /b 0

:open_page
set "ANNHA_ADDRESS="
for /f "delims=" %%P in ('docker compose --project-directory "%CD%" --env-file "%CD%\.env" -f "%CD%\compose.yaml" port %1 %2 2^>nul') do set "ANNHA_ADDRESS=%%P"
if not defined ANNHA_ADDRESS (
  echo [LOI] Dich vu chua chay. Hay khoi dong ung dung truoc.
  exit /b 1
)
echo http://%ANNHA_ADDRESS%
start "" "http://%ANNHA_ADDRESS%"
exit /b %errorlevel%

:help
echo AnNha - Camera giam sat gia dinh
echo.
echo   run.bat                  Menu tuong tac
echo   run.bat up               Build va chay toan bo
echo   run.bat start            Chay nhanh bang image hien co
echo   run.bat stop             Dung container, giu du lieu
echo   run.bat recreate         Tao lai container va nap lai .env
echo   run.bat status           Xem trang thai
echo   run.bat logs [service]   Theo doi log
echo   run.bat web              Mo ung dung
echo   run.bat mail             Mo hop thu xac minh
echo   run.bat check            Kiem tra Docker va cau hinh
echo.
echo Cong mac dinh: web 8188, hop thu 8125. Doi trong .env.
echo Script khong xoa volume, seed/reset du lieu, hoac chay AI tren host.
exit /b 0

:menu
echo.
echo ====================================================
echo   ANNHA - CAMERA GIAM SAT GIA DINH
echo ====================================================
echo   [1] Build va chay toan bo - mac dinh
echo   [2] Chay nhanh bang image hien co
echo   [3] Dung ung dung - giu du lieu
echo   [4] Tao lai container / nap lai .env - giu du lieu
echo   [5] Xem trang thai
echo   [6] Xem log - Ctrl+C de thoat
echo   [7] Mo ung dung tren trinh duyet
echo   [8] Mo hop thu xac minh
echo   [9] Kiem tra Docker / Compose
echo   [0] Thoat
echo.
set "ANNHA_CHOICE="
set /p "ANNHA_CHOICE=Chon [0-9] (mac dinh: 1): "
if not defined ANNHA_CHOICE set "ANNHA_CHOICE=1"
if "%ANNHA_CHOICE%"=="0" exit /b 0
set "ANNHA_ACTION="
if "%ANNHA_CHOICE%"=="1" set "ANNHA_ACTION=up"
if "%ANNHA_CHOICE%"=="2" set "ANNHA_ACTION=start"
if "%ANNHA_CHOICE%"=="3" set "ANNHA_ACTION=stop"
if "%ANNHA_CHOICE%"=="4" set "ANNHA_ACTION=recreate"
if "%ANNHA_CHOICE%"=="5" set "ANNHA_ACTION=status"
if "%ANNHA_CHOICE%"=="6" set "ANNHA_ACTION=logs"
if "%ANNHA_CHOICE%"=="7" set "ANNHA_ACTION=web"
if "%ANNHA_CHOICE%"=="8" set "ANNHA_ACTION=mail"
if "%ANNHA_CHOICE%"=="9" set "ANNHA_ACTION=check"
if not defined ANNHA_ACTION (
  echo Lua chon khong hop le.
  goto menu
)
call :dispatch "%ANNHA_ACTION%"
if errorlevel 1 echo [LOI] Thao tac chua hoan tat. Xem thong bao phia tren.
pause
goto menu
