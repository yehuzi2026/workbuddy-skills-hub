# -*- coding: utf-8 -*-
"""生成关闭/恢复 UAC 的批处理脚本，以 GBK 编码写入桌面，避免中文乱码。"""
import os

DESKTOP = r"C:\Users\AHS\Desktop"

DISABLE = r'''@echo off
chcp 936 >nul
title 关闭 UAC - 让所有程序获得完整管理员权限
color 0E

REM ===================== 自动提权 =====================
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [提示] 需要管理员权限，正在弹出 UAC 窗口，请点"是"...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    if errorlevel 1 (
        echo.
        echo   [失败] 自动提权未成功。
        echo          请关掉本窗口，右键本文件 -^> "以管理员身份运行"。
        echo.
        pause
    )
    exit /b
)

set "KEY=HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
set "BAK=%~dp0uac-backup.reg"

echo ==================================================================
echo          关闭 UAC —— 让所有程序以完整管理员权限运行
echo ==================================================================
echo.
echo   [当前 UAC 设置]
reg query "%KEY%" /v EnableLUA 2>nul | findstr /i "EnableLUA"
reg query "%KEY%" /v ConsentPromptBehaviorAdmin 2>nul | findstr /i "ConsentPromptBehaviorAdmin"
echo.
echo   [即将执行]
echo      1. 备份当前 UAC 设置  --^>  uac-backup.reg
echo      2. EnableLUA                = 0  （关闭 UAC）
echo      3. ConsentPromptBehaviorAdmin = 0  （不再弹提权提示）
echo      4. PromptOnSecureDesktop    = 0  （不再切换安全桌面）
echo.
echo   [重要副作用]
echo      关闭 UAC 后，Windows 商店类应用（Microsoft Store、照片、
echo      计算器、"设置"应用的部分页面等）可能无法启动。
echo      如需恢复，运行同目录下的 "恢复UAC-默认设置.bat" 并重启。
echo.
set /p GO=   确认执行？输入 Y 回车继续，直接回车取消：
if /i not "%GO%"=="Y" (
    echo.
    echo   已取消，未做任何修改。
    pause
    exit /b
)

echo.
echo   [1/4] 备份当前设置...
reg export "%KEY%" "%BAK%" /y >nul 2>&1
if exist "%BAK%" (echo         OK  -^>  %BAK%) else (echo         备份失败，仍继续执行)

echo   [2/4] 关闭 UAC...
reg add "%KEY%" /v EnableLUA /t REG_DWORD /d 0 /f >nul
if errorlevel 1 (echo         失败！请确认是以管理员身份运行) else (echo         OK)

echo   [3/4] 关闭提权提示...
reg add "%KEY%" /v ConsentPromptBehaviorAdmin /t REG_DWORD /d 0 /f >nul
reg add "%KEY%" /v PromptOnSecureDesktop /t REG_DWORD /d 0 /f >nul
echo         OK

echo   [4/4] 校验结果...
reg query "%KEY%" /v EnableLUA
echo.
echo ==================================================================
echo    完成！必须重启电脑才会生效。
echo    重启后，AHS 运行的所有程序都直接拥有完整管理员权限，
echo    不再有 UAC 弹窗，也不会再出现"拒绝访问"。
echo ==================================================================
echo.
set /p RB=   现在立刻重启？输入 Y 立即重启（5 秒后），直接回车稍后手动重启：
if /i "%RB%"=="Y" (
    echo.
    echo   正在重启...
    shutdown /r /t 5 /c "应用 UAC 设置"
) else (
    echo.
    echo   请稍后自行重启。设置已保存。
)
pause
'''

RESTORE = r'''@echo off
chcp 936 >nul
title 恢复 UAC 到默认（开启）状态
color 0A

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [提示] 需要管理员权限，正在弹出 UAC 窗口，请点"是"...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    if errorlevel 1 (
        echo.
        echo   [失败] 自动提权未成功。
        echo          请关掉本窗口，右键本文件 -^> "以管理员身份运行"。
        echo.
        pause
    )
    exit /b
)

set "KEY=HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
set "BAK=%~dp0uac-backup.reg"

echo ==================================================================
echo              恢复 UAC 到 Windows 默认设置
echo ==================================================================
echo.
echo   [当前设置]
reg query "%KEY%" /v EnableLUA 2>nul | findstr /i "EnableLUA"
echo.
set /p GO=   确认恢复？输入 Y 回车继续，直接回车取消：
if /i not "%GO%"=="Y" (
    echo   已取消。
    pause
    exit /b
)

echo.
if exist "%BAK%" (
    echo   [1/2] 检测到备份文件，从备份还原...
    reg import "%BAK%" >nul 2>&1
    if errorlevel 1 (echo         还原失败，改用默认值) else (echo         OK  -^>  %BAK%)
)

echo   [2/2] 写入 Windows 默认值...
reg add "%KEY%" /v EnableLUA /t REG_DWORD /d 1 /f >nul
reg add "%KEY%" /v ConsentPromptBehaviorAdmin /t REG_DWORD /d 5 /f >nul
reg add "%KEY%" /v PromptOnSecureDesktop /t REG_DWORD /d 1 /f >nul
echo         OK
echo.
reg query "%KEY%" /v EnableLUA
echo.
echo ==================================================================
echo   已恢复，重启后生效。
echo ==================================================================
pause
'''

for name, content in (("关闭UAC-彻底管理员权限.bat", DISABLE),
                      ("恢复UAC-默认设置.bat", RESTORE)):
    path = os.path.join(DESKTOP, name)
    with open(path, "w", encoding="gbk", newline="\r\n") as f:
        f.write(content)
    print("生成:", path, os.path.getsize(path), "bytes")
