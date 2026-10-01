---
name: cloud-project-deploy
description: 把本地 Docker 化程序/项目部署到阿里云服务器（root@<阿里云服务器公网IP>）并稳定运行的通用方法论。当用户说「部署到云服务器 / 上传项目到云 / 部署 Docker / 项目上云 / 配置二级域名 / 开放签 / 小内存 OOM / 证书」时使用。以开放签（Java Spring Boot + Vue）部署为完整范例，可复用到任何 Docker 化项目。含小内存主机 OOM 调优、SSH 自动重连、Docker Swarm 隔离部署、Let's Encrypt 证书、宿主机 nginx 反代、排错手册。
agent_created: true
---

# 项目上云部署（cloud-project-deploy）

把本地的 Docker 化程序（Java Spring Boot / Node / 任意容器栈）部署到云服务器并**直接可用**的通用工作流。今天的开放签电子签（kaifangqian）是完整范例，后续别的 Docker 项目套用同一套流程即可。

## 何时使用

- 用户说「把 XX 程序部署到云服务器 / 上传到腾讯云阿里云 / 项目上云 / 配个二级域名直接用」。
- 用户给了一个本地目录（如桌面「素材库/合同/kaifangqian-base-master」），要求上云运行。
- 部署后出现 `exit 137` / `502` / `OutOfMemoryError` / 证书问题 / 域名解析问题。
- **与 `wusun-cockpit` 的关系**：本技能是**通用部署方法论**；`wusun-cockpit` 是 `wusun-app` 驾驶舱的专用迭代流程。两者共用同一台机 `<阿里云服务器公网IP>`，但本技能强调**独立隔离部署**，不碰既有 `wusun-app`。

## 连接约定（铁律）

- **目标主机**：`root@<阿里云服务器公网IP>`（Alibaba Cloud Linux 3，阿里云 ECS）。这台机同时跑 `wusun-app`（`ws.aicnpor.cn`）。
- **SSH 口令**：读环境变量 `SSH_PW`（**不要硬编码密码**）。口令存于用户记忆，按需取用。每次部署前：
  ```bash
  SSH_PW="<root口令>" python deploy_to_server.py
  ```
- **SSH 掉线（10054 / WinError 10054）**：云主机 sshd 在拉镜像等长时间空闲时会断。务必用**自动重连**模式（见「已知坑 #0」和 `references/sshlib.py`）。

## 隔离部署原则（与既有程序互不影响）

新增项目必须独立，绝不污染 `wusun-app`：

| 维度 | 既有 wusun-app | 新增项目（例：kaifangqian） |
|---|---|---|
| 部署目录 | `/opt/wusun-app` | `/home/data/<项目名>` |
| 运行方式 | PM2（Node 3000） | Docker Swarm 栈 `<项目名>` |
| 数据库 | SQLite | 独立 MySQL/Redis 容器卷 |
| 公网域名 | `ws.aicnpor.cn` | 新二级域名（A 记录指同一 IP） |
| 端口 | 主机 nginx 直连 3000 | 容器只暴露**高位端口**（如 8088）→ 主机 nginx 反代 |
| Docker 网络 | — | 独立 overlay 网络 `<项目名>_net` |

> 二期「数据对通」：在新增栈内加同步服务或直连其 MySQL 卷，不动 wusun-app。

## 部署流程（7 步，幂等可重复跑）

1. **装 Docker + Swarm**：在 Alinux3 上 `dnf/yum install docker` 失败则回落阿里云 docker-ce 仓库（`references/ensure_docker.sh`），随后 `docker swarm init`。幂等：已运行则跳过。
2. **宿主机内存调优（小内存主机必做）**：`references/ensure_host_memory.sh` 补 4G swapfile + `vm.overcommit_memory=1`，持久化到 `/etc/fstab` 与 `/etc/sysctl.conf`。详见「OOM 调优」一节。
3. **建目录 + 生成强口令**：`/home/data/<项目>/mysql`、`/storage`、`/var/www/certbot`。口令用 `secrets` 模块生成，**本地存 `.secrets.local`**（chmod 600），保证重复部署口令一致（否则已初始化的 MySQL 卷会 Access denied）。
4. **推文件**：解析 yaml 占位符（`${MYSQL_ROOT_PASSWORD}` 等）→ 上传；上传 nginx 虚拟主机到 `/etc/nginx/conf.d/<域名>.conf`；口令存服务器 `secrets.env`（chmod 600）。
5. **`docker stack deploy`**（后台 `nohup` 跑，避免拉镜像期间 SSH 断开）→ 等 5 个容器 `Up` → **初始化数据库**（导入 sql、改应用地址为公网域名）→ 强制 `--force` 重启 api/web 重新连库（规避启动顺序）。
6. **nginx 虚拟主机 + Let's Encrypt**：证书幂等（已存在则跳过申请，避免触发频率限制）；`nginx -t` 通过才 reload。
7. **公网验证**：`curl -w '%{http_code}' https://<域名>/` 和后端 API 探针都应为 200。

## OOM 调优（小内存主机的命门，最值钱）

**核心事实**：很多 Java 应用的镜像 `ENTRYPOINT` 是硬编码 `sh -c "exec java -jar ..."`，**不读 `JAVA_OPTS`**。只能用 JVM 启动器自动读取的 **`JAVA_TOOL_OPTIONS`** 来限制堆。

2G 主机跑 Spring Boot + PowerJob + MySQL + Redis + nginx 必崩，根因有三层：

