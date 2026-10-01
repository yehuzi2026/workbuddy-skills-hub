"""通用日志解码器：自动识别 UTF-8 / UTF-16 LE/BE / GBK，输出为 UTF-8 文本。

用法:
    python decode.py <文件> [--tail N] [--skip-empty]

Windows 上不同工具写日志的编码不一致（Tee-Object 写 UTF-16、Out-File -Encoding utf8
写 UTF-8 with BOM、原生命令 stderr 可能是 GBK），所以按可靠性顺序逐个试探，
以"解码后是否含常见可读片段"作为判定依据。
"""
import sys
from pathlib import Path

CANDIDATES = ("utf-8-sig", "utf-16", "utf-16-be", "cp936", "latin-1")

# 出现这些片段说明解码方向对了（脚本/Hermes 的输出里几乎必然有）
PROBES = ("hermes", "Hermes", "OK", "install", "uv ", "npm", "[", "=")


def decode(raw: bytes) -> tuple[str, str]:
    best = None
    for enc in CANDIDATES:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        score = sum(text.count(p) for p in PROBES)
        # \ufffd 是替换字符，出现说明解码有损
        score -= text.count("\ufffd") * 10
        if best is None or score > best[1]:
            best = (enc, score, text)
    if best is None:
        return "latin-1", raw.decode("latin-1", errors="replace")
    return best[0], best[2]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"文件不存在: {path}")
        return 1

    tail = 0
    skip_empty = "--skip-empty" in sys.argv
    if "--tail" in sys.argv:
        tail = int(sys.argv[sys.argv.index("--tail") + 1])

    enc, text = decode(path.read_bytes())
    lines = text.splitlines()
    if skip_empty:
        lines = [ln for ln in lines if ln.strip()]
    if tail:
        lines = lines[-tail:]

    print(f"# 编码={enc} 总行数={len(lines)} 文件={path.name}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
