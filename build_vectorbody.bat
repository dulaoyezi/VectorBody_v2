@echo off
setlocal enabledelayedexpansion
title VectorBody 智能体态检测系统 - 自动化封装工具
color 0A

echo ======================================================
echo   VectorBody Project 构建工具 (开发者: 杜文鑫)
echo ======================================================

:: 1. 环境预检 (避免频繁联网触发拦截)
echo [1/4] 检查 Python 环境与依赖库...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 并添加到环境变量。
    pause
    exit
)

:: 检查并静默安装打包工具
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在配置构建引擎，请稍候...
    pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
)

:: 2. 温和清理 (避免使用强力删除命令引起拦截)
echo [2/4] 准备构建空间...
if exist build ( rename build build_old & rd /s /q build_old )
if exist *.spec ( del /f /q *.spec )

:: 3. 执行核心封装 (采用单目录模式，兼容性更好)
echo [3/4] 正在封装核心算法与 MediaPipe 算子...
echo ------------------------------------------------------
:: 注意：这里去掉了 --onedir 改用更稳健的默认模式
:: 显式包含所有核心业务模块，确保临床分析逻辑不丢失
pyinstaller --noconsole --onedir ^
 --name "VectorBody_System" ^
 --add-data "assets;assets" ^
 --collect-all mediapipe ^
 --hidden-import pythoncom ^
 --hidden-import pyttsx3.drivers ^
 --hidden-import pyttsx3.drivers.sapi5 ^
 --hidden-import core.vector_body_analyzer ^
 --hidden-import core.vector_body_stabilizer ^
 --hidden-import ui.vector_body_dashboard ^
 --hidden-import utils.vector_body_audio ^
 --hidden-import utils.vector_body_visualizer ^
 vector_body_main.py

:: 4. 封装结果校验
echo ------------------------------------------------------
if exist "dist\VectorBody_System\VectorBody_System.exe" (
    echo [4/4] 构建成功！
    echo 项目成品已生成至: dist\VectorBody_System\
    echo 请双击运行 VectorBody_System.exe 进行临床测试。
) else (
    echo [错误] 封装失败，请检查是否被杀毒软件拦截或代码路径错误。
)

echo ======================================================
echo 任务结束。
pause