#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""车拍拍 · 稳健上架脚本（逐文件独立连接 + 重试 + latin-1）。
覆盖 FTP 欢迎语/传输偶发 ConnectionReset 的问题。"""
import ftplib, os, sys, time

HOST = os.environ.get('FTP_HOST', 'wuhanhonganghang.cn')
USER = os.environ.get('FTP_USER', 'wuhanhgh06')
PASS = os.environ.get('FTP_PASS', '')


def connect():
    last = None
    for attempt in range(1, 6):
        try:
            f = ftplib.FTP(timeout=30)
            f.encoding = 'latin-1'          # 西部数码欢迎语含非 UTF-8 字节，latin-1 最稳
            f.connect(HOST)
            f.login(USER, PASS)
            return f
        except Exception as e:
            last = e
            print(f'  [connect retry {attempt}] {e}')
            time.sleep(2)
    raise SystemExit('FTP 连接失败: ' + str(last))


def ensure_dir(f, remote_dir):
    parts = [p for p in remote_dir.split('/') if p]
    cur = ''
    for p in parts:
        cur = cur + '/' + p
        try:
            f.mkd(cur)
        except Exception:
            pass


def put_one(local, remote):
    for attempt in range(1, 4):
        try:
            f = connect()
            ensure_dir(f, os.path.dirname(remote))
            with open(local, 'rb') as fh:
                f.storbinary('STOR ' + remote, fh)
            try:
                f.quit()
            except Exception:
                pass
            print('OK   ->', remote)
            return True
        except Exception as e:
            print(f'  [retry {attempt}] {remote}: {e}')
            time.sleep(2)
    print('FAIL ->', remote)
    return False


def main():
    manifest = sys.argv[1] if len(sys.argv) > 1 else 'deploy_web_release.txt'
    cwd = os.getcwd()
    items = []
    with open(manifest, 'r', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            toks = line.split()
            if len(toks) >= 2:
                items.append((toks[0], toks[1]))
    print(f'=== 稳健上架：{len(items)} 个文件 ===')
    ok = fail = 0
    for local_rel, remote in items:
        local = os.path.join(cwd, local_rel)
        if not os.path.exists(local):
            print('MISS ->', local_rel)
            fail += 1
            continue
        if put_one(local, remote):
            ok += 1
        else:
            fail += 1
    print(f'=== 完成：成功 {ok} / 失败 {fail} / 共 {len(items)} ===')
    sys.exit(1 if fail else 0)


if __name__ == '__main__':
    main()
