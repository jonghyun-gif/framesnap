@echo off
chcp 65001 >nul
echo.
echo ╔═══════════════════════════════════════════╗
echo ║   FrameSnap EXE 빌드 스크립트             ║
echo ╚═══════════════════════════════════════════╝
echo.

echo [1/3] 필요 패키지 설치 중...
pip install mss pillow numpy pyinstaller --quiet
if errorlevel 1 (
    echo 패키지 설치 실패! Python/pip가 설치되어 있는지 확인하세요.
    pause
    exit /b 1
)

echo [2/3] EXE 빌드 중 (1~2분 소요)...
pyinstaller --onefile --windowed --name "FrameSnap" ^
    --hidden-import=PIL._tkinter_finder ^
    --hidden-import=mss ^
    --hidden-import=mss.windows ^
    --collect-all mss ^
    framesnap.py

if errorlevel 1 (
    echo.
    echo 빌드 실패! 오류 메시지를 확인하세요.
    pause
    exit /b 1
)

echo.
echo [3/3] 완료!
echo.
echo ✅ EXE 파일 위치: dist\FrameSnap.exe
echo.
echo 이 파일 하나만 있으면 어디서든 실행 가능합니다.
echo.
pause
