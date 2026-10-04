@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

docker image inspect ring-web >nul 2>&1
if errorlevel 1 (
	echo Image "ring-web" not found locally - building it now, this can take a minute...
	docker build -t ring-web .
	if errorlevel 1 (
		echo Build failed.
		pause
		exit /b 1
	)
)

docker container inspect ring-web >nul 2>&1
if errorlevel 1 (
	echo Creating and starting container "ring-web"...
	docker run -d -p 8000:8000 --name ring-web ring-web
) else (
	for /f "usebackq delims=" %%R in (`docker container inspect -f "{{.State.Running}}" ring-web`) do set "IS_RUNNING=%%R"
	if /i "!IS_RUNNING!"=="true" (
		echo Container "ring-web" is already running.
	) else (
		echo Starting existing container "ring-web"...
		docker start ring-web >nul
	)
)

echo.
echo Open http://127.0.0.1:8000/ in your browser.
pause
