# 开发与部署纪要（Chronicle）

> 覆盖范围：从项目初始化到本次 RAG 入库/向量检索闭环跑通，以及在 Windows + Docker Desktop（大陆网络）下部署落地的真实问题与修复过程。  
> 时间基准：Asia/Shanghai（UTC+8）。  
> 目标读者：想快速理解“发生了什么、为什么这么做、遇到什么坑、怎么修”的维护者。

## 0. 环境快照（用于复现问题）

- OS：Windows 10 Home China（从 Docker Desktop service 日志可见）
- Docker Desktop：4.65.0 (221669)
- Docker Engine：29.2.1（linux/amd64）
- Docker CLI：29.2.1（windows/amd64）

## 1. 项目初始化与骨架期（2026-03-18 ~ 2026-03-19）

这一阶段目标：先把“可跑的微服务栈 + 数据库 schema + CI + 本地命令”搭起来，形成可复现闭环。

关键提交（按仓库历史顺序）：
- `a8e7390 chore(infra)`：搭建 compose、环境变量模板、数据库初始化脚本（`backend/migrations/001_init.sql`）。
- `7030b8d feat(libs)`：公共库落地（鉴权头、DB 连接、日志、LLM 客户端）。
- `ef95378 feat(services)`：6 个服务骨架 + worker 骨架。
- `a0b521a chore(tooling)`：增加 `Makefile`、`justfile`，统一操作入口。
- `22b8b77 ci`：GitHub Actions（lint/compile/docker build）。
- `2ff339d docs(api)`：Postman 集合与调用说明。
- `8e113b3 chore(quality)`：pre-commit + commit-msg 校验（Conventional Commits）。
- `609d4a7 (tag: v0.1.0)`：补充迭代手册/架构说明（`backend/docs/development-playbook.md`）。

结果：
- 栈能启动（在网络通畅前提下），各服务提供 `/healthz`。
- 基础链路定义清晰：`knowledge -> redis ingest_jobs -> worker -> pgvector`。

## 2. RAG 闭环增强（2026-03-20 ~ 2026-03-21）

这一阶段目标：把 worker 从“占位写一条 chunk+零向量”升级为“真实分块 + embedding + 向量检索”，并补齐测试。

### 2.1 关键实现点

1. 引入公共 embedding/分块库 `backend/libs/common_embedding`：
- 分块：按词窗口（max_words + overlap_words）生成 chunk。
- embedding：
  - 默认：确定性哈希 embedding（1536 维），保证离线可用、可测试、可演示。
  - 可选：配置 `LITELLM_URL` 后走 `POST /embeddings`，失败默认回退（`EMBEDDING_FALLBACK_ON_ERROR=true`）。

2. worker 入库逻辑升级：
- 从 Redis `ingest_jobs` 读取 payload（`tenant_id/document_id/content`）。
- 状态机：`queued -> processing -> ready/failed`。
- 对已软删除文档做保护：不会把 deleted 文档状态改回 ready。
- 写入：
  - `document_chunks`（含 chunk metadata：strategy/chunk_index/chunk_total）
  - `chunk_vectors`（pgvector embedding + model 名称）

3. knowledge-service 检索升级：
- `/v1/documents` 支持提交 `content`，并把 `content` 随队列入库（MVP：不依赖对象存储）。
- `/v1/rag/search`：
  - 优先向量检索（pgvector `<=>` 排序）
  - 若无结果：回退 ILIKE（保证空库/入库未完成也能给出结果）
  - 返回 `score`（向量检索时为数值，fallback 时为 `null`）

4. 单测补齐（不依赖 Docker）：
- `common_embedding`：分块、确定性 embedding、远程 embedding mock + 回退测试。
- `knowledge-service`：入队 payload 含 content、向量检索无结果 fallback、向量检索有 score。
- `worker-service`：核心入库 SQL 调用次数/行为（mock DB cursor）。

### 2.2 对应提交

- `188764c feat(rag): add chunked ingest vector search and tests`
  - 引入 `common_embedding`
  - worker/knowledge 改造
  - 新增 `backend/tests/*`

## 3. 部署排障与可复现化（2026-03-21 ~ 2026-03-22）

这一阶段目标：在 Windows + Docker Desktop + 大陆网络条件下，把 compose 真正跑通，并把“靠运气/靠 UI 设置”改成“工程内可配置、可记录、可复用”。

