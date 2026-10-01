# 保险理赔 / 核保自动化 Agent —— 部署方案（Runbook）

> 适用对象：车险物损智能初审工具（FastAPI + SCNet 云端推理 + 本地 OCR + 自我净化）。
> 本文给出 **4 种部署路径**，按"对外发布 / 内网使用 / 临时演示"不同目标选一条即可。

---

## 0. 架构与数据流（先看清再部署）

```
                 ┌──────────────┐
   用户浏览器 ──► │  Nginx/IIS   │  (HTTPS / 域名 / 大文件上传)
                 │  反代 :80/443│
                 └──────┬───────┘
                        │ http://127.0.0.1:8000
                 ┌──────▼───────┐
                 │  uvicorn     │  FastAPI (app.py)
                 │  app:app     │
                 └──┬────┬─────┬┘
        ┌───────────┘    │     └──────────────┐
        ▼                ▼                     ▼
  ┌──────────┐   ┌──────────────┐     ┌─────────────────┐
  │ RapidOCR │   │ SCNet 云端    │     │ experience.db   │
  │ 本地离线 │   │ / 私有 vLLM   │     │ (SQLite 经验库) │
  │ ONNX 推理│   │ 模型推理      │     │ 自我净化记忆    │
  └──────────┘   └──────────────┘     └─────────────────┘
```

**三类外部依赖，决定了部署约束：**
1. **SCNet 模型推理**（必填）：`https://api.scnet.cn/api/llm/v1`，需要 `SCNET_API_KEY`。这是唯一的"必联网"点。
2. **RapidOCR 模型文件**（首次运行下载）：本地离线推理，**首次实例化会下载 ONNX 权重**（约几十 MB），需要外网；下载后永久本地缓存，之后不再出网。
3. **经验库 `experience.db`**：SQLite 文件，**必须持久化**（自我净化的"记忆"），否则容器/进程重启后归零。

> ⚠️ 隐私红线：理赔材料含个人隐私（车牌、身份证、单据）。**生产环境强烈建议内网 / 私有化部署**；若走 SCNet 云端推理，材料会经平台模型服务，请先评估合规。

---

## 1. 前置条件（所有路径通用）

- Python 3.11（或 3.10+）；Linux 服务器或 Windows Server。
- 一个可用的 `SCNET_API_KEY`（api.scnet.cn 控制台 → 密钥管理）。
- 目标服务器能出网到 `api.scnet.cn`（推理用）。
- 若用本地 OCR，服务器首次需能出网下载 ONNX 模型（下载后免联网）。

**文件清单（部署时把这整个目录拷到服务器，去掉 SKILL.md / __pycache__）：**
```
app.py  claim_analyzer.py  ocr_utils.py  cases.py  cases.json
memory_store.py  evolver.py  llm_client.py
templates/index.html  requirements.txt  .env.example
Dockerfile  docker-compose.yml  nginx.conf  install_windows_service.bat  DEPLOYMENT.md
```

**环境变量（写进 `.env` 或系统环境变量）：**

| 变量 | 必填 | 说明 |
|---|---|---|
| `SCNET_API_KEY` | ✅ | SCNet 云端 API Key |
| `SCNET_BASE_URL` | ❌ | 默认 `https://api.scnet.cn/api/llm/v1`；私有化 vLLM 改成 `http://<IP>:10304/v1` |
| `ZHIPU_API_KEY` | ❌ | 云端视觉 OCR 兜底（GLM-4V）。内网/SCNet 容器场景留空 |
| `SELF_IMPROVE_DB` | ❌ | 经验库路径，默认 `./experience.db`；Docker 下固定 `/data/experience.db` |

---

## 2. 路径 A：Docker 部署（★ 推荐，VPS / 云主机 / 自有 Linux）

最干净、可移植、易回滚。经验库用卷持久化，OCR 模型在构建时预下载。

```bash
# 1) 拷目录到服务器后进入
cd insurance-claim-agent
cp .env.example .env
nano .env                 # 填入 SCNET_API_KEY

# 2) 构建并后台运行
docker compose up -d --build

# 3) 验证
curl http://localhost:8000/api/models      # 返回模型列表即成功
# 浏览器打开 http://<服务器IP>:8000
```

**加 HTTPS / 域名（可选但建议）：**
```bash
# 装 nginx + certbot，复制 nginx.conf，改 server_name 与证书路径，申请证书：
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp nginx.conf /etc/nginx/conf.d/claim-agent.conf   # 先只留 listen 80
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d claim.your-domain.com            # 自动签发并切到 443
```
随后在 `nginx.conf` 里把 `listen 80` 注释掉、启用 `listen 443 ssl` 两行，reload 即可。

**运维：**
- 看日志：`docker compose logs -f`
- 升级：`git pull` 或重新拷文件 → `docker compose up -d --build`
- 数据备份：定期 `cp data/experience.db data/experience.db.bak`

