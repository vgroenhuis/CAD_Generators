@echo off
cd /d "%~dp0"

rem The code is copied into the Docker image at build time, so after changing any
rem code you must rebuild the image and recreate the container (a plain restart
rem keeps running the old code). run_docker.bat only builds if the image is missing.

echo Rebuilding image "ring-web"...
docker build -t ring-web .
if errorlevel 1 (
	echo Build failed.
	pause
	exit /b 1
)

docker rm -f ring-web >nul 2>&1
echo Starting container "ring-web"...
docker run -d -p 8000:8000 --name ring-web ring-web

echo.
echo Open http://127.0.0.1:8000/ in your browser (press Ctrl+F5 to bypass the cache).
pause
