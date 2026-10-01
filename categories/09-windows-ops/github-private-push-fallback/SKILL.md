---
name: github-private-push-fallback
description: 当 GitHub MCP 连接器掉线/抖动、本地无 gh CLI、或无 Docker 时，用「本地 git + 用户临时 PAT + 嵌入 URL + 禁用 GCM helper + 事后抹 URL」稳定推送代码到 GitHub 私有仓的兜底工作流。触发词：推 GitHub、建私有仓、GitHub MCP 掉线、推代码到 GitHub、git push 失败。
---

# GitHub 私有仓推送兜底流程

当 WorkBuddy 的 **GitHub MCP 连接器掉线**（deferred 索引找不到 `mcp__github__*`、重连失败），
或本机**没有 `gh` CLI / 没有 Docker** 时，用本地 git + 用户提供的临时 PAT 仍可稳定推送私有仓。

## 前置：拿 PAT（绝对不要自己伪造）
- 让用户到 `GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)` 生成。
- 权限：勾 **`repo`**（或 fine-grained 勾 Repository contents 读写 + metadata）。
- 账户必须是目标 GitHub 账号（如 `yehuzi2026`）。

## 步骤
1. **验证 PAT 权限**（只测 scope，不打印令牌明文）：
   ```bash
   TOK="ghp_xxx"   # 来自用户，仅进本次 shell 变量
   curl -s -D - -o /dev/null -H "Authorization: Bearer $TOK" https://api.github.com/user \
     | grep -i "x-oauth-scopes"
   # 期望看到：X-OAuth-Scopes: repo
   ```
2. **建私有仓**（避免重名，先确认不存在）：
   ```bash
   curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
     -d '{"name":"<repo>","private":true,"auto_init":false}' \
     https://api.github.com/user/repos
   # HTTP 201 = 成功；422 = 已存在
   ```
3. **配置 remote 并推送**（关键：`-c credential.helper=` 绕过 Windows 凭据管理器/GCM 里可能缓存的**只读** `x-access-token`，否则它会抢先返回无 repo 权限的令牌导致 403）：
   ```bash
   cd <repo_dir>
   git remote remove origin 2>/dev/null
   git remote add origin "https://<user>:<PAT>@github.com/<user>/<repo>.git"
   git -c credential.helper= push -u origin <branch>   # 一般是 master 或 main
   ```
4. **立即抹掉 URL 里的 PAT 明文**（安全第一，绝不留在 `.git/config`）：
   ```bash
   git remote set-url origin "https://github.com/<user>/<repo>.git"
   git remote -v   # 确认无令牌
   ```
5. **验证远端零密钥泄露**：
   ```bash
   curl -s -H "Authorization: Bearer $TOK" \
     "https://api.github.com/repos/<user>/<repo>/git/trees/<branch>?recursive=1" \
     | python -c "import sys,json;d=json.load(sys.stdin);print('文件数',len(d['tree']))"
   git ls-files | grep -E '\.env$|\.db$' || echo "无 .env/.db 入库 ✅"
   ```

## 安全铁律（必须遵守）
- **PAT 只进本次 shell 变量，绝不写进记忆文件 / 日志 / 源码硬编码 / `.env`**。
- 推送前必须确认 `.gitignore` 已排除 `.env`、`*.db`、打包产物、测试图。
- push 后**必须** `git remote set-url` 抹掉 URL 明文。
- 给用户走的「部署拉取用 GitHub Token」只给**只读**权限，不要复用含 `repo` 写权限的 PAT；
  真正的云厂商密钥（如 `SCNET_API_KEY`）只在**容器环境变量**里填，永远不进 Git。

## 常见坑
- **GCM 缓存的只读令牌**：Windows 凭据管理器里的 `x-access-token` 可能只有只读权限，git push 会静默用它 → 403。
  解决：`git -c credential.helper=` 临时禁用 helper（最稳），或 `GIT_CREDENTIAL_HELPER=`。
- **本地分支名**：git init 新版默认 `master`，旧版可能 `main`；用 `git branch --show-current` 确认。
- **curl 在沙箱里重定向写文件可能被拦**：用变量捕获 `RESP=$(curl ...)` 再 `echo "$RESP" | grep`，不要 `curl ... -o file`。
- **python 路径**：脚本里别用 `$C:` 这种未定义变量；用绝对路径
  `"C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"`。

## 适用边界
- 仓库已 `git init` + 已 commit 干净源码（密钥已排除）后，本流程只负责"建仓 + 推送"。
- 若 GitHub MCP 连接器恢复可用，优先用 `create_repository` + `push_files`，更省事。