### 3.1 问题 1：Docker Desktop 引擎无法启动（WSL2/KERNEL 更新）

现象：
- `docker version` 只有 Client；或 Server 报 `Docker Desktop is unable to start`
- compose 连接 npipe 失败

定位：
- Docker Desktop backend 日志出现 `wslUpdateRequired=true`

修复步骤（在 Windows PowerShell）：
1. `wsl --shutdown`
2. 启动依赖服务：
   - `Start-Service LxssManager`
   - `Start-Service vmcompute`
3. 更新 WSL（实际执行用 web-download 才更稳）：
   - `wsl --update --web-download`
4. 重启 Docker Desktop，直到 `docker version` 同时出现 Client + Server。

### 3.2 问题 2：Docker Hub 拉取镜像超时（无 HTTPS proxy）

现象：
- `registry-1.docker.io:443 timeout`
- Docker Desktop 提示没有 HTTPS proxy，直连失败

策略（工程化而非手工配置）：
- 引入 `DOCKER_REGISTRY` 作为镜像前缀：
  - compose 里的公共镜像改为 `${DOCKER_REGISTRY:-docker.io}/...`
  - 各服务 Dockerfile 支持：
    - `ARG DOCKER_REGISTRY=docker.io`
    - `FROM ${DOCKER_REGISTRY}/library/python:3.11-slim`
  - `.env.example` 提供大陆默认：`DOCKER_REGISTRY=docker.1panel.live`

镜像源测试过程（以 python slim 为探针）：
- `docker.1panel.dev`：失败（EOF）
- `docker.1panel.live`：成功
- `docker.m.daocloud.io`：成功

最终选择：
- 以 `docker.1panel.live` 作为示例默认（拉通了 python/redis/pgvector/minio）。

### 3.3 问题 3：postgres 初始化脚本失败导致整条链路断裂（保留字）

现象：
- `kb_postgres` 退出
- 其它服务连接 DB 报：
  - `psycopg.OperationalError: [Errno -2] Name or service not known`
- 容器内解析 `redis` 正常、解析 `postgres` 失败（因为 postgres 根本没在网络里运行起来）

定位：
- `docker logs kb_postgres` 看到：
  - `syntax error at or near "window"`

根因：
- `backend/migrations/001_init.sql` 的 `quota_policies` 使用了列名 `window`（PostgreSQL 保留字）。

修复：
- 列名改为 `window_name`，并同步改 `ops-service` 查询字段。

恢复步骤（无需重建卷，脚本可重入）：
1. 删除退出的 postgres 容器（不删卷）：
   - `docker rm kb_postgres`
2. 拉起 postgres：
   - `docker-compose -f backend/docker-compose.yml --env-file backend/.env up -d postgres`
3. 补跑初始化 SQL（可重复执行）：
   - `docker exec -i kb_postgres psql -U app -d knowledge -f /docker-entrypoint-initdb.d/001_init.sql`

### 3.4 PowerShell 下的 curl 别名坑

现象：
- PowerShell 中 `curl -sS ...` 报参数错误

原因：
- `curl` 在 PowerShell 是 `Invoke-WebRequest` 的别名

解决：
- 文档与脚本统一使用 `Invoke-RestMethod` 作为 API 调用方式。

### 3.5 端到端 smoke 最终结果

启动：
- `docker-compose -f backend/docker-compose.yml --env-file backend/.env up -d --build`

验证：
1. `POST /v1/documents` 返回 `queued`
2. `worker-service` 处理后，DB 中 `documents.status` 变为 `ready`
3. `POST /v1/rag/search` 返回 hits 且带 score（向量检索生效）

对应提交：
- `4addb7b fix(docker): add registry prefix and repair pg init`
- `f52bc41 docs: add dev deploy and reuse guides`

## 4. 推荐的维护方式（从这次经验提炼）

- “会阻塞部署的外部变量”要工程内配置化：镜像前缀、模型网关 URL、fallback 策略等，尽量不要依赖 UI 点选。
- init SQL 必须可重入：`IF NOT EXISTS` / `ON CONFLICT DO NOTHING`，便于补跑修复。
- 先跑通最小闭环再扩展：
  - `create_document -> worker -> rag_search` 是核心价值最短路径。
- Windows 环境优先把命令写成 PowerShell 友好版本，避免 `curl`/编码/权限问题。

