@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title PoE2 Helper - сборка

echo.
echo === PoE2 Helper: сборка exe ===
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python не найден в PATH.
    echo     Поставь Python 3.11 или новее с python.org
    echo     и обязательно отметь "Add python.exe to PATH".
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python -V 2^>^&1') do set PYVER=%%v
echo Python: %PYVER%

if not exist ".venv" (
    echo [1/5] Создаю виртуальное окружение...
    python -m venv .venv || goto :fail
) else (
    echo [1/5] Виртуальное окружение уже есть.
)

echo [2/5] Обновляю pip...
call .venv\Scripts\python.exe -m pip install --upgrade pip --quiet || goto :fail

echo [3/5] Ставлю зависимости (это надолго при первом запуске)...
call .venv\Scripts\python.exe -m pip install -r requirements-build.txt --quiet || goto :fail

echo [4/5] Рисую иконку...
call .venv\Scripts\python.exe tools\make_icon.py || goto :fail

echo [5/5] Собираю exe...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
call .venv\Scripts\python.exe -m PyInstaller poe2helper.spec --noconfirm --clean || goto :fail

echo.
echo === Готово ===
echo Папка с программой: %CD%\dist\PoE2Helper
echo Запуск: dist\PoE2Helper\PoE2Helper.exe
echo.
pause
exit /b 0

:fail
echo.
echo [!] Сборка сорвалась. Смотри сообщение выше.
pause
exit /b 1
