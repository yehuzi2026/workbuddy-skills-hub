---
name: gitbash-coreutils-fix
description: 修复 Windows 上 Git Bash / WorkBuddy 终端「coreutils 集体失踪」——ls、cat、cp、mv、mkdir、grep、head、tail、sed、awk、dirname、basename、xargs、date、sleep、du、df、seq、tee、mktemp 等全部 command not found，同时 stderr 反复刷 `shell-runtime-bash-env.sh: line 3: dirname: command not found` 与 `cd: null directory`。核心洞察：文件其实都在 PortableGit/usr/bin 里没丢，真正断的是 PATH —— bash 以「非登录+非交互」启动导致 /etc/profile 不执行，且 $HOME 下没有 .bashrc/.bash_profile 兜底；一个 dirname 找不到就让 WorkBuddy 的 BASH_ENV 脚本自我中断，连带 brokered-bin 也没进 PATH，形成连锁瘫痪。含幂等自愈脚本（注入 BASH_ENV 引导 + 建 ~/.bashrc、~/.bash_profile，自动备份、可 --check 诊断、可 --restore 回滚）。当用户说「Git Bash 缺 coreutils」「ls: command not found」「终端里命令都没了」「老毛病」「bash 命令找不到」「dirname command not found」「WorkBuddy 终端坏了」「git bash 环境又坏了」「换电脑后命令全没了」时加载。
agent_created: true
---

# Git Bash coreutils 集体失踪修复（gitbash-coreutils-fix）

> 沉淀自 2026-09-15 实战。用户原话：「Git Bash 缺 coreutils（老毛病），修复」——
> 关键词是**老毛病**，说明会复发，所以本 skill 的重点不只是"怎么修"，而是"为什么老复发 + 怎么一键再修"。

## 何时用

- Git Bash / WorkBuddy 终端里 `ls`、`cat`、`grep`、`head`、`sed`、`awk`、`dirname` 等报 command not found。
- stderr 反复刷这两行：
  ```
  .../cli/vendor/shim/shell-runtime-bash-env.sh: line 3: dirname: command not found
  .../cli/vendor/shim/shell-runtime-bash-env.sh: line 3: cd: null directory
  ```
- 用户说「老毛病又犯了」「换电脑后命令都没了」「终端坏了」。

## 一、先别急着装东西 —— 文件根本没丢

**新手最容易走错的一步：去重装 Git、去 choco/scoop 装 coreutils。全错。**

第一步永远是确认文件是否真的存在：

```bash
/usr/bin/ls -d /usr/bin/ls.exe
/usr/bin/cygpath -w /usr/bin
```

2026-09-15 实测：`C:\Users\AHS\.workbuddy\binaries\PortableGit\versions\1.2.0\usr\bin\`
下面 **ls.exe / cat.exe / grep.exe / sed.exe / awk.exe … 一个不少**，连 `/mingw64/bin/git.exe` 都在。

**文件在、命令找不到 → 问题 100% 在 PATH，不在文件。**

## 二、根因链条（关键，别只看症状）

```
① WorkBuddy 以「非登录 + 非交互」方式启动 bash，只读 BASH_ENV
   → /etc/profile 不执行
   → 而 /etc/profile 第 52 行才是把 /mingw64/bin:/usr/local/bin:/usr/bin:/bin
     写进 PATH 的唯一地方
② PATH 里没有 /usr/bin
   → BASH_ENV 脚本 shell-runtime-bash-env.sh 第 3 行的 dirname 找不到
③ 第 3 行失败
   → __codebuddy_shell_runtime_dir=""（因为 $(cd "$(dirname ...)" && pwd) 返回空）
   → 第 5/6 行 [ ! -f "/safe-bin/..." ] 判断全部短路
   → brokered-sandbox-bash-env.sh 没被 source
   → brokered-bin 也没进 PATH
④ 结果：整套 coreutils 消失
```

**一个 `dirname` 引发连锁瘫痪** —— 这是本 bug 最反直觉的地方。

### 为什么是"老毛病"（会复发）

`$HOME`（`C:\Users\AHS`）下**原本没有 `.bashrc` / `.bash_profile` / `.profile`**，
没有任何用户级入口去补 PATH。于是：

| 场景 | 结果 |
|---|---|
| 换电脑 / 迁移（只搬 WorkBuddy 数据，没搬 dotfiles） | 必复发 |
| WorkBuddy 升级，覆盖了 `cli/vendor/shim/shell-runtime-bash-env.sh` | 必复发 |
| 手动装过一次但因上面两条又丢 | 复发 |

## 三、一键修复

```bash
"C:/Users/AHS/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
  "C:/Users/AHS/.workbuddy/tools/fix-gitbash-coreutils.py"
```

三种模式：

| 命令 | 作用 |
|---|---|
| `（无参数）` | 修复 + 实测验证 |
| `--check` | 只诊断，不写任何文件 |
| `--restore` | 从 shim 移除已注入的 bootstrap（回滚） |

脚本做三件事：
- **A** 给 WorkBuddy 的 BASH_ENV shim 注入最小 PATH 引导（幂等，先自动备份成 `.bak-<时间戳>`）
- **B** 确保 `~/.bashrc` 与 `~/.bash_profile` 存在
- **C** 用新起的 bash 进程实测验证，输出中文报告

> 脚本用 Python 写，**故意不依赖任何 shell 工具** —— 因为修复前 coreutils 本身就是缺的，
> 用 shell 写的修复脚本可能连运行都运行不起来。

## 四、手动修复（没有脚本时的最小操作）

在 `cli/vendor/shim/shell-runtime-bash-env.sh` 的**第一行之前**插入：

```sh
if [ -z "${WB_PATH_BOOTSTRAPPED:-}" ]; then
  WB_PATH_BOOTSTRAPPED=1
  export WB_PATH_BOOTSTRAPPED
  case ":${PATH}:" in
    *:/usr/bin:*) ;;
    *) PATH="/mingw64/bin:/usr/local/bin:/usr/bin:/bin${PATH:+:${PATH}}"; export PATH ;;
  esac
  if [ -n "${HOME:-}" ] && [ -f "${HOME}/.bashrc" ]; then
    . "${HOME}/.bashrc"
  fi
