# -*- coding: utf-8 -*-
"""Robust SSH helper: auto-reconnect on 10054/reset, keepalive, single command per session."""
import os, time, paramiko

HOST = "<阿里云服务器公网IP>"
PORT = 22
USER = "root"
PW = os.environ.get("SSH_PW")

def _connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, PORT, USER, PW, timeout=20, look_for_keys=False, allow_agent=False)
    c.get_transport().set_keepalive(20)
    return c

def ssh_run(cmd, retries=5, timeout_per=60):
    """Run a single command, reconnecting on failure. Returns combined stdout+stderr."""
    last = ""
    for i in range(retries):
        try:
            c = _connect()
            stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout_per)
            out = stdout.read().decode(errors="replace") + stderr.read().decode(errors="replace")
            c.close()
            return out
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
            time.sleep(1.5)
    return "SSH_FAIL: " + last

def ssh_put(local, remote, retries=5):
    last = ""
    for i in range(retries):
        try:
            c = _connect()
            sftp = c.open_sftp()
            sftp.put(local, remote)
            sftp.close()
            c.close()
            return "OK"
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
            time.sleep(1.5)
    return "SFTP_FAIL: " + last

if __name__ == "__main__":
    import sys
    print(ssh_run(" ".join(sys.argv[1:])))
