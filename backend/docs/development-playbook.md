# 开发与迭代手册（内部知识库 + AI 中转站）

> 更新时间：2026-03-19

## 1. 文档目标

这份手册用于回答三件事：
1. 为什么选择当前技术栈。
2. 这个 MVP 是按什么工程过程搭起来的。
3. 下一轮迭代应该如何稳步推进。

## 2. 项目目标与边界

### 2.1 目标
- 作为企业内部知识库：支持文档入库、检索、问答。
- 作为 AI 中转站：统一接入模型、记录审计、做基础配额控制。

### 2.2 非目标（MVP 阶段）
- 不做复杂多模态解析。
- 不做精细计费结算。
- 不做多 Region 灾备。

## 3. 技术栈选择与取舍

### 3.1 后端语言与框架
- 选择：`Python 3.11 + FastAPI`
- 原因：
  - 与 AI/RAG 生态（向量库、模型 SDK）耦合成本最低。
  - FastAPI 在异步 API、类型约束、自动文档方面交付快。
- 备选：
  - `Node.js + NestJS`：全栈统一强，但 AI 工具链整合成本略高。
  - `Java + Spring Boot`：治理成熟，但 MVP 速度较慢。

### 3.2 数据与存储
- 选择：`PostgreSQL + pgvector`、`Redis`、`MinIO/S3`
- 原因：
  - PostgreSQL 同时承载业务数据和向量，降低早期系统复杂度。
  - Redis 处理队列和缓存，满足异步入库需求。
  - MinIO/S3 存原始文档，便于版本和归档。
- 何时升级：
  - 当向量规模/检索复杂度上升，可引入 OpenSearch 或独立向量库。

### 3.3 模型网关
- 选择：`LiteLLM`（当前以可配置 URL 接入）
- 原因：
  - 统一多模型调用协议，方便路由、fallback、配额扩展。

### 3.4 运行与交付
- 选择：`Docker Compose（本地） + GitHub Actions（CI）`
- 原因：
  - MVP 目标是先获得稳定可复现的本地和 CI 闭环。

## 4. 架构设计（MVP）

## 4.1 服务拆分
- `gateway-service`：统一入口与健康探针。
- `identity-service`：登录回调、`/me`。
- `knowledge-service`：文档 CRUD、检索接口、入库任务投递。
- `ai-service`：会话与消息、调用模型网关。
- `worker-service`：消费队列，执行解析/切块/向量入库（当前是占位实现）。
- `ops-service`：审计日志与配额查询。

## 4.2 关键链路
1. 入库链路：
`POST /v1/documents -> Redis ingest_jobs -> worker -> chunks/vectors -> documents.status=ready`
2. 问答链路：
`POST /v1/chat/sessions/{id}/messages -> ai-service -> LiteLLM/mock -> chat_messages + request_logs`

## 5. 数据模型设计原则

### 5.1 表结构范围
- 租户/用户：`tenants`, `users`, `tenant_users`
- 知识库：`documents`, `document_chunks`, `chunk_vectors`
- 会话：`chat_sessions`, `chat_messages`
- 治理：`request_logs`, `quota_policies`, `quota_usages`

### 5.2 关键原则
- 每张业务表尽量带 `tenant_id`，保证租户隔离基础能力。
- 文档删除采用软删除（`deleted_at`），保障可追溯。
- 向量索引先用 pgvector HNSW，后续按规模演进。

## 6. 这次开发的实际过程（按提交回放）

1. `a8e7390` `chore(infra)`
- 建立 `docker-compose`、环境变量模板、数据库初始化脚本。

2. `7030b8d` `feat(libs)`
- 建立公共库：鉴权上下文、数据库连接、日志、LLM 客户端。

3. `ef95378` `feat(services)`
- 落地 6 个服务骨架与核心 API。

4. `a0b521a` `chore(tooling)`
- 增加 `Makefile`、`justfile`，统一本地操作入口。

5. `22b8b77` `ci`
- 建立 GitHub Actions：lint、compile、docker build。

6. `2ff339d` `docs(api)`
- 提供 Postman 集合与调用文档。

7. `c67deb8` `fix(libs)`
- 修复 ruff 告警（显式 re-export）。

8. `48001d0` `chore(tooling)`
- 本地命令兼容 `docker-compose` 二进制。

## 7. 开发规范与质量门禁

### 7.1 Commit 规范
- 采用 Conventional Commits：
  - `feat(scope): ...`
  - `fix(scope): ...`
  - `chore(scope): ...`
- 已提供 `commit-msg` 钩子校验脚本：
`backend/scripts/validate_commit_msg.py`

### 7.2 Pre-commit 规范
- 配置文件：`.pre-commit-config.yaml`
- 包含检查：
  - YAML 基础校验
  - 行尾空格/EOF
  - `ruff check --fix`
  - `ruff format`

### 7.3 CI 规范
- `ci.yml`：每次 PR/Push 执行 lint、compile、镜像构建检查。
- `release.yml`：支持 tag 触发和手动触发发布。

## 8. 本地开发操作手册

### 8.1 初始化
1. 复制环境变量：`Copy-Item backend/.env.example backend/.env`
2. 安装依赖：`just install-dev`
3. 安装钩子：`just hooks-install`

### 8.2 日常命令
1. 启动：`just up`
2. 停止：`just down`
3. 日志：`just logs`
4. 校验：`just check`

### 8.3 API 调试
- 导入 Postman 集合：
`backend/docs/postman/internal-kb-ai-gateway.postman_collection.json`

## 9. 迭代路线图（建议）

### 9.1 第一阶段（1-2 周）
- 真正接入文档解析（PDF/Docx/Markdown）。
- 把 worker 的占位向量替换为真实 embedding。
- `rag/search` 从 ILIKE 升级到向量检索 + 过滤。

### 9.2 第二阶段（2-4 周）
- 增加重排（rerank）和答案引用片段。
- 增加文档级权限（部门、标签、密级）。
- 增加基础缓存（query + top_k 级别）。

### 9.3 第三阶段（1-2 个月）
- 引入网关级模型路由策略（成本/时延/质量）。
- 审计增强：请求追踪 ID、错误分类、敏感信息脱敏。
- 加入评测集和离线回归评测。

## 10. 常见坑与规避

1. Docker CLI 可用但 daemon 未启动。
- 现象：`docker version` 只有 Client 信息。
- 处理：确保 Docker Desktop/daemon 正常启动。

2. Windows 下 `python` 命令指向商店别名。
- 处理：优先使用 `py -3.11` 或显式 Python 路径。

3. 本地和 CI 规则不一致。
- 处理：统一走 `pre-commit` 和 `ruff`。

## 11. 后续文档维护建议

1. 每次重要架构调整，补一条 ADR（放在 `backend/docs/adr/`）。
2. 每个里程碑结束更新本手册的“已完成/待完成”状态。
3. 每次发布把 release note 链接回填到本手册。
