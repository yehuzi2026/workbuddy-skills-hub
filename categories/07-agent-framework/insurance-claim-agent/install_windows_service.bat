@echo off
REM ============================================================
REM  Windows 部署：把保险理赔 Agent 注册为系统服务（开机自启、崩溃重启）
REM  前置：已安装 Python 3.11、并下载 nssm.exe 放到本目录或 PATH
REM  用法：右键「以管理员身份运行」本文件
REM ============================================================
setlocal
cd /d %~dp0

set VENV=.venv
set SVC=InsuranceClaimAgent
set NSSM=nssm.exe

echo [1/4] 创建虚拟环境并安装依赖...
if not exist %VENV% python -m venv %VENV%
call %VENV%\Scripts\activate.bat
pip install -r requirements.txt

echo [2/4] 请确认 .env 已存在并填入 SCNET_API_KEY（未配置则无法推理）
if not exist .env (
  echo 警告：未找到 .env，请先 cp .env.example .env 并填写 Key
)

echo [3/4] 用 nssm 注册服务（监听 127.0.0.1:8000，由 IIS 反代对外）...
%NSSM% install %SVC% "%CD%\%VENV%\Scripts\python.exe"
%NSSM% set %SVC% AppParameters " -m uvicorn app:app --host 127.0.0.1 --port 8000 --timeout 300"
%NSSM% set %SVC% AppDirectory "%CD%"
%NSSM% set %SVC% DisplayName "保险理赔核保自动化 Agent"
%NSSM% set %SVC% Start SERVICE_AUTO_START
%NSSM% set %SVC% AppExit Default Restart

echo [4/4] 启动服务...
%NSSM% start %SVC%

echo 完成。访问 http://localhost:8000 ；建议再用 IIS ARR 反代做域名/HTTPS（见 DEPLOYMENT.md）
pause
