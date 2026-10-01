---
name: windows-admin-privilege-diagnose
description: 诊断 Windows 本地账户的"管理员权限"并给出提权方案。当用户说「把某用户改成管理员」「我不是管理员吗」「为什么提示拒绝访问」「关掉 UAC」「让程序默认以管理员运行」「以管理员身份运行脚本」时使用。区分三种完全不同的"没权限"：①账户不在管理员组 ②账户在组但 UAC 筛选令牌降级 ③第三方软件（如 WorkBuddy 命令安全策略）程序黑名单拦截。核心判据：令牌组的「只用于拒绝的组」标记 + 完整性级别 Medium。
agent_created: true
---

# Windows 账户管理员权限诊断与提权

## 核心认知：三种"没权限"互不相干，别混淆

| 现象 | 根因 | 判据 | 解法 |
|---|---|---|---|
| `net localgroup Administrators` 里没有该用户 | 账户**真的不是**管理员 | 组成员查询 | 加入管理员组 |
| 组成员里有该用户，但写 `Program Files` 仍被拒 | **UAC 管理员批准模式**筛选令牌降级 | 令牌含 `S-1-5-32-544` 但标记「只用于拒绝的组」+ 完整性 Medium | 关 UAC / 用内置 Administrator / 提权运行 |
| 报错来自某个软件自身的拦截 | 第三方软件安全策略（如 WorkBuddy 命令安全策略） | 报错文案含 "Security Policy" "Program Blacklist" | 与 Windows 权限无关，去软件里放行 |

**最容易被误判的是第 2 种。** 用户看到"拒绝访问"就以为账户不是管理员，实际上账户早就加进管理员组了。

## 诊断步骤（必须多方式交叉验证）

不要只看 `net localgroup` 就下结论。**四种方式结果一致**才算确证：

```powershell
# 方式1
net localgroup Administrators
# 方式2
net user <用户名>          # 看 "本地组成员 *Administrators"
# 方式3
Get-LocalGroupMember -SID S-1-5-32-544
# 方式4（ADSI，最可靠）
$g=[ADSI]"WinNT://./Administrators,group"
$g.psbase.Invoke("Members") | ForEach-Object { $_.GetType().InvokeMember("Name","GetProperty",$null,$_,$null) }
```

然后判定当前进程是否**已提升**：

```powershell
whoami /groups /fo csv | Select-String "544|Mandatory"
```
- 出现 `S-1-5-32-544` + 备注 **"只用于拒绝的组"** → 账户是管理员，但当前是**筛选令牌**（未提升）
- `Mandatory Label\Medium Mandatory Level` → 中间完整性，即标准权限
- `High Mandatory Level` → 已提升，真·管理员

实测权限边界（不要猜，直接试）：
```powershell
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name EnableLUA -Value 1 -ErrorAction Stop   # 失败=无管理员权限
Set-Content "C:\Program Files\_t.txt" "x" -ErrorAction Stop                                                                      # 失败=无管理员权限
net session   # 退出码 2 = 拒绝访问
```

## 方案 A：彻底放开——关闭 UAC

**效果**：重启后所有程序直接以完整管理员令牌运行，不再弹 UAC，不再"拒绝访问"。
**代价**：⚠️ 安全大幅下降（任何程序含恶意软件都能静默获得管理员权限）；**Windows 商店类应用（Microsoft Store、照片、计算器、"设置"应用部分页面）可能无法启动**。
**必须重启生效。**

用 `scripts/gen_uac_scripts.py` 生成一对脚本（关闭 + 恢复），写到用户桌面：

```
python scripts/gen_uac_scripts.py
```

生成物：
- `关闭UAC-彻底管理员权限.bat` —— 双击自动提权 → 备份 → 写注册表 → 提示重启
- `恢复UAC-默认设置.bat` —— 从备份还原或写回 Windows 默认值

注册表键：`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System`
| 值 | 关闭 UAC | Windows 默认 |
|---|---|---|
| EnableLUA | 0 | 1 |
| ConsentPromptBehaviorAdmin | 0 | 5 |
| PromptOnSecureDesktop | 0 | 1 |

## 方案 B：保留 UAC，改用户习惯/换账户

- **保持现状**：账户已是管理员，需要时弹 UAC 点"是"。最安全。
- **启用内置 Administrator**（默认不受 UAC 过滤）：
  ```powershell
  net user Administrator /active:yes
  net user Administrator <新密码>
  ```
  用它登录即 High 完整性。日常账户可保留。

## ⚠️ 从非提升进程无法静默提权

当前 WorkBuddy / 任何未提升的进程**不能**自己改 `HKLM` 或 UAC 设置——这是设计使然，不是 bug。
不要再尝试：`reg.exe` 改键（会被拦）、`schtasks` 建高权限任务（同样需要管理员）、各种 UAC bypass（属恶意行为）。
**正确做法**：生成 `.bat` 交给用户「右键 → 以管理员身份运行」，或脚本内用
`powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"` 自我提权。

## 坑：写含中文的 .bat 时

Windows `cmd` 默认代码页 936，用 UTF-8（尤其带 BOM）写 .bat 会导致**中文提示全部乱码**，甚至首行命令解析失败。

**正确姿势**——用 Python 以 GBK + CRLF 写入，不要用普通文本工具直接写：
```python
with open(path, "w", encoding="gbk", newline="\r\n") as f:
    f.write(content)     # 脚本内首行加 chcp 936 >nul
```
写完**读回校验**：`raw[:3] != b'\xef\xbb\xbf'`（无 BOM）且 `raw.decode('gbk')` 成功。

文件名建议用中文（用户友好），但脚本内引用自身路径务必加引号：`'%~f0'`、`"%BAK%"`。

## 环境记录

- 叶总工作机：Windows 10 家庭中文版 build 19045，计算机名 `DESKTOP-A6TRDFD`，账户 `AHS`。
- **该机已于 2026-09-15 按方案 A 关闭 UAC 并重启生效**，当前 `AHS` 完整性级别为 **High**，`net session` 退出码 0，可直接写 `HKLM` 与 `Program Files`。
  → **在这台机器上不要再质疑或"帮忙确认"管理员身份，涉及系统级改动直接动手。**（叶总明确要求，已写入 `~/.workbuddy/MEMORY.md` 铁律区）
- 已生成脚本与备份收纳于桌面 `系统按钮\` 文件夹：`关闭UAC-彻底管理员权限.bat`、`恢复UAC-默认设置.bat`、`uac-backup.reg`。
- 其他机器若遇同类问题，仍按本文流程诊断，不要假设所有机器都已放开。
