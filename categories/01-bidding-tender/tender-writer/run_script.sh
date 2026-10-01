#!/usr/bin/env bash
# tender-writer 运行包装器(WorkBuddy 适配)
# 用 WorkBuddy 受管虚拟环境的 python 执行 scripts/ 下的脚本,
# 避免污染系统 Python,也无需在技能目录内创建 .venv。
# 用法: bash run_script.sh <脚本名> <参数...>

set -euo pipefail

# 受管 venv 的 python 绝对路径(Windows 风格)
VENV_PY="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

# 本脚本所在目录下的 scripts/(转为原生 Windows 路径,避免 MSYS 转换歧义)
SCRIPT_DIR_POSIX="$(cd "$(dirname "$0")" && pwd)/scripts"
if command -v cygpath >/dev/null 2>&1; then
  SCRIPT_DIR="$(cygpath -w -a "$SCRIPT_DIR_POSIX")"
else
  SCRIPT_DIR="$SCRIPT_DIR_POSIX"
fi
# 统一用反斜杠,Windows python 解析更稳
SCRIPT_DIR="${SCRIPT_DIR//\//\\}"

if [ "$#" -lt 1 ]; then
  echo "用法: bash run_script.sh <脚本名> <参数...>" >&2
  exit 1
fi

SCRIPT_NAME="$1"
shift

# 若未带 .py 后缀则补上
case "$SCRIPT_NAME" in
  *.py) ;;
  *) SCRIPT_NAME="$SCRIPT_NAME.py" ;;
esac

TARGET="${SCRIPT_DIR}\\${SCRIPT_NAME}"
if [ ! -f "$TARGET" ]; then
  echo "找不到脚本: $TARGET" >&2
  exit 1
fi

exec "$VENV_PY" "$TARGET" "$@"
