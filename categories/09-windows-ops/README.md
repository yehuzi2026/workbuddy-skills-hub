# 🛠️ Windows 运维与 WorkBuddy 工具链 / Windows Ops & Toolchain

> 管理员权限诊断、开机自启清理、Git Bash 修复、解除程序黑名单、GitHub 兜底推送、迁移打包/修复、云部署、共享主机 PHP 子系统。

**本分类共 9 个技能。**


| 技能文件夹 | 名称 | 简介 |
| --- | --- | --- |
| `windows-admin-privilege-diagnose` | windows-admin-privilege-diagnose | 诊断 Windows 本地账户的"管理员权限"并给出提权方案。当用户说「把某用户改成管理员」「我不是管理员吗」「为什么提示拒绝访问」「关掉 UAC」「让程序默认以管理员运行」「以管… |
| `windows-autostart-cleanup` | windows-autostart-cleanup | 清理 Windows 开机自启项（注册表 Run、启动文件夹、计划任务），并判断被删掉的应用会不会"自己长回来"。当用户说「关掉开机自启 / 取消开机启动 / 电脑开机太慢 / 清… |
| `gitbash-coreutils-fix` | gitbash-coreutils-fix | 修复 Windows 上 Git Bash / WorkBuddy 终端「coreutils 集体失踪」——ls、cat、cp、mv、mkdir、grep、head、tail、se… |
| `workbuddy-program-blacklist` | workbuddy-program-blacklist | 解除 WorkBuddy 沙箱的「程序黑名单」（Program Blacklist）硬拦截。当出现 "PROGRAM BLOCKED BY SECURITY POLICY" 报错、… |
| `github-private-push-fallback` | github-private-push-fallback | 当 GitHub MCP 连接器掉线/抖动、本地无 gh CLI、或无 Docker 时，用「本地 git + 用户临时 PAT + 嵌入 URL + 禁用 GCM helper … |
| `workbuddy-migration-pack` | workbuddy-migration-pack | 生成「WorkBuddy 换电脑迁移包」v3.1——把 AI 助手的全部身份（SOUL/IDENTITY/USER/MEMORY）、技能库、记忆缓存、连接器配置、自动化任务库、会话… |
| `workbuddy-migration-repair` | workbuddy-migration-repair | 修复「换电脑迁移后 WorkBuddy 空间/工作区列表变空、空间里对话全空、自动化任务全失效」的事故，以及把迁移包「合并」进已有安装（去重不覆盖、不丢本机新增数据）。当用户说"空… |
| `cloud-project-deploy` | cloud-project-deploy | 把本地 Docker 化程序/项目部署到阿里云服务器（root@<阿里云服务器公网IP>）并稳定运行的通用方法论。当用户说「部署到云服务器 / 上传项目到云 / 部署 Docker… |
| `shared-host-php-subsystem` | shared-host-php-subsystem | Guidance for building a self-contained business subsystem (admin SPA plus PHP backend) on … |

## 安装

将本分类下对应的技能文件夹整体复制到 WorkBuddy 用户级技能目录：

```bash
# Windows
xcopy "%USERPROFILE%\.workbuddy\skills"  # 放入对应子文件夹
# 或直接把某个技能文件夹复制到 (Windows 示例):
C:\Users\<你>\.workbuddy\skills\<技能名>
```

放入后重启 WorkBuddy 即可在对话中触发。
