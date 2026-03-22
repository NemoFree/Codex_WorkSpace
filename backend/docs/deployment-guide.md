# 部署文档（本地/开发环境，Docker Compose）

> 目标：在一台新机器上，用最少步骤把栈跑起来，并验证 RAG 入库+检索链路 OK。

## 1. 前置条件

### 1.1 必需组件
- Docker Desktop（Windows）或 Docker Engine（Linux/macOS）
- docker-compose（或 compose v2 兼容命令）

### 1.2 Windows 特别说明（WSL2）
如果你在 Windows 用 Docker Desktop（Linux containers）：
- 确保 WSL2/虚拟化相关服务可用
- 如果 Docker Desktop 启动卡住，优先尝试：
  - `wsl --shutdown`
  - 启动服务：`LxssManager`、`vmcompute`
  - 更新 WSL：`wsl --update --web-download`

## 2. 配置文件

### 2.1 创建环境变量文件
在 `backend/` 目录：
- `Copy-Item backend/.env.example backend/.env`

### 2.2 关键环境变量
必需：
- `DATABASE_URL`（默认：`postgresql://app:app@postgres:5432/knowledge`）
- `REDIS_URL`（默认：`redis://redis:6379/0`）

大陆网络建议：
- `DOCKER_REGISTRY=docker.1panel.live`

说明：
- `backend/docker-compose.yml` 里的公共镜像与各服务 Dockerfile 都支持 `DOCKER_REGISTRY` 前缀。
- 不在大陆或可以直连 Docker Hub：不设置也行（默认 `docker.io`）。

## 3. 启动与关闭

### 3.1 启动
从仓库根目录执行：
- `docker-compose -f backend/docker-compose.yml --env-file backend/.env up -d --build`

推荐先跑一次自检（串行输出每一步结果）：
- `just doctor`（或 `just doctor-preflight` 只做启动前检查）

### 3.2 查看状态
- `docker-compose -f backend/docker-compose.yml --env-file backend/.env ps`

### 3.3 停止
- `docker-compose -f backend/docker-compose.yml --env-file backend/.env down`

## 4. 健康检查

各服务 healthz：
- gateway：`http://localhost:8080/healthz`
- identity：`http://localhost:8081/healthz`
- knowledge：`http://localhost:8082/healthz`
- ai：`http://localhost:8083/healthz`
- ops：`http://localhost:8084/healthz`

PowerShell 示例：
```powershell
Invoke-RestMethod http://localhost:8082/healthz
```

## 4.1 可视化控制台（可选，但推荐）
打开 Knowledge Console UI（同一套 API 的可视化操作台）：
- `http://localhost:8082/ui/knowledge`

页面会用你填写的 Header 调用 API；如果你需要看入库状态汇总：
- `GET /v1/admin/ingest/summary`（需要 `X-Role=admin`）

## 5. 端到端 Smoke（入库 -> worker -> 检索）

### 5.1 创建文档（入队）
```powershell
$headers=@{
  "X-Tenant-Id"="11111111-1111-1111-1111-111111111111"
  "X-User-Id"="22222222-2222-2222-2222-222222222222"
  "X-Role"="admin"
}
$body=@{
  title="Smoke Doc"
  source_type="upload"
  content="Hello from smoke test. This document should be chunked and indexed into pgvector."
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8082/v1/documents -Headers $headers -ContentType 'application/json' -Body $body
```

预期返回：
- `status` 为 `queued`
- `document_id` 为 UUID

### 5.2 等待 worker 处理完成
```powershell
$docId="替换成上一步返回的 document_id"
for($i=0;$i -lt 60;$i++){
  $status = (docker exec kb_postgres psql -U app -d knowledge -t -A -c "SELECT status FROM documents WHERE id='$docId'").Trim()
  if($status -eq "ready"){ "READY"; break }
  Start-Sleep -Seconds 1
}
```

### 5.3 检索验证
```powershell
$body=@{query="chunked indexed pgvector"; top_k=5} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8082/v1/rag/search -Headers $headers -ContentType 'application/json' -Body $body
```

预期：
- `hits` 至少 1 条
- 每条命中包含 `chunk_id/content/metadata`
- `score` 为数值（向量检索）或 `null`（fallback ILIKE）

## 6. 常见故障与定位

### 6.1 镜像拉取失败（Docker Hub 超时/无代理）
现象：
- `failed to resolve reference registry-1.docker.io ... dial tcp ... timeout`

处理：
- 设置 `DOCKER_REGISTRY=docker.1panel.live`（或你可用的企业镜像前缀）
- 重新 `up -d --build`

### 6.2 postgres 容器退出，服务报 `Name or service not known`
现象：
- `kb_postgres` 退出
- 其它服务连接 DB 报 `psycopg.OperationalError: [Errno -2] Name or service not known`

处理：
1. 看 postgres 日志：`docker logs kb_postgres --tail 200`
2. 修复 `backend/migrations/001_init.sql`
3. 重新拉起 postgres：`docker-compose ... up -d postgres`
4. 必要时补跑 SQL：
   - `docker exec -i kb_postgres psql -U app -d knowledge -f /docker-entrypoint-initdb.d/001_init.sql`
