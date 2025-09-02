@echo off
setlocal ENABLEDELAYEDEXPANSION


REM 1) 가상환경(선택)
REM py -m venv .venv
REM call .venv\Scripts\activate


REM 2) 의존성
python -m pip install --upgrade pip >nul 2>&1
pip install ezdxf pyshp pyinstaller >nul 2>&1


REM 3) PyInstaller로 spec 빌드 (최적 옵션은 spec에 반영됨)
pyinstaller DXF_to_SHP_v0.02_ultralight.spec --noconfirm
if errorlevel 1 goto :FAIL


REM 4) UPX 경로 (설치 경로에 맞게 수정)
set UPX=C:\upx\upx.exe
if not exist "%UPX%" (
echo [경고] UPX가 없어서 추가 압축을 건너뜁니다. ^(C:\upx\upx.exe 예상^)
goto :DONE
)


REM 5) dist 폴더 내 exe/dll/pyd 전체 재압축 (추가 20~30%% 기대)
for /r "%CD%\dist" %%F in (*.exe *.dll *.pyd) do (
"%UPX%" -9 --lzma "%%F" >nul 2>&1
)


echo.
echo [완료] dist 폴더를 배포하세요.
goto :EOF


:FAIL
echo 빌드 실패
exit /b 1


:DONE
endlocal