---

## 3. 路径 B：Windows 原生部署（契合你现有 IIS + PHP 基础设施）

适合**内网 / 已有 Windows Server** 的场景，不引入 Docker。

**① 注册为系统服务（开机自启 + 崩溃重启）：**
- 下载 [nssm](https://nssm.cc/) 的 `nssm.exe` 放到项目目录。
- 右键「以管理员身份运行」`install_windows_service.bat`。
- 它会在 `127.0.0.1:8000` 起 uvicorn，并注册服务 `InsuranceClaimAgent`。

**② 用 IIS 做反向代理（域名 + HTTPS）：**
- 服务器管理器 → 添加角色"Web 服务器(IIS)"，并装 **URL 重写** 与 **Application Request Routing (ARR)**。
- IIS 管理器 → 服务器节点 → **Application Request Routing Cache → Server Proxy Settings** → 勾选 "Enable proxy"。
- 在你的站点里加一条"入站规则"：匹配 `.*` → 重写到 `http://127.0.0.1:8000/{R:0}`。
- 绑定域名 + 在 IIS 上申请/绑定证书（或用 certbot for Windows）。

**③ 防火墙：** 只对外暴露 80/443（IIS），8000 仅监听回环，不对外。

---

## 4. 路径 C：SCNet 控制台「Web 应用」托管（零算力成本，但有坑）

控制台：**人工智能服务 → 模型部署 → 自定义创建 → 服务方式选「Web 应用」**，上传本目录，启动命令 `uvicorn app:app --host 0.0.0.0 --port 8000`，环境变量填 `SCNET_API_KEY`。

**必须知道的 3 个坑（决定能否用）：**
1. **经验库不持久**：容器重启 / 重新部署会清空 `experience.db`，**自我净化记忆归零**。除非平台提供持久存储挂载（需确认）。
2. **OCR 大概率失效**：RapidOCR 首次需下载 ONNX 模型，而 SCNet 容器通常**只能访问 `api.scnet.cn`、不能出公网** → 模型下载失败 → OCR 永久降级为 `none`。若必须 OCR，需提前把模型 bake 进镜像（自行构建带模型的 Docker，再上传）或改用路径 A/B。
3. **数据出境**：理赔材料会经 SCNet 云端模型服务，含个人隐私，**合规需评估**。

> 结论：SCNet 云托管只适合**演示 / 不计较记忆持久与 OCR 的内部试用**。生产请走 A 或 B。

---

## 5. 路径 D：局域网直跑（最快验证 / 内部小范围）

```bash
cd insurance-claim-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # 填 SCNET_API_KEY
uvicorn app:app --host 0.0.0.0 --port 8000
```
同网段访问 `http://<本机IP>:8000`。用 `nohup` / 任务计划程序保活即可，无需反代。

---

## 6. 上线后检查清单（Health Check）

- [ ] `GET /api/models` 返回模型列表（说明 Key 生效、能连 SCNet）。
- [ ] 提交一次 `/api/analyze`（带/不带照片）→ 返回 `analysis` + `experience_id`。
- [ ] 上传一张定损照片，`ocr_engine` 应为 `rapidocr`（若 `none` 说明 ONNX 模型未下载成功，查外网）。
- [ ] `GET /api/cases` 能列出案例（含 24 条种子）。
- [ ] 自我净化闭环：对一条经验 `POST /api/feedback`（评分≤2 或写纠正）→ `POST /api/evolve` → `GET /api/pending` 出现待审 → `POST /api/approve` → `GET /api/principles` 出现新原则。
- [ ] **持久化验证**：重启服务后 `experience.db` 仍在、`/api/principles` 仍有之前批准的原则。
- [ ] HTTPS / 域名已配置（对外发布时）。
- [ ] 防火墙只开 80/443，后端 8000 不暴露公网。

---

## 7. 升级 / 维护

- **升级应用代码**：重新拷目录 → 路径 A 重新 `docker compose up -d --build`；路径 B 重启服务。
- **经验库备份**：`experience.db` 是单文件，定期复制即可；也可 `sqlite3 experience.db .dump` 导出。
- **案例库扩展**：编辑 `cases.json` 种子（重启加载）；运行期通过自我净化"批准"新增的案例存在 `experience.db`，不污染种子。
- **切换私有化推理**：把 `SCNET_BASE_URL` 改成自有 vLLM 地址、Key 传 `EMPTY`（`claim_analyzer.py` 已支持），其余零改动。

---

## 8. 安全与合规底线

- API Key 只走环境变量 / `.env` / 平台密钥管理，**绝不写代码、不截图发聊天、不提交 git**。
- 本工具是**初审辅助**，最终以人工核赔与保险条款为准，不得替代合规核赔流程。
- 真实客户数据优先内网 / 私有化处理；SCNet 云端调用请评估隐私合规。
