# 复用手册（换电脑快速复刻：开发 + 部署 + 排障）

> 目标：你换一台电脑后，30-60 分钟内把一个“多服务 FastAPI + pgvector + Redis + worker + 可选 LiteLLM”的 MVP 跑起来。  
> 内容基于本次真实开发/部署过程，包含踩坑与对应修复手段。

## 0. 一句话原则

先跑通“最小闭环”（入库 -> worker -> 检索）再做功能扩展；遇到问题先看日志、再看依赖启动顺序、最后看网络/代理。

## 1. 新机器准备清单（按顺序）

### 1.1 系统与工具
- 安装 Git
- 安装 Python 3.11（用于本地 lint/test；服务容器里会自带 Python）
- 安装 Docker Desktop
- 安装 docker-compose（或确保 Docker Desktop 自带 compose 可用）

### 1.2 Windows (WSL2) 必备动作
你在 Windows 上跑 Linux 容器，最常见的两个问题是：
- Docker Desktop 引擎起不来
- WSL kernel/组件不匹配

建议执行顺序（遇到异常时复用）：
1. `wsl --shutdown`
2. 确认服务状态并启动：
   - `Start-Service LxssManager`
   - `Start-Service vmcompute`
3. 更新 WSL：
   - `wsl --update --web-download`
4. 重启 Docker Desktop 后验证：
   - `docker version` 必须同时看到 Client 和 Server

## 2. 大陆网络镜像源策略（可复用到任何项目）

### 2.1 问题现象
Docker 拉取镜像时报：
- `registry-1.docker.io:443 timeout`
- 或 Docker Desktop 提示 no HTTPS proxy

### 2.2 策略
不要在每台机器里手工点 Docker Desktop 设置（可行但不可追踪）；推荐做“工程内可配置”：
- 在 `docker-compose.yml` 中把公共镜像改为：`${DOCKER_REGISTRY:-docker.io}/...`
- 在各服务 Dockerfile 里把基础镜像改为：
  - `ARG DOCKER_REGISTRY=docker.io`
  - `FROM ${DOCKER_REGISTRY}/library/python:3.11-slim`
- 在 `.env.example` 中提供默认：
  - `DOCKER_REGISTRY=docker.1panel.live`

这样你换电脑时只需要改 `.env`，无需改代码。

### 2.3 选源方法（通用）
用一个最小镜像测试可用性（例如 python slim）：
- `docker pull <mirror>/library/python:3.11-slim`

本次实践结果：
- `docker.1panel.live` 可用（python/redis/pgvector/minio 均可拉）
- `docker.m.daocloud.io` 可用（至少 python/pgvector 可拉）
- `docker.1panel.dev` 在本机测试失败（EOF）

## 3. 数据库迁移脚本踩坑（PostgreSQL 保留字）

### 3.1 问题现象
`kb_postgres` 容器初始化时退出，日志里出现：
- `syntax error at or near "window"`

连锁反应：
- 其它服务连接 DB 报 `Name or service not known`
  - 因为 compose 网络里没有正在运行的 `postgres` 服务，容器内 DNS 解析不到。

### 3.2 根因
在 `001_init.sql` 中列名使用了保留字 `window`。

### 3.3 修复模式（可复用）
1. 修 SQL：保留字列名一律改成可读的非保留字，例如 `window_name`
2. 同步改所有依赖查询（如 ops-service）
3. 重新拉起 postgres
4. 对初始化脚本保持可重入（`IF NOT EXISTS` / `ON CONFLICT DO NOTHING`），便于补跑：
   - `docker exec -i kb_postgres psql -U app -d knowledge -f /docker-entrypoint-initdb.d/001_init.sql`

## 4. PowerShell 下 curl 的坑（别名）

### 4.1 问题现象
在 PowerShell 里直接 `curl -sS ...` 报参数错误。

### 4.2 原因
PowerShell 的 `curl` 是 `Invoke-WebRequest` 的别名，不支持 `-sS` 等参数。

### 4.3 解决
统一用：
- `Invoke-RestMethod`（适合 JSON API）
- 或显式调用 `curl.exe`（如果你确定系统里有）

## 5. pre-commit 在网络受限环境的坑

### 5.1 现象
第一次 `git commit` 触发 pre-commit 时，拉取 hook repo 失败（连接重置/超时）。

### 5.2 处理策略
- 先落盘：`git commit --no-verify ...`
- 后续在网络正常时再装 hooks 或跑 `just check`

## 6. 一个可复用的“最小闭环”设计（工程模板）

你要快速搭类似项目时，这个组合能极快跑通 MVP：
- API 服务：FastAPI
- DB：PostgreSQL + pgvector
- 队列：Redis（list + BLPOP）
- worker：一个常驻消费者
- embedding：先用确定性离线 embedding 保证可测试/可演示
- 可选 LiteLLM：通过 `LITELLM_URL` 打开真实模型调用

关键点：
- 所有服务读取 `DATABASE_URL/REDIS_URL`（容器内用服务名 `postgres/redis`）
- RAG 搜索必须有 fallback（在向量未就绪/空库时也能返回）
- schema 初始化脚本必须可重入

## 7. 换电脑一键流程（建议照抄）

1. `Copy-Item backend/.env.example backend/.env`
2. 如果在大陆：编辑 `backend/.env` 设置 `DOCKER_REGISTRY=docker.1panel.live`
3. `docker-compose -f backend/docker-compose.yml --env-file backend/.env up -d --build`
4. `Invoke-RestMethod http://localhost:8082/healthz`
5. 跑 smoke：按 `backend/docs/deployment-guide.md` 第 5 节执行