fi
```

**三个必须遵守的点：**

1. **必须在任何 `dirname` / `$(...)` 之前** —— 否则脚本第 3 行照样自我中断。
2. **不写死版本号** —— 用 `/usr/bin`、`/mingw64/bin` 这种 MSYS2 挂载点，
   由 bash 自动解析到当前 PortableGit 安装根，换 `versions/1.2.0` 之后依然有效。
3. **文件可能 EBUSY** —— 若 Edit 报 `resource busy or locked`，隔几秒重试即可，
   实测是瞬时占用，不是硬锁。

### 同时建用户级兜底（抗复发）

- `~/.bashrc`：真正的 PATH 修复逻辑（含幂等判断）
- `~/.bash_profile`：`test -f ~/.bashrc && . ~/.bashrc`

⚠️ **但要知道一个实测结论**：WorkBuddy 的 Bash 工具走的是「非登录+非交互」，
**`~/.bashrc` 不会被自动读取**（实测 `WB_BASHRC_LOADED=NO`）。
它只在被 shim 显式 `.` 引入、或用户开交互式 Git Bash 时生效。
所以 **shim 里那行引导才是真正的救命稻草**，dotfiles 是兜底和扩展入口。

## 五、验证（必须实测，别只看文件）

```bash
# 1) 引导标记
printf '%s\n' "${WB_PATH_BOOTSTRAPPED:-NO}"      # 期望 1
printf '%s\n' "${WB_BASHRC_LOADED:-NO}"          # 期望 yes

# 2) 逐命令探活
for c in ls cat cp mv mkdir grep head sed awk dirname xargs git; do
  printf '%-8s %s\n' "$c" "$(command -v $c)"
done

# 3) GNU 语义验证（Windows 的 find 不支持 -name，能过说明走的是 GNU 版）
find . -maxdepth 1 -name "*.txt"
echo "$(printf 'b\na\n' | sort | head -1)"       # 期望 a

# 4) stderr 必须干净 —— 那两行 dirname 报错消失
```

2026-09-15 修复后实测：

| 项目 | 结果 |
|---|---|
| 命令探活 | **34/34 可用，缺失 0** |
| GNU coreutils | 8.32 |
| GNU findutils | 4.10.0 |
| GNU Awk | 5.4.0 |
| git | 2.55.0.windows.3（`/mingw64/bin/git`） |
| stderr | 完全干净 |
| 中文文件名 | 正常 |
| `type rm` | `rm is a function` ← **安全删除沙箱未降级** |

### PATH 顺序（要保证 GNU 优先）

```
第 13 位  /mingw64/bin
第 15 位  /usr/bin
第 27 位  /c/Windows/system32      ← GNU 必须排它前面
```

`C:\Windows\System32` 里也有 `find.exe` 和 `sort.exe`，**语义与 GNU 完全不同**
（Windows 的 find 是字符串搜索，`find . -name x` 直接报错）。
所以引导必须把 `/mingw64/bin`、`/usr/bin` 放在 system32 **之前**。

## 六、踩坑记录

| 坑 | 现象 | 处理 |
|---|---|---|
| 误判为"文件丢了" | 去重装 Git / 装 coreutils | 先 `/usr/bin/cygpath -w /usr/bin` 确认文件在 |
| shim 写入 EBUSY | `resource busy or locked` | 瞬时占用，隔几秒重试 |
| 写 sh 文件带 BOM | 第一行 `\ufeff` 导致语法错 | 必须 `encoding="utf-8"`、`newline="\n"`，**绝不加 BOM** |
| 从 Bash 调 `cmd.exe` | 被安全策略拦截 | 用 Glob / Read / Write 等专用工具，别绕 shell |
| 以为改了 `~/.bashrc` 就完事 | 仍报 command not found | 非交互 bash 不读 .bashrc，**必须改 shim** |
| 把 GNU 路径塞到 PATH 最前 | 可能压掉沙箱拦截层 | 引导里先前置 GNU，再幂等把 `CODEBUDDY_BROKERED_BIN_DIR` / `CODEBUDDY_SAFE_DELETE_BIN_DIR` 重新提到最前 |

## 七、PATH 里残留的脏项（已知、无害、未清理）

WorkBuddy 会往 PATH 注入 Windows 格式路径，例如：

```
C:\LenovoSoftstore\Install\WorkBuddy\...\shim\safe-bin
```

PATH 用 `:` 分隔，而 `C:\...` 自带冒号 → 被切成无效的 `C` 和 `\LenovoSoftstore\...` 两项。
它们在任何 Unix 语义下都解析不到（不存在这样的目录），**只是浪费查找、无害**。
同时 node/python 路径有重复段。**这些是 WorkBuddy 自身注入的，本 skill 不清理**，
以免改变 WorkBuddy 的预期行为 —— 若用户明确要求再单独处理。
