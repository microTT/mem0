# Local Deploy Checklist

Use this checklist when the task is to self-host OpenMemory locally with DashScope or Qwen defaults and connect it to Codex through MCP.

The expected bootstrap flow is:

1. Clone the official `mem0ai/mem0` repo.
2. Apply the bundled customization patch from `assets/openmemory-local-custom.patch`.
3. Write env defaults.
4. Build and run the local stack.
5. Persist runtime config through the OpenMemory config API.

## Baseline

- Target repo layout: `mem0/openmemory/`
- Official source repo: `https://github.com/mem0ai/mem0.git`
- Bundled patch source: fork commit `34926f15` (`Customize OpenMemory for local DashScope deployment`)
- Local API: `http://localhost:8765`
- Local UI: `http://localhost:53000`
- Default client name: `codex`
- Default vector store: local Qdrant in Docker
- Default models:
  - LLM: `qwen3-max`
  - Categorization: `qwen3-max`
  - Embedder: `text-embedding-v4`
  - Embedding dims: `2048`

## Env Defaults

Prefer generating these files with the skill script:

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/openmemory-local/scripts/openmemory_local.py" \
  bootstrap --dest /path/to/mem0 --write-env --user <user-id>
```

Or update an existing clone:

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/openmemory-local/scripts/openmemory_local.py" \
  env --root /path/to/mem0 --user <user-id> --write
```

Set or verify these keys in `openmemory/api/.env`:

```env
OPENAI_API_KEY=<dashscope-key>
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
USER=<user-id>
OPENMEMORY_LLM_MODEL=qwen3-max
OPENMEMORY_CATEGORIZATION_MODEL=qwen3-max
OPENMEMORY_EMBED_MODEL=text-embedding-v4
OPENMEMORY_EMBED_DIMS=2048
```

Set or verify these keys in `openmemory/ui/.env`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8765
NEXT_PUBLIC_USER_ID=<user-id>
```

Keep the user id exactly the same in:

- `api/.env` `USER`
- `ui/.env` `NEXT_PUBLIC_USER_ID`
- the generated MCP URL

## Required Code Shape

Before starting services, confirm the bundled patch has been applied:

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/openmemory-local/scripts/openmemory_local.py" \
  doctor --root /path/to/mem0
```

The doctor output should report the customization patch as already applied. The patch should leave these repo-local assumptions in place:

- `openmemory/docker-compose.yml`
  - Qdrant volume mounts to `/qdrant/storage`
  - API command is `uvicorn main:app --host 0.0.0.0 --port 8765`
  - local flow does not use `--reload` or multi-worker SQLite
- `openmemory/api/app/routers/config.py`
  - LLM config exposes `openai_base_url`
  - embedder config exposes `openai_base_url` and `embedding_dims`
  - defaults point to DashScope or Qwen env keys
- `openmemory/api/app/utils/memory.py`
  - fallback config keeps `openai_base_url`
  - fallback embedder config keeps `embedding_dims`
- `openmemory/api/app/utils/categorization.py`
  - uses `OPENAI_BASE_URL`
  - uses `response_format={"type": "json_object"}`
  - does not hardcode `gpt-4o-mini`
  - does not call `beta.chat.completions.parse(...)`

## macOS And Colima

If Docker Desktop is unavailable on macOS, use Colima:

```bash
colima status
colima start --cpu 4 --memory 8 --disk 60
docker context use colima
docker version
docker compose version
docker ps
```

Only continue when `docker ps` succeeds.

## Start Services

Run these from `openmemory/`:

```bash
make build
make up
```

Open the local endpoints:

```bash
open http://localhost:53000
open http://localhost:8765/docs
```

If you need to stop without deleting data, use:

```bash
docker compose stop
docker compose start
```

Do not use `make down` for routine stop and start in this repo. It removes volumes and deletes `api/openmemory.db`.

## Persist Runtime Config

After startup, write the intended config into SQLite. `.env` changes alone are not enough once the database already contains `main` config rows.

Use the skill script:

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/openmemory-local/scripts/openmemory_local.py" \
  apply-config --root /path/to/mem0 --apply
```

Or inspect the payloads first:

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/openmemory-local/scripts/openmemory_local.py" \
  apply-config --root /path/to/mem0
```

Then confirm:

```bash
curl http://localhost:8765/api/v1/config/
```

## MCP Wiring

Generate the SSE URL:

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/openmemory-local/scripts/openmemory_local.py" \
  mcp-url --root /path/to/mem0 --client codex
```

Typical Codex setup uses `mcp-proxy`:

```toml
[mcp_servers.openmemory]
command = "/absolute/path/to/mcp-proxy"
args = ["http://localhost:8765/mcp/codex/sse/<user-id>"]
enabled_tools = ["search_memory", "add_memories", "list_memories"]
disabled_tools = ["delete_all_memories"]
```

## Verification Order

1. `bootstrap` or `apply-patch` finishes without patch conflicts.
2. `doctor` reports that the bundled customization patch is already applied.
3. The DashScope or OpenAI-compatible key is present.
4. `make build` and `make up` start the stack.
5. `apply-config --apply` succeeds.
6. `curl http://localhost:8765/api/v1/config/` returns the expected models and dims.
7. Codex can see the OpenMemory MCP tools through `mcp-proxy`.
