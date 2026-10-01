#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wusun-cockpit 增量部署脚本（自包含）。
把本地 wusun-auction 项目打包 -> SFTP 上传 -> 解压到 /opt/wusun-app -> npm install --omit=dev -> pm2 restart wusun-app。
保留 uploads/ 与 wusun.db，不动既有管理员口令。

环境变量（必须）：
  SSH_PW       root@<阿里云服务器公网IP> 的登录口令
  PROJECT_DIR  本地 wusun-auction 项目根目录（含 server.js）。缺省用当前工作目录。
  LOCAL_TAR    本地临时 tar 包路径（可选，默认用系统临时目录）。

用法：
  export SSH_PW="xxxx"
  python deploy_cockpit.py
  PROJECT_DIR=/path/to/wusun-auction SSH_PW=xxxx python deploy_cockpit.py
"""
import os, sys, time, tarfile, tempfile, paramiko

HOST = "<阿里云服务器公网IP>"
PORT = 22
USER = "root"
APP_DIR = "/opt/wusun-app"
REMOTE_TAR = "/opt/wusun-app-deploy.tar.gz"

EXCLUDE_DIRS = {"node_modules", ".git", ".workbuddy", "backups", "__pycache__", "_tmp_verify", "uploads"}
# 关键：部署时绝不包含任何 *.db（含 wusun.db 及本地/测试库），避免用本地/测试库覆盖生产数据。
# 生产库的表结构由 server 启动时自动迁移（db.js init），数据靠生产侧自身落盘保留。
EXCLUDE_FILES = {".DS_Store", "wusun-app-deploy.tar.gz", "wusun.db"}


def build_tar(project_dir, tar_path):
    if not os.path.isfile(os.path.join(project_dir, "server.js")):
        print("[!] PROJECT_DIR 下找不到 server.js：", project_dir)
        sys.exit(1)
    print("==> 打包", project_dir, "->", tar_path)
    with tarfile.open(tar_path, "w:gz") as tar:
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f in EXCLUDE_FILES or f.endswith(".db"):
                    continue
                fp = os.path.join(root, f)
                arc = os.path.relpath(fp, project_dir)
                tar.add(fp, arcname=arc)
    print("==> 打包完成，大小", os.path.getsize(tar_path), "bytes")


def ssh_connect():
    pw = os.environ.get("SSH_PW")
    if not pw:
        print("[!] 未设置环境变量 SSH_PW（root 登录口令）")
        sys.exit(1)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=pw, timeout=30)
    return c


def run_stream(c, cmd, timeout=900):
    stdin, stdout, stderr = c.exec_command(cmd, timeout=60, get_pty=True)
    t0 = time.time(); buf = ""
    while time.time() - t0 < timeout:
        r = stdout.channel.recv(65536)
        if not r:
            if stdout.channel.exit_status_ready():
                break
            time.sleep(0.2); continue
        s = r.decode("utf-8", "replace"); buf += s
        sys.stdout.write(s); sys.stdout.flush()
    try:
        while True:
            r = stdout.channel.recv(65536)
            if not r: break
            s = r.decode("utf-8", "replace"); buf += s
            sys.stdout.write(s); sys.stdout.flush()
    except Exception:
        pass
    return buf


def main():
    project_dir = os.environ.get("PROJECT_DIR") or os.getcwd()
    project_dir = os.path.abspath(project_dir)
    tar_path = os.environ.get("LOCAL_TAR") or os.path.join(tempfile.gettempdir(), "wusun-app-deploy.tar.gz")

    build_tar(project_dir, tar_path)

    print("==> 连接服务器", HOST, flush=True)
    c = ssh_connect()
    print("==> SFTP 上传 ...", flush=True)
    sftp = c.open_sftp()
    sftp.put(tar_path, REMOTE_TAR)
    sftp.close()

    print("==> 增量更新：覆盖代码 + npm install + pm2 restart ...", flush=True)
    run_stream(c,
        f"cd {APP_DIR} && rm -f public/admin.html public/admin.js && tar -xzf {REMOTE_TAR} -C {APP_DIR} && npm install --registry=https://registry.npmmirror.com --omit=dev && pm2 restart wusun-app",
        timeout=900)

    print("\n==> 本地 3000 验证 ...", flush=True)
    print(run_stream(c, "sleep 2; curl -s -o /dev/null -w 'local_http=%{http_code}\\n' http://localhost:3000/; curl -s -o /dev/null -w 'local_dashboard=%{http_code}\\n' http://localhost:3000/api/dashboard", timeout=30), flush=True)
    print("==> 公网 HTTPS 验证 ...", flush=True)
    print(run_stream(c, "curl -s -o /dev/null -w 'https_home=%{http_code}\\n' https://ws.aicnpor.cn/; curl -s -o /dev/null -w 'https_dashboard=%{http_code}\\n' https://ws.aicnpor.cn/api/dashboard", timeout=30), flush=True)
    c.close()
    print("\n==> 增量部署完成", flush=True)


if __name__ == "__main__":
    main()
