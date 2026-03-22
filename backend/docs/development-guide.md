# 开发文档（Internal KB + AI Gateway）

> 目标读者：要在本机进行二次开发/调试的人。  
> 假设：你使用 Windows PowerShell（其他平台同理）。

## 1. 项目结构与服务职责

目录（后端）：
- `backend/services/*-service`：各服务源码 + Dockerfile
- `backend/libs/*`：公共库（鉴权、DB、日志、LLM/Embedding）
- `backend/migrations/001_init.sql`：数据库初始化脚本（pgvector + 基础表 + seed）
- `backend/docker-compose.yml`：本地一键启动栈

服务（MVP）：
- `gateway-service`：API 入口与健康检查
- `identity-service`：身份相关接口（MVP 仅占位）
- `knowledge-service`：文档创建/删除/列表、RAG 检索（向量检索 + ILIKE fallback）
- `ai-service`：chat session/message + 模型调用（LiteLLM 可选）
- `worker-service`：消费 Redis 队列，执行文档入库（分块、embedding、写入 pgvector）
- `ops-service`：审计日志 + 配额查询（MVP）

## 2. 关键链路（你在开发时最常改的地方）

### 2.1 入库链路（Document -> Chunk -> Vector）
1. 调用 `knowledge-service`：`POST /v1/documents`
2. 写入 `documents` 表，`status=queued`
3. 推入 Redis 队列 `ingest_jobs`（携带 `tenant_id/document_id/content`）
4. `worker-service` BLPOP `ingest_jobs`：
   - `documents.status -> processing`
   - 生成源文本（payload content + title/storage_uri）
   - 分块（词窗口 + overlap）
   - 写入 `document_chunks`
   - embedding：优先调用 LiteLLM embeddings（如配置），失败回退确定性 embedding
   - 写入 `chunk_vectors`
   - `documents.status -> ready`（异常则 `failed`）

### 2.2 检索链路（RAG Search）
1. 调用 `knowledge-service`：`POST /v1/rag/search`
2. 生成 query embedding
3. 用 pgvector 排序：`ORDER BY embedding <=> query_vector LIMIT top_k`
4. 若无结果：回退 ILIKE（MVP 兜底）

### 2.3 本地可视化（Knowledge Console UI）
在本地启动栈后，可直接打开：
- `GET http://localhost:8082/ui/knowledge`

这个页面会用你填写的 Header 调用同一套 API（便于在不写脚本的情况下观察入库与检索）：
- Documents：列表、详情、Chunk 列表
- Create Document：创建并入队（触发 worker 入库）
- RAG Search：向量检索（必要时 fallback）
- Ingest Summary：查看队列长度、各状态文档计数、最近文档及 chunk 数
- Delete Document：软删除（仅标记 `deleted_at`）

注意：
- `GET /v1/admin/ingest/summary` 需要 `X-Role=admin`，否则返回 403。

## 3. 开发环境与依赖

### 3.1 依赖版本（建议）
- Python：3.11
- Docker Desktop（Windows）：建议启用 WSL2 模式
- docker-compose：可用即可（本仓库用 `docker-compose` 命令）

### 3.2 本地任务入口
根目录提供：
- `Makefile`（偏类 Unix）
- `justfile`（Windows 友好）

常用：
- `just up`：启动栈
- `just down`：停止栈
- `just logs`：看日志
- `just check`：跑 pre-commit（ruff/format/yaml 等）

## 4. 代码质量与提交规范

### 4.1 Lint/Format
- `ruff check backend`
- `ruff format backend`

### 4.2 pre-commit
仓库配置了 `.pre-commit-config.yaml`：
- ruff lint + format
- 基础 YAML/空格/EOF 检查
- commit-msg：Conventional Commits 校验脚本

说明：
- 在网络受限环境，pre-commit 首次拉取 hook repo 可能失败；这不是代码问题。
- 如果你需要先落盘提交再处理 hook，可以临时用：`git commit --no-verify ...`

## 5. Embedding 与模型调用（可选）

### 5.1 Embedding（RAG）
公共库：`backend/libs/common_embedding`

行为：
- 若 `LITELLM_URL` 为空：使用“确定性哈希 embedding”（便于离线/可测试）
- 若 `LITELLM_URL` 非空：调用 `POST {LITELLM_URL}/embeddings`
  - 失败时默认回退（可用 `EMBEDDING_FALLBACK_ON_ERROR=false` 关闭回退）

相关环境变量：
- `LITELLM_URL`
- `LITELLM_API_KEY`
- `EMBEDDING_MODEL`：默认 `text-embedding-3-small`
- `EMBEDDING_FALLBACK_ON_ERROR`：默认 `true`

### 5.2 Chat Completion（AI）
公共库：`backend/libs/common_llm`
- `LITELLM_URL` 为空：返回 mock（`[mock] {content}`）
- 配置后：调用 `POST {LITELLM_URL}/chat/completions`

## 6. 开发时常见问题与排查顺序

### 6.1 服务 500：优先看容器日志
- `docker-compose -f backend/docker-compose.yml --env-file backend/.env logs --tail=200 knowledge-service`

常见根因：
- 数据库没起来（容器没运行、迁移失败、DNS 解析不到 postgres）
- Redis 没起来（worker/knowledge 入队失败）

### 6.2 Worker 不消费/文档一直 queued
1. 看 worker 日志：
   - `docker-compose ... logs --tail=200 worker-service`
2. 看 Redis 队列长度（可选）：
   - `docker exec kb_redis redis-cli llen ingest_jobs`
3. 看 documents.status：
   - `docker exec kb_postgres psql -U app -d knowledge -c "select id,status from documents order by created_at desc limit 5;"`

### 6.3 pgvector/数据库初始化失败
本项目使用 `/docker-entrypoint-initdb.d/001_init.sql` 初始化。
如果脚本语法错误，postgres 容器会退出，导致其它服务解析不到 `postgres`（表现为 `Name or service not known`）。

处理：
1. 先修 SQL 脚本
2. 重新拉起 postgres
3. 必要时手动补跑脚本（可重复执行）：
   - `docker exec -i kb_postgres psql -U app -d knowledge -f /docker-entrypoint-initdb.d/001_init.sql`
