@echo off
chcp 65001 > nul
title iPhone転売利益計算ツール

echo ============================================
echo  iPhone転売利益計算ツール 起動スクリプト
echo ============================================
echo.

:: Pythonの確認（py ランチャー優先）
py --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=py
    goto :found
)
python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON=python
    goto :found
)
echo [エラー] Pythonが見つかりません。
echo Microsoft Store または https://www.python.org/downloads/ からインストールしてください。
pause
exit /b 1

:found
echo [OK] Python が見つかりました
echo.

:: 依存パッケージのインストール
echo 依存パッケージをインストール中...
%PYTHON% -m pip install -r requirements.txt -q
echo [OK] パッケージのインストール完了
echo.

:: サーバー起動
echo ブラウザで http://localhost:5000 を開いてください
echo 終了するには Ctrl+C を押してください
echo.
start "" "http://localhost:5000"
%PYTHON% app.py

pause
