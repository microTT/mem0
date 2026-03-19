---
name: openmemory-local
description: Clone the official `mem0ai/mem0` repo, apply a bundled local customization patch for OpenMemory, and connect the result to Codex or other MCP clients. Use when the task involves bootstrapping OpenMemory from upstream instead of from a fork, replaying the local DashScope or Qwen customization patch, writing `api/.env` and `ui/.env`, aligning user IDs, persisting config into SQLite through the OpenMemory config API, generating the local SSE MCP URL, or troubleshooting local OpenMemory startup and patch drift.
---

# OpenMemory Local

This skill treats the official `mem0ai/mem0` repo as the source of truth. The local customization lives as a bundled patch inside the skill and should be replayed onto an upstream clone, not copied from a personalized fork.

## Quick Start

1. Run `scripts/openmemory_local.py bootstrap --dest /path/to/mem0 --write-env --user <user-id>` to clone the official repo and apply the bundled patch.
2. Run `scripts/openmemory_local.py doctor --root /path/to/mem0 --ping` to verify patch state, env alignment, and local runtime readiness.
3. Start Colima first on macOS if Docker Desktop is unavailable, then run `make build` and `make up` from `openmemory/`.
4. Persist the intended runtime config with `scripts/openmemory_local.py apply-config --root /path/to/mem0 --apply`.
5. Generate the SSE endpoint with `scripts/openmemory_local.py mcp-url --root /path/to/mem0 --client codex` and wire that URL through `mcp-proxy`.

## Workflow

### 1. Clone Upstream And Replay The Patch

- Prefer the official remote `https://github.com/mem0ai/mem0.git`.
- Use `bootstrap` for the default path:
  - clone upstream `main`
  - create a local working branch
  - apply the bundled patch asset
  - optionally write `api/.env` and `ui/.env`
- Use `apply-patch` if the repo already exists locally and only the customization patch needs to be replayed.
- Use `doctor` to distinguish three states:
  - patch already applied
  - patch ready to apply
  - patch no longer applies cleanly and needs maintenance

### 2. Normalize Env Files

- Keep `api/.env` `USER`, `ui/.env` `NEXT_PUBLIC_USER_ID`, and the MCP URL user id exactly the same.
- Default local profile:
  - `OPENAI_BASE_URL` and `OPENAI_API_BASE`: `https://dashscope.aliyuncs.com/compatible-mode/v1`
  - `OPENMEMORY_LLM_MODEL`: `qwen3-max`
  - `OPENMEMORY_CATEGORIZATION_MODEL`: `qwen3-max`
  - `OPENMEMORY_EMBED_MODEL`: `text-embedding-v4`
  - `OPENMEMORY_EMBED_DIMS`: `2048`
  - `NEXT_PUBLIC_API_URL`: `http://localhost:8765`
- Do not overwrite a real API key unless the user explicitly wants that.
- `bootstrap --write-env` or `env --write` should update env files without forcing a new API key.

### 3. Understand What The Bundled Patch Changes

- OpenMemory UI port becomes `53000`.
- Qdrant storage mounts to `/qdrant/storage`.
- The API runs as a single-process `uvicorn` worker for local SQLite safety.
- OpenMemory config and memory defaults switch to DashScope or Qwen-friendly OpenAI-compatible settings.
- Categorization stops hardcoding `gpt-4o-mini` and uses JSON output through the configured base URL.
- The MCP server customization and supporting OpenMemory files come from the bundled patch asset, not from ad hoc edits in the cloned repo.

### 4. Start And Stop Safely

- On macOS with Colima, check `colima status`, start it if needed, and ensure Docker points at the `colima` context before running `make build` or `make up`.
- Treat `make down` as destructive in this repo. Prefer `docker compose stop` and `docker compose start` for routine stop and start.
- If the UI does not come up on `53000`, inspect logs before changing ports.

### 5. Persist Config Into SQLite

- Changing `.env` or Python defaults does not overwrite the saved `main` config in `api/openmemory.db`.
- After model, base URL, or embedding-dimension changes, run `apply-config --apply` or equivalent `PUT` requests to `/api/v1/config/mem0/llm`, `/embedder`, and `/vector_store`.
- Use `doctor --ping` or `curl http://localhost:8765/api/v1/config/` to confirm the running API returns the intended config.

### 6. Wire MCP Into Codex

- OpenMemory exposes SSE. Codex works most reliably through `mcp-proxy`, turning the SSE endpoint into a local stdio server.
- Generate the URL with `mcp-url`; the expected pattern is `http://localhost:8765/mcp/<client>/sse/<user>`.
- Recommend enabling only `search_memory`, `add_memories`, and `list_memories` first. Leave destructive tools disabled unless the user explicitly wants them.

## Scripts

- `scripts/openmemory_local.py bootstrap`: clone the official mem0 repo when needed, create a local branch, apply the bundled patch, and optionally write env files.
- `scripts/openmemory_local.py doctor`: check repo shape, env alignment, code drift, Docker or Colima availability, and optional API health.
- `scripts/openmemory_local.py apply-patch`: replay the bundled patch onto an existing mem0 checkout.
- `scripts/openmemory_local.py env`: preview or write the local DashScope or Qwen env defaults into `api/.env` and `ui/.env`.
- `scripts/openmemory_local.py apply-config`: print or apply the three config API payloads needed after startup.
- `scripts/openmemory_local.py mcp-url`: print the local SSE MCP URL from the resolved env.

## References

- Load [references/local-deploy.md](references/local-deploy.md) for the detailed checklist, exact commands, and operational caveats.
- Load [references/install-from-github.md](references/install-from-github.md) when the user wants the exact GitHub install or listing commands.
- Use the bundled asset `assets/openmemory-local-custom.patch` as the only source for replaying the local OpenMemory customization on top of upstream.
- When the user wants to install this skill from GitHub, use the repo path `skills/openmemory-local`.
