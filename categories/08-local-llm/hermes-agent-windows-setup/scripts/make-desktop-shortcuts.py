# -*- coding: utf-8 -*-
"""在桌面生成 Hermes Agent 使用入口（bat 启动器 + 使用说明）。
bat 内容全 ASCII、CRLF 换行，规避中文编码坑；文件名用中文，便于识别。
"""
import os
from pathlib import Path
import shutil
import sys

desktop = Path(os.environ['USERPROFILE']) / 'Desktop'
if not desktop.is_dir():
    print('FAIL: desktop not found ->', desktop)
    sys.exit(1)

folder = desktop / 'Hermes Agent'
folder.mkdir(parents=True, exist_ok=True)
print('TARGET FOLDER =', folder)

COMMON = (
    '@echo off\r\n'
    'chcp 65001 >nul 2>&1\r\n'
    'setlocal\r\n'
    'set "HERMES_HOME=%LOCALAPPDATA%\\hermes"\r\n'
    'set "PATH=%HERMES_HOME%\\bin;%HERMES_HOME%\\git\\cmd;%HERMES_HOME%\\git\\bin;'
    '%HERMES_HOME%\\git\\usr\\bin;%LOCALAPPDATA%\\Programs\\Cua\\cua-driver\\bin;%PATH%"\r\n'
)

# ---------- 1) 启动 Hermes ----------
start_bat = COMMON + (
    'title Hermes Agent\r\n'
    'findstr /B /C:"DEEPSEEK_API_KEY=sk-" "%HERMES_HOME%\\.env" >nul 2>&1\r\n'
    'if errorlevel 1 (\r\n'
    '  echo.\r\n'
    '  echo   [!] DeepSeek API key is NOT set yet.\r\n'
    '  echo   [!] Please run  "Fill API Key.bat"  first.\r\n'
    '  echo.\r\n'
    '  pause\r\n'
    '  exit /b 1\r\n'
    ')\r\n'
    'echo.\r\n'
    'echo   Starting Hermes Agent ...\r\n'
    'echo.\r\n'
    '"%HERMES_HOME%\\bin\\hermes.exe" %*\r\n'
    'echo.\r\n'
    'echo   [Hermes exited]\r\n'
    'echo.\r\n'
    'pause\r\n'
)

# ---------- 2) 填 API Key ----------
fill_bat = COMMON + (
    'title Fill DeepSeek API Key\r\n'
    'echo ==========================================================\r\n'
    'echo    Fill DeepSeek API Key\r\n'
    'echo ==========================================================\r\n'
    'echo.\r\n'
    'echo   Get a key at:  https://platform.deepseek.com/api_keys\r\n'
    'echo.\r\n'
    'echo   Paste the key below, then press Enter.\r\n'
    'echo   (Right-click inside this window to paste)\r\n'
    'echo.\r\n'
    'set "NEWKEY="\r\n'
    'set /p "NEWKEY=  Key: "\r\n'
    'if "%NEWKEY%"=="" goto :empty\r\n'
    'echo.\r\n'
    'powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Join-Path $env:LOCALAPPDATA \'hermes\\.env\'; '
    '$k=$env:NEWKEY; '
    '$lines=@(Get-Content -LiteralPath $p -Encoding UTF8); '
    '$o=New-Object System.Collections.ArrayList; $hit=$false; '
    'foreach($l in $lines){ if($l.StartsWith(\'DEEPSEEK_API_KEY=\')){ [void]$o.Add(\'DEEPSEEK_API_KEY=\'+$k); $hit=$true } else { [void]$o.Add($l) } }; '
    'if(-not $hit){ [void]$o.Add(\'DEEPSEEK_API_KEY=\'+$k) }; '
    '[System.IO.File]::WriteAllLines($p,$o,(New-Object System.Text.UTF8Encoding($false))); '
    'Write-Host (\'  [OK] key saved. replaced existing line: \' + $hit)"\r\n'
    'echo.\r\n'
    'echo   Next: run  "Hermes Checkup.bat"  to verify.\r\n'
    'echo.\r\n'
    'pause\r\n'
    'exit /b 0\r\n'
    '\r\n'
    ':empty\r\n'
    'echo.\r\n'
    'echo   [!] Nothing entered. No change made.\r\n'
    'echo.\r\n'
    'pause\r\n'
    'exit /b 1\r\n'
)

# ---------- 3) 体检 ----------
check_bat = COMMON + (
    'title Hermes Checkup\r\n'
    'echo.\r\n'
    'echo   ===== hermes doctor =====\r\n'
    'echo.\r\n'
    '"%HERMES_HOME%\\bin\\hermes.exe" doctor\r\n'
    'echo.\r\n'
    'echo   ===== current model config =====\r\n'
    'echo.\r\n'
    '"%HERMES_HOME%\\bin\\hermes.exe" config get model.provider\r\n'
    '"%HERMES_HOME%\\bin\\hermes.exe" config get model.default\r\n'
    '"%HERMES_HOME%\\bin\\hermes.exe" config get model.base_url\r\n'
    'echo.\r\n'
    'echo   ===== one-shot chat test =====\r\n'
    'echo.\r\n'
    '"%HERMES_HOME%\\bin\\hermes.exe" -z "reply with exactly: hermes-ok"\r\n'
    'echo.\r\n'
    'pause\r\n'
)

# ---------- 4) 打开安装目录（替代 .lnk：COM 被安全策略拦）----------
open_bat = (
    '@echo off\r\n'
    'explorer "%LOCALAPPDATA%\\hermes"\r\n'
)

files = {
    '启动 Hermes.bat': start_bat,
    '填 API Key.bat': fill_bat,
    'Hermes 体检.bat': check_bat,
    '打开 hermes 目录.bat': open_bat,
}

for name, content in files.items():
    p = folder / name
    p.write_bytes(content.encode('ascii'))
    print('WROTE', p.name, p.stat().st_size, 'bytes')

# ---------- 5) 使用说明副本 ----------
src = Path(r'C:\Users\AHS\WorkBuddy\2026-09-15-10-22-22\Hermes-Agent-使用说明.md')
if src.is_file():
    dst = folder / '使用说明.md'
    shutil.copy2(src, dst)
    print('COPIED', dst.name, dst.stat().st_size, 'bytes')
else:
    print('SKIP doc copy (source missing):', src)

print('DONE')