1. **内核 OOM-kill（exit 137）**：JVM 无堆上限 → RSS 涨满 RAM；即便限了堆，宿主机 `CommitLimit`（`RAM*overcommit_ratio + swap`）不足，启动期提交超限额仍被内核 kill。
   - 修复：补 **4G swapfile** 抬高 CommitLimit + `vm.overcommit_memory=1`（允许换页而非直接 kill）。脚本见 `references/ensure_host_memory.sh`。
2. **java 级 `OutOfMemoryError: Metaspace`**：元空间给 128m 太小（SpringBoot + 调度框架 + Redis 客户端运行期需 200m+），应用虽 Up 但 tomcat 死掉、API 返回 000。
   - 修复：元空间给到 **192m+**，并限制 code cache 为 64m。
3. **Docker cgroup OOM（exit 1）**：容器 `memory limit` 小于 JVM 提交总内存（heap + metaspace + code cache + 堆外线程）。
   - 修复：JVM 总提交 ≈ heap + metaspace + codecache + 堆外(~100m)，容器 limit 留 ~20% 余量。例：api `-Xmx256m -XX:MaxMetaspaceSize=192m -XX:ReservedCodeCacheSize=64m` → 容器 limit **768M**；job `-Xmx256m -XX:MaxMetaspaceSize=160m` → limit **512M**；mysql 512M；redis 128M。
4. **多 Java 应用抢物理内存**：每个 Java 服务都要限（job 默认占 444MB，不限制会挤爆 api）。

**4G 内存主机可放宽**：堆可放到 384m，limit 放宽，基本不再 OOM。

## 域名与证书

- **二级域名不变**：只是 `aicnpor.cn` 的一条 A 记录，改指向新服务器 IP 即可，与哪台机器无关。换机时：把 `qianzhang.aicnpor.cn` 的 A 记录从旧 IP 改到新 IP（在阿里云 DNS 控制台改，AI 改不了域名解析）。
- **证书绑定域名非 IP**：新机器 certbot 重新签发/续期即可。webroot 挑战放 `/var/www/certbot`，nginx 80 端口预留 `.well-known/acme-challenge/`。
- **nginx 反代模式**：web 容器只暴露高位端口（如 8088）→ 宿主机 nginx `proxy_pass http://127.0.0.1:8088` 做 TLS 终止。80/443 统一由宿主机 nginx 接管。虚拟主机模板见 `references/nginx-vhost.conf.example`（改 `server_name` 和 `proxy_pass` 端口即可）。

## 已知坑（必看，今天逐个踩过）

0. **SSH 10054 掉线**：长命令（拉镜像）必断。用 `references/sshlib.py` 模式——**每条命令独立会话 + 自动重连 + `set_keepalive(20)`**；`docker stack deploy` 用 `nohup ... > log 2>&1 &` 后台跑，再轮询日志。
1. **镜像不读 JAVA_OPTS**：硬编码 `java -jar` 启动 → 用 `JAVA_TOOL_OPTIONS` 限堆（见上）。
2. **启动顺序：PowerJob `no server available!`**：api 在 job（PowerJob server）起来前启动 → 重启顺序 `job → api（等 ~70s）→ web`。
3. **nginx 502**：早期是 api 无健康任务；web 经 Swarm VIP（`opensign-api` → `10.0.2.2`）代理，api 任务重启后 VIP 不变，**无需重启 web**。若 web 真的静态 `proxy_pass` 写死 IP 才需重启 web 重新解析。
4. **RSA `Data must not be longer than 245 bytes`**：`cleanData()` 迁移在 `sys_config.system_version < "205"` 时运行，会把已加密的字段（phone/corporationNo/organizationNo）再加密一次。修复：`UPDATE sys_config SET value='205' WHERE type='system_version';` 再重启 api。
5. **MySQL `Access denied`**：重复部署时口令变了但 MySQL 卷已用旧口令初始化。修复：本地 `.secrets.local` 持久化口令 + `docker stack rm` + `rm -rf /home/data/<项目>/mysql` 清卷后重跑。
6. **`%{http_code}` 在 Python `%` 格式化里崩溃**：写成 `%%{http_code}`；或在 bash 里单引号包住、`%%` 转义。
7. **certbot 频率限制**：证书已存在就跳过申请（脚本用 `test -f .../fullchain.pem && echo CERT_EXISTS || certbot ...`）。
8. **阿里云新机选购**：开放签类 Java 栈**最低 4G 内存**才稳；2G 必反复 OOM。轻量应用服务器 2核4G（¥199 抢购/¥298-379 常规）比 ECS 2核4G（¥599+）便宜；u1 企业专享 ¥199 需企业实名。镜像选 **Alibaba Cloud Linux 3**（与 `ensure_docker.sh` 兼容）。

## 套用到新项目时改什么

- `references/mysql-redis.yaml.tpl`：改镜像、网络名、卷路径。
- `references/nginx-vhost.conf.example`：改 `server_name`、证书路径、`proxy_pass` 端口。
- 部署脚本里：`STACK`、`APP_DIR`、`DOMAIN`、镜像 tag、SQL 初始化命令、应用地址改写 SQL。
- **内存参数**：按新项目实际 JVM 调（堆 + 元空间 + code cache + 容器 limit，四者配套）。

## 参考文件

- `references/sshlib.py` — SSH 自动重连 helper（10054 救星）
- `references/ensure_host_memory.sh` — 2G 小内存调优（swap + overcommit）
- `references/ensure_docker.sh` — Alinux3 装 Docker + Swarm
- `references/mysql-redis.yaml.tpl` — MySQL+Redis 隔离栈模板
- `references/nginx-vhost.conf.example` — 宿主机 nginx 虚拟主机模板
