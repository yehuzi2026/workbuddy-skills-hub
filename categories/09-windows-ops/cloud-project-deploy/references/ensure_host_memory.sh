#!/bin/bash
# 开放签独立部署包 · 宿主机内存调优（幂等）
# 2G 小内存主机同时跑 api + job 两台 Java 应用 + mysql 时，默认内存配置会触发：
#   1) 内核 OOM-killer 在内存压力下直接 kill 掉 Java（exit 137），而非换页；
#   2) Committed_AS 触及 CommitLimit(RAM*overcommit_ratio + swap) 时被拒。
# 本脚本：补一个 4G swapfile（抬高 CommitLimit）+ 设 vm.overcommit_memory=1（允许换页而非 OOM-kill）。
# 已在 <阿里云服务器公网IP> 上验证，使 api 从崩溃循环变为长期稳定。
set -e

SWAPFILE=/swapfile2

echo "==> 当前 overcommit_memory=$(cat /proc/sys/vm/overcommit_memory) CommitLimit=$(grep CommitLimit /proc/meminfo | awk '{print $2}')KB"

# 1) 补充 swapfile（若尚未启用）
if ! swapon --show 2>/dev/null | grep -q "$SWAPFILE"; then
  if [ ! -f "$SWAPFILE" ]; then
    echo "==> 创建 4G swapfile: $SWAPFILE"
    fallocate -l 4G "$SWAPFILE" 2>/dev/null || dd if=/dev/zero of="$SWAPFILE" bs=1M count=4096 status=none
    chmod 600 "$SWAPFILE"
    mkswap "$SWAPFILE" >/dev/null
  fi
  swapon "$SWAPFILE"
  grep -q "$SWAPFILE" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
  echo "==> 已启用 swap"
else
  echo "==> swapfile 已启用，跳过"
fi

# 2) 关闭启发式 overcommit，允许内核换页而不是直接 OOM-kill Java
if [ "$(cat /proc/sys/vm/overcommit_memory)" != "1" ]; then
  echo "==> 设置 vm.overcommit_memory=1"
  sysctl -w vm.overcommit_memory=1 >/dev/null
  if grep -q 'vm.overcommit_memory' /etc/sysctl.conf; then
    sed -i 's/^vm.overcommit_memory.*/vm.overcommit_memory=1/' /etc/sysctl.conf
  else
    echo 'vm.overcommit_memory=1' >> /etc/sysctl.conf
  fi
else
  echo "==> overcommit_memory 已为 1，跳过"
fi

echo "==> 完成: overcommit_memory=$(cat /proc/sys/vm/overcommit_memory) swap条目=$(swapon --show | grep -c '^/') CommitLimit=$(grep CommitLimit /proc/meminfo | awk '{print $2}')KB"
