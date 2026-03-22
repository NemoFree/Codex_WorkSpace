import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from redis import Redis

from libs.common_auth import Actor, get_actor
from libs.common_db import get_conn
from libs.common_embedding import embed_text, to_vector_literal
from libs.common_observability import setup_logging

setup_logging("knowledge-service")

app = FastAPI(title="knowledge-service", version="0.1.0")
redis_client = Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
)


class DocumentCreate(BaseModel):
    title: str
    source_type: str = Field(default="upload")
    storage_uri: str | None = None
    content: str | None = Field(default=None, min_length=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


KNOWLEDGE_UI_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Knowledge Console</title>
  <style>
    :root {
      --bg: #f3f2ec;
      --bg-strong: #e9e5db;
      --panel: #fffdf6;
      --ink: #181612;
      --muted: #6a6257;
      --line: #e6decb;
      --accent: #0d6a58;
      --accent-soft: #dff4ed;
      --danger: #ad3f3f;
      --shadow: 0 12px 30px rgba(24, 22, 18, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", "Noto Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(900px 350px at 85% -10%, #d3f0e6 0%, rgba(211, 240, 230, 0) 60%),
        linear-gradient(180deg, var(--bg) 0%, #f8f7f2 100%);
      min-height: 100vh;
    }
    .wrap {
      max-width: 1280px;
      margin: 0 auto;
      padding: 20px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 20px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel);
      box-shadow: var(--shadow);
      margin-bottom: 16px;
    }
    .title {
      margin: 0;
      font-size: 26px;
      letter-spacing: -0.02em;
    }
    .sub {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 8px 12px;
      font-size: 12px;
      background: #fff;
      color: var(--muted);
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #8a8376;
    }
    .dot.ok { background: #1c8a72; }
    .grid {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 16px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .card h2 {
      margin: 0;
      font-size: 16px;
      letter-spacing: 0.01em;
    }
    .card-hd {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: #fffef8;
    }
    .card-bd {
      padding: 14px 16px;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .controls-right {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      user-select: none;
    }
    .toggle input {
      width: 16px;
      height: 16px;
    }
    input, textarea, button {
      font: inherit;
    }
    input[type="text"], textarea {
      width: 100%;
      border: 1px solid #d6cfbe;
      border-radius: 10px;
      padding: 10px 12px;
      outline: none;
      background: #fff;
      color: var(--ink);
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    input[type="text"]:focus, textarea:focus {
      border-color: #77b7a8;
      box-shadow: 0 0 0 3px rgba(13, 106, 88, 0.12);
    }
    textarea {
      min-height: 92px;
      resize: vertical;
    }
    .inline {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
      margin-bottom: 8px;
    }
    button {
      border: 1px solid #c8c0ae;
      background: #fff;
      color: var(--ink);
      border-radius: 10px;
      padding: 8px 12px;
      cursor: pointer;
    }
    button:hover {
      background: #fbf8ef;
    }
    .btn-accent {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    .btn-accent:hover {
      background: #0b5a4b;
    }
    .muted {
      color: var(--muted);
      font-size: 12px;
    }
    .list {
      max-height: 420px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
    }
    .row {
      padding: 10px 12px;
      border-bottom: 1px solid #efe8d8;
      cursor: pointer;
    }
    .row:last-child {
      border-bottom: none;
    }
    .row:hover {
      background: #f9f7ef;
    }
    .row.active {
      background: var(--accent-soft);
      border-left: 3px solid var(--accent);
      padding-left: 9px;
    }
    .row-title {
      font-weight: 600;
      font-size: 14px;
      margin: 0 0 4px;
    }
    .row-meta {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
    }
    .kv {
      display: grid;
      grid-template-columns: 140px minmax(0, 1fr);
      row-gap: 8px;
      column-gap: 10px;
      font-size: 13px;
      margin-bottom: 14px;
    }
    .kv b {
      color: var(--muted);
      font-weight: 600;
    }
    .pre {
      font-family: "JetBrains Mono", "Consolas", monospace;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      margin: 0;
      max-height: 220px;
      overflow: auto;
    }
    .chunk {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      padding: 10px;
      margin-bottom: 10px;
    }
    .chunk-hd {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }
    .hit {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      padding: 10px;
      margin-bottom: 10px;
    }
    .status-ok { color: #156b57; }
    .status-bad { color: var(--danger); }
    .danger {
      border-color: rgba(173, 63, 63, 0.35);
      color: var(--danger);
    }
    .danger:hover {
      background: rgba(173, 63, 63, 0.06);
    }
    @media (max-width: 1024px) {
      .grid {
        grid-template-columns: 1fr;
      }
      .inline {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="topbar">
      <div>
        <h1 class="title">Knowledge Console</h1>
        <p class="sub">Read and operate your current knowledge base in one page.</p>
      </div>
      <div class="pill"><span id="healthDot" class="dot"></span><span id="healthText">checking service...</span></div>
    </section>

    <section class="grid">
      <article class="card">
        <header class="card-hd">
          <h2>Documents</h2>
          <div class="controls-right">
            <label class="toggle">
              <input id="autoRefresh" type="checkbox" checked />
              <span>Auto refresh</span>
            </label>
            <button id="refreshBtn">Refresh</button>
          </div>
        </header>
        <div class="card-bd">
          <div class="inline">
            <input id="tenantId" type="text" placeholder="Tenant ID" value="11111111-1111-1111-1111-111111111111" />
            <input id="userId" type="text" placeholder="User ID" value="22222222-2222-2222-2222-222222222222" />
            <input id="role" type="text" placeholder="Role" value="admin" />
          </div>
          <div class="muted">Headers are used for all API calls on this page.</div>
          <div style="height: 10px"></div>
          <div id="docList" class="list"></div>
          <div style="height: 12px"></div>
          <h2 style="margin: 0 0 8px; font-size: 15px;">Ingest Summary</h2>
          <div class="controls">
            <button id="summaryBtn">Refresh Summary</button>
          </div>
          <div style="height: 8px"></div>
          <p id="summaryText" class="pre">loading...</p>
        </div>
      </article>

      <article class="card">
        <header class="card-hd">
          <h2>Document Detail</h2>
          <span id="selectedState" class="muted">none selected</span>
        </header>
        <div class="card-bd">
          <div id="docDetail" class="kv"></div>
          <div class="controls">
            <button id="deleteBtn" class="danger">Delete Document</button>
            <span id="deleteMsg" class="muted"></span>
          </div>

          <h2 style="margin: 0 0 8px; font-size: 15px;">Create Document</h2>
          <input id="newTitle" type="text" placeholder="Document title" />
          <div style="height: 8px"></div>
          <textarea id="newContent" placeholder="Paste text content for indexing..."></textarea>
          <div style="height: 8px"></div>
          <button id="createBtn" class="btn-accent">Create & Queue</button>
          <span id="createMsg" class="muted"></span>

          <div style="height: 16px"></div>
          <h2 style="margin: 0 0 8px; font-size: 15px;">Chunks</h2>
          <div id="chunks"></div>

          <div style="height: 12px"></div>
          <h2 style="margin: 0 0 8px; font-size: 15px;">Search (RAG)</h2>
          <input id="searchQuery" type="text" placeholder="Try: smoke test pgvector" />
          <div style="height: 8px"></div>
          <button id="searchBtn">Search</button>
          <div style="height: 8px"></div>
          <div id="hits"></div>
        </div>
      </article>
    </section>
  </div>

  <script>
    const state = {
      docs: [],
      selectedId: null
    };

    function headers() {
      return {
        "Content-Type": "application/json",
        "X-Tenant-Id": document.getElementById("tenantId").value.trim(),
        "X-User-Id": document.getElementById("userId").value.trim(),
        "X-Role": document.getElementById("role").value.trim()
      };
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        ...options,
        headers: {
          ...headers(),
          ...(options.headers || {})
        }
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(path + " -> " + res.status + " " + txt);
      }
      return res.json();
    }

    function fmt(v) {
      if (v === null || v === undefined || v === "") return "-";
      return String(v);
    }

    function renderDocList() {
      const box = document.getElementById("docList");
      if (!state.docs.length) {
        box.innerHTML = "<div class='row'><p class='row-meta'>No documents.</p></div>";
        return;
      }
      box.innerHTML = state.docs.map((d) => {
        const active = d.id === state.selectedId ? "active" : "";
        return `
          <div class="row ${active}" data-id="${d.id}">
            <p class="row-title">${d.title}</p>
            <p class="row-meta">${d.status} | ${d.source_type}</p>
            <p class="row-meta">${d.id}</p>
          </div>
        `;
      }).join("");
      box.querySelectorAll(".row[data-id]").forEach((el) => {
        el.addEventListener("click", () => selectDoc(el.getAttribute("data-id")));
      });
    }

    function renderDocDetail(doc) {
      const node = document.getElementById("docDetail");
      if (!doc) {
        node.innerHTML = "<b>Info</b><span>-</span>";
        document.getElementById("selectedState").textContent = "none selected";
        return;
      }
      node.innerHTML = `
        <b>ID</b><span>${fmt(doc.id)}</span>
        <b>Title</b><span>${fmt(doc.title)}</span>
        <b>Status</b><span>${fmt(doc.status)}</span>
        <b>Source Type</b><span>${fmt(doc.source_type)}</span>
        <b>Storage URI</b><span>${fmt(doc.storage_uri)}</span>
        <b>Created At</b><span>${fmt(doc.created_at)}</span>
      `;
      document.getElementById("selectedState").textContent = "selected: " + doc.id;
    }

    function renderChunks(items) {
      const node = document.getElementById("chunks");
      if (!items || !items.length) {
        node.innerHTML = "<div class='muted'>No chunks yet.</div>";
        return;
      }
      node.innerHTML = items.map((c) => `
        <section class="chunk">
          <div class="chunk-hd">
            <span>chunk_no=${fmt(c.chunk_no)} | tokens=${fmt(c.token_count)}</span>
            <span>${fmt(c.id)}</span>
          </div>
          <p class="pre">${fmt(c.content)}</p>
        </section>
      `).join("");
    }

    function renderHits(hits) {
      const node = document.getElementById("hits");
      if (!hits || !hits.length) {
        node.innerHTML = "<div class='muted'>No hits.</div>";
        return;
      }
      node.innerHTML = hits.map((h) => `
        <section class="hit">
          <div class="chunk-hd">
            <span>${fmt(h.chunk_id)}</span>
            <span>score=${h.score === null ? "-" : Number(h.score).toFixed(6)}</span>
          </div>
          <p class="pre">${fmt(h.content)}</p>
          <p class="pre">${JSON.stringify(h.metadata || {}, null, 2)}</p>
        </section>
      `).join("");
    }

    async function refreshHealth() {
      const dot = document.getElementById("healthDot");
      const txt = document.getElementById("healthText");
      try {
        const data = await fetch("/healthz").then((r) => r.json());
        dot.classList.add("ok");
        txt.textContent = data.status + " | " + data.service;
      } catch (err) {
        dot.classList.remove("ok");
        txt.textContent = "health check failed";
      }
    }

    async function loadDocs() {
      const data = await api("/v1/documents?limit=100&offset=0", { method: "GET" });
      state.docs = data.items || [];
      if (!state.selectedId && state.docs.length) {
        state.selectedId = state.docs[0].id;
      }
      renderDocList();
      if (state.selectedId) {
        await selectDoc(state.selectedId);
      } else {
        renderDocDetail(null);
        renderChunks([]);
      }
    }

    async function selectDoc(id) {
      state.selectedId = id;
      renderDocList();
      const doc = await api("/v1/documents/" + id, { method: "GET" });
      renderDocDetail(doc);
      const chunks = await api("/v1/documents/" + id + "/chunks?limit=200&offset=0", { method: "GET" });
      renderChunks(chunks.items || []);
    }

    async function deleteDoc() {
      const msg = document.getElementById("deleteMsg");
      if (!state.selectedId) return;
      const doc = state.docs.find((d) => d.id === state.selectedId);
      const title = doc ? doc.title : state.selectedId;
      if (!confirm("Delete document?\n\n" + title + "\n\nThis is a soft delete.")) return;
      msg.textContent = "deleting...";
      msg.className = "muted";
      try {
        await api("/v1/documents/" + state.selectedId, { method: "DELETE" });
        msg.textContent = "deleted";
        msg.className = "muted status-ok";
        state.selectedId = null;
        await loadDocs();
      } catch (err) {
        msg.textContent = String(err);
        msg.className = "muted status-bad";
      }
    }

    async function createDoc() {
      const title = document.getElementById("newTitle").value.trim();
      const content = document.getElementById("newContent").value.trim();
      const msg = document.getElementById("createMsg");
      if (!title) {
        msg.textContent = "title is required";
        msg.className = "muted status-bad";
        return;
      }
      msg.textContent = "creating...";
      msg.className = "muted";
      const payload = {
        title,
        source_type: "upload",
        content: content || null
      };
      try {
        const data = await api("/v1/documents", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        msg.textContent = "queued: " + data.document_id;
        msg.className = "muted status-ok";
        await loadDocs();
      } catch (err) {
        msg.textContent = String(err);
        msg.className = "muted status-bad";
      }
    }

    async function doSearch() {
      const q = document.getElementById("searchQuery").value.trim();
      if (!q) return;
      const data = await api("/v1/rag/search", {
        method: "POST",
        body: JSON.stringify({ query: q, top_k: 8 })
      });
      renderHits(data.hits || []);
    }

    document.getElementById("refreshBtn").addEventListener("click", loadDocs);
    document.getElementById("deleteBtn").addEventListener("click", deleteDoc);
    document.getElementById("createBtn").addEventListener("click", createDoc);
    document.getElementById("searchBtn").addEventListener("click", doSearch);
    document.getElementById("searchQuery").addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch();
    });

    async function refreshSummary() {
      const node = document.getElementById("summaryText");
      node.textContent = "loading...";
      try {
        const data = await api("/v1/admin/ingest/summary", { method: "GET" });
        node.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        node.textContent = String(err);
      }
    }

    document.getElementById("summaryBtn").addEventListener("click", refreshSummary);

    function scheduleAutoRefresh() {
      const enabled = document.getElementById("autoRefresh").checked;
      if (!enabled) return;
      setTimeout(async () => {
        try {
          await refreshHealth();
          await refreshSummary();
          await loadDocs();
        } finally {
          scheduleAutoRefresh();
        }
      }, 4000);
    }

    (async () => {
      await refreshHealth();
      await refreshSummary();
      await loadDocs();
      scheduleAutoRefresh();
    })();
  </script>
</body>
</html>
"""


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "knowledge-service"}


@app.get("/ui/knowledge", response_class=HTMLResponse)
def knowledge_ui() -> str:
    return KNOWLEDGE_UI_HTML


@app.post("/v1/documents")
def create_document(
    payload: DocumentCreate, actor: Actor = Depends(get_actor)
) -> dict[str, str]:
    doc_id = str(uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (id, tenant_id, title, source_type, storage_uri, status, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    doc_id,
                    actor.tenant_id,
                    payload.title,
                    payload.source_type,
                    payload.storage_uri,
                    "queued",
                    actor.user_id,
                    datetime.now(timezone.utc),
                ),
            )

    redis_client.rpush(
        "ingest_jobs",
        json.dumps(
            {
                "tenant_id": actor.tenant_id,
                "document_id": doc_id,
                "content": payload.content,
            }
        ),
    )
    return {"document_id": doc_id, "status": "queued"}


@app.get("/v1/admin/ingest/summary")
def ingest_summary(actor: Actor = Depends(get_actor)) -> dict:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="forbidden")

    queue_len = -1
    try:
        queue_len = int(redis_client.llen("ingest_jobs"))
    except Exception:
        queue_len = -1

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*)
                FROM documents
                WHERE tenant_id = %s AND deleted_at IS NULL
                GROUP BY status
                """,
                (actor.tenant_id,),
            )
            rows = cur.fetchall()
            status_counts = {r[0]: int(r[1]) for r in rows}

            cur.execute(
                """
                SELECT d.id, d.title, d.status, d.created_at, COUNT(dc.id) AS chunk_count
                FROM documents d
                LEFT JOIN document_chunks dc ON dc.document_id = d.id
                WHERE d.tenant_id = %s AND d.deleted_at IS NULL
                GROUP BY d.id, d.title, d.status, d.created_at
                ORDER BY d.created_at DESC
                LIMIT 10
                """,
                (actor.tenant_id,),
            )
            recent = cur.fetchall()

    recent_documents = [
        {
            "id": str(r[0]),
            "title": r[1],
            "status": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "chunk_count": int(r[4]) if r[4] is not None else 0,
        }
        for r in recent
    ]

    return {
        "tenant_id": actor.tenant_id,
        "queue_len": queue_len,
        "status_counts": status_counts,
        "recent_documents": recent_documents,
    }


@app.get("/v1/documents")
def list_documents(
    actor: Actor = Depends(get_actor),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, source_type, status, created_at
                FROM documents
                WHERE tenant_id = %s AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (actor.tenant_id, limit, offset),
            )
            rows = cur.fetchall()

    items = [
        {
            "id": str(r[0]),
            "title": r[1],
            "source_type": r[2],
            "status": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]
    return {"items": items}


@app.get("/v1/documents/{document_id}")
def get_document(document_id: str, actor: Actor = Depends(get_actor)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, source_type, storage_uri, status, created_at
                FROM documents
                WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
                """,
                (document_id, actor.tenant_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="document not found")

    return {
        "id": str(row[0]),
        "title": row[1],
        "source_type": row[2],
        "storage_uri": row[3],
        "status": row[4],
        "created_at": row[5].isoformat() if row[5] else None,
    }


@app.get("/v1/documents/{document_id}/chunks")
def list_document_chunks(
    document_id: str,
    actor: Actor = Depends(get_actor),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM documents
                WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
                """,
                (document_id, actor.tenant_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="document not found")

            cur.execute(
                """
                SELECT id, chunk_no, content, token_count, metadata_jsonb, created_at
                FROM document_chunks
                WHERE document_id = %s AND tenant_id = %s
                ORDER BY chunk_no ASC
                LIMIT %s OFFSET %s
                """,
                (document_id, actor.tenant_id, limit, offset),
            )
            rows = cur.fetchall()

    items = [
        {
            "id": str(r[0]),
            "chunk_no": r[1],
            "content": r[2],
            "token_count": r[3],
            "metadata": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]
    return {"document_id": document_id, "items": items}


@app.delete("/v1/documents/{document_id}")
def delete_document(
    document_id: str, actor: Actor = Depends(get_actor)
) -> dict[str, bool]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET deleted_at = %s, status = 'deleted'
                WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
                """,
                (datetime.now(timezone.utc), document_id, actor.tenant_id),
            )
            deleted = cur.rowcount > 0

    if not deleted:
        raise HTTPException(status_code=404, detail="document not found")

    return {"deleted": True}


@app.post("/v1/rag/search")
def rag_search(payload: SearchRequest, actor: Actor = Depends(get_actor)) -> dict:
    query_vector = to_vector_literal(embed_text(payload.query))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT dc.id, dc.content, dc.metadata_jsonb, 1 - (cv.embedding <=> %s::vector) AS score
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                JOIN chunk_vectors cv ON cv.chunk_id = dc.id
                WHERE dc.tenant_id = %s
                  AND cv.tenant_id = %s
                  AND d.tenant_id = %s
                  AND d.deleted_at IS NULL
                ORDER BY cv.embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    query_vector,
                    actor.tenant_id,
                    actor.tenant_id,
                    actor.tenant_id,
                    query_vector,
                    payload.top_k,
                ),
            )
            rows = cur.fetchall()

            if not rows:
                cur.execute(
                    """
                    SELECT dc.id, dc.content, dc.metadata_jsonb, NULL::double precision AS score
                    FROM document_chunks dc
                    JOIN documents d ON d.id = dc.document_id
                    WHERE dc.tenant_id = %s
                      AND d.tenant_id = %s
                      AND d.deleted_at IS NULL
                      AND dc.content ILIKE %s
                    LIMIT %s
                    """,
                    (
                        actor.tenant_id,
                        actor.tenant_id,
                        f"%{payload.query}%",
                        payload.top_k,
                    ),
                )
                rows = cur.fetchall()

    hits = [
        {
            "chunk_id": str(r[0]),
            "content": r[1],
            "metadata": r[2],
            "score": float(r[3]) if r[3] is not None else None,
        }
        for r in rows
    ]
    return {"query": payload.query, "hits": hits}
