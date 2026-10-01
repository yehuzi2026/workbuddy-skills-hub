#!/bin/bash
# 在 Alibaba Cloud Linux 3 (el8 兼容) 上安装并启动 Docker + Swarm。
# 兼容策略：优先用系统自带 docker 包，失败则回落到阿里云 docker-ce 仓库(centos/8)。
set -e
if command -v dockerd >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "docker 已在运行"
else
  # 1) 系统自带 docker 包
  if ! command -v dockerd >/dev/null 2>&1; then
    dnf install -y docker >/dev/null 2>&1 || yum install -y docker >/dev/null 2>&1 || true
  fi
  # 2) 回落：阿里云 docker-ce 仓库（centos/8 与 Alinux3 el8 兼容）
  if ! command -v dockerd >/dev/null 2>&1; then
    dnf install -y dnf-plugins-core >/dev/null 2>&1 || true
    cat > /etc/yum.repos.d/docker-ce.repo <<'EOF'
[docker-ce-stable]
name=Docker CE Stable - $basearch
baseurl=https://mirrors.aliyun.com/docker-ce/linux/centos/8/$basearch/stable
enabled=1
gpgcheck=1
gpgkey=https://mirrors.aliyun.com/docker-ce/linux/centos/gpg
EOF
    dnf makecache >/dev/null 2>&1 || true
    dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null 2>&1 || true
  fi
fi
systemctl enable docker 2>/dev/null || true
systemctl start docker 2>/dev/null || service docker start 2>/dev/null || true
sleep 3
if docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q inactive; then
  docker swarm init 2>/dev/null || true
fi
docker info --format 'Swarm: {{.Swarm.LocalNodeState}} Server: {{.ServerVersion}}'
