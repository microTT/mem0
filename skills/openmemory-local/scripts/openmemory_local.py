#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_API_URL = "http://localhost:8765"
DEFAULT_LLM_MODEL = "qwen3-max"
DEFAULT_CATEGORY_MODEL = "qwen3-max"
DEFAULT_EMBED_MODEL = "text-embedding-v4"
DEFAULT_EMBED_DIMS = 2048
DEFAULT_COLLECTION = "openmemory"
DEFAULT_VECTOR_HOST = "mem0_store"
DEFAULT_VECTOR_PORT = 6333
DEFAULT_CLIENT = "codex"
DEFAULT_REPO_URL = "https://github.com/mem0ai/mem0.git"
DEFAULT_REPO_REF = "main"
DEFAULT_PATCH_BRANCH = "openmemory-local-custom"
PATCH_RELATIVE_PATH = ("assets", "openmemory-local-custom.patch")
ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class SkillError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap and manage a local OpenMemory deployment from the official mem0 repo."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser(
        "bootstrap",
        help="Clone the official mem0 repo when needed, create a local branch, and apply the bundled custom patch.",
    )
    bootstrap.add_argument("--dest", default="mem0", help="Destination directory for the mem0 repo root.")
    bootstrap.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="Official mem0 git remote to clone.")
    bootstrap.add_argument("--ref", default=DEFAULT_REPO_REF, help="Git ref to clone from the official repo.")
    bootstrap.add_argument("--branch", default=DEFAULT_PATCH_BRANCH, help="Branch name to create after a fresh clone.")
    bootstrap.add_argument("--user", help="Shared user id for api/.env, ui/.env, and the MCP URL.")
    bootstrap.add_argument("--api-key", help="Optional API key to write into api/.env.")
    bootstrap.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible base URL.")
    bootstrap.add_argument("--api-url", default=DEFAULT_API_URL, help="Local OpenMemory API URL.")
    bootstrap.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help="Default LLM model.")
    bootstrap.add_argument("--categorization-model", default=DEFAULT_CATEGORY_MODEL, help="Default categorization model.")
    bootstrap.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL, help="Default embedding model.")
    bootstrap.add_argument("--embed-dims", type=int, default=DEFAULT_EMBED_DIMS, help="Default embedding dimensions.")
    bootstrap.add_argument("--write-env", action="store_true", help="Write local env defaults after clone and patch.")
    bootstrap.set_defaults(func=run_bootstrap)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check repo shape, patch state, env alignment, and local runtime readiness.",
    )
    doctor.add_argument("--root", help="Path to the mem0 repo root or the openmemory directory.")
    doctor.add_argument("--ping", action="store_true", help="Also check the local API health endpoint.")
    doctor.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    doctor.set_defaults(func=run_doctor)

    env = subparsers.add_parser(
        "env",
        help="Preview or write local env defaults into api/.env and ui/.env.",
    )
    env.add_argument("--root", help="Path to the mem0 repo root or the openmemory directory.")
    env.add_argument("--user", help="Shared user id for api/.env, ui/.env, and the MCP URL.")
    env.add_argument("--api-key", help="Optional API key to write into api/.env.")
    env.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible base URL.")
    env.add_argument("--api-url", default=DEFAULT_API_URL, help="Local OpenMemory API URL.")
    env.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help="Default LLM model.")
    env.add_argument("--categorization-model", default=DEFAULT_CATEGORY_MODEL, help="Default categorization model.")
    env.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL, help="Default embedding model.")
    env.add_argument("--embed-dims", type=int, default=DEFAULT_EMBED_DIMS, help="Default embedding dimensions.")
    env.add_argument("--client", default=DEFAULT_CLIENT, help="Client name used when printing the MCP URL.")
    env.add_argument("--write", action="store_true", help="Write the computed values back to the env files.")
    env.set_defaults(func=run_env)

    apply_patch_cmd = subparsers.add_parser(
        "apply-patch",
        help="Apply the bundled customization patch to an existing mem0 checkout.",
    )
    apply_patch_cmd.add_argument("--root", help="Path to the mem0 repo root or the openmemory directory.")
    apply_patch_cmd.set_defaults(func=run_apply_patch)

    apply_config = subparsers.add_parser(
        "apply-config",
        help="Print or apply the config API payloads for llm, embedder, and vector_store.",
    )
    apply_config.add_argument("--root", help="Path to the mem0 repo root or the openmemory directory.")
    apply_config.add_argument("--api-url", help="Override the API URL. Defaults to ui/.env or localhost.")
    apply_config.add_argument("--vector-host", default=DEFAULT_VECTOR_HOST, help="Vector store host inside Docker.")
    apply_config.add_argument("--vector-port", type=int, default=DEFAULT_VECTOR_PORT, help="Vector store port.")
    apply_config.add_argument("--collection-name", default=DEFAULT_COLLECTION, help="Vector collection name.")
    apply_config.add_argument("--apply", action="store_true", help="Send the payloads to the running API.")
    apply_config.set_defaults(func=run_apply_config)

    mcp_url = subparsers.add_parser("mcp-url", help="Print the local OpenMemory SSE MCP URL.")
    mcp_url.add_argument("--root", help="Path to the mem0 repo root or the openmemory directory.")
    mcp_url.add_argument("--api-url", help="Override the API URL. Defaults to ui/.env or localhost.")
    mcp_url.add_argument("--user", help="Override the shared user id.")
    mcp_url.add_argument("--client", default=DEFAULT_CLIENT, help="Client name segment in the MCP URL.")
    mcp_url.set_defaults(func=run_mcp_url)

    return parser.parse_args()


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def patch_file() -> Path:
    return skill_root().joinpath(*PATCH_RELATIVE_PATH)


def is_openmemory_dir(path: Path) -> bool:
    return (path / "docker-compose.yml").is_file() and (path / "api").is_dir() and (path / "ui").is_dir()


def is_mem0_root(path: Path) -> bool:
    return (path / ".git").exists() and is_openmemory_dir(path / "openmemory")


def candidate_paths(root_hint: str | None) -> List[Path]:
    base = Path(root_hint).expanduser().resolve() if root_hint else Path.cwd().resolve()
    candidates: List[Path] = [base]
    candidates.extend(base.parents)
    return candidates


def resolve_repo_paths(root_hint: str | None) -> Tuple[Path, Path]:
    for candidate in candidate_paths(root_hint):
        if is_mem0_root(candidate):
            return candidate, candidate / "openmemory"
        if is_openmemory_dir(candidate) and (candidate.parent / ".git").exists():
            return candidate.parent, candidate
        if is_openmemory_dir(candidate / "openmemory") and (candidate / ".git").exists():
            return candidate, candidate / "openmemory"
    raise SystemExit("Could not locate a mem0 repo root or openmemory directory from the provided path.")


def parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE_RE.match(raw_line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def upsert_env_file(path: Path, updates: Dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    seen = set()
    new_lines: List[str] = []

    for line in lines:
        match = ENV_LINE_RE.match(line)
        if match and match.group(1) in updates:
            key = match.group(1)
            new_lines.append(f"{key}={updates[key]}\n")
            seen.add(key)
        else:
            new_lines.append(line if line.endswith("\n") else f"{line}\n")

    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}\n")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(new_lines), encoding="utf-8")


def run_command(command: Sequence[str], cwd: Path | None = None, timeout: int = 30) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, "timed out"

    output = (result.stdout or result.stderr).strip()
    if result.returncode == 0:
        return True, output or "ok"
    return False, output or f"exit {result.returncode}"


def run_or_raise(command: Sequence[str], cwd: Path | None = None, timeout: int = 300) -> str:
    ok, output = run_command(command, cwd=cwd, timeout=timeout)
    if not ok:
        raise SkillError(f"{' '.join(command)} failed: {output}")
    return output


def git_output(repo_root: Path, args: Sequence[str]) -> str:
    return run_or_raise(["git", "-C", str(repo_root), *args], timeout=120)


def add_item(target: List[Dict[str, str]], severity: str, subject: str, detail: str) -> None:
    target.append({"severity": severity, "subject": subject, "detail": detail})


def summarize_updates(current: Dict[str, str], desired: Dict[str, str]) -> List[Tuple[str, str, str]]:
    summary: List[Tuple[str, str, str]] = []
    for key, value in desired.items():
        if key not in current:
            status = "new"
        elif current[key] == value:
            status = "unchanged"
        else:
            status = "updated"
        summary.append((status, key, value))
    return summary


def resolve_user(api_env: Dict[str, str], ui_env: Dict[str, str], override: str | None) -> str:
    if override:
        return override
    return (
        api_env.get("USER")
        or ui_env.get("NEXT_PUBLIC_USER_ID")
        or os.environ.get("USER")
        or "default_user"
    )


def resolve_api_url(ui_env: Dict[str, str], override: str | None) -> str:
    return (override or ui_env.get("NEXT_PUBLIC_API_URL") or DEFAULT_API_URL).rstrip("/")


def build_mcp_url(api_url: str, client: str, user: str) -> str:
    return f"{api_url.rstrip('/')}/mcp/{client}/sse/{user}"


def build_env_updates(
    api_env: Dict[str, str],
    ui_env: Dict[str, str],
    user: str | None,
    api_key: str | None,
    base_url: str,
    api_url: str,
    llm_model: str,
    categorization_model: str,
    embed_model: str,
    embed_dims: int,
) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    resolved_user = resolve_user(api_env, ui_env, user)
    api_updates = {
        "OPENAI_BASE_URL": base_url,
        "OPENAI_API_BASE": base_url,
        "USER": resolved_user,
        "OPENMEMORY_LLM_MODEL": llm_model,
        "OPENMEMORY_CATEGORIZATION_MODEL": categorization_model,
        "OPENMEMORY_EMBED_MODEL": embed_model,
        "OPENMEMORY_EMBED_DIMS": str(embed_dims),
    }
    if api_key is not None:
        api_updates["OPENAI_API_KEY"] = api_key

    ui_updates = {
        "NEXT_PUBLIC_API_URL": api_url,
        "NEXT_PUBLIC_USER_ID": resolved_user,
    }

    return resolved_user, api_updates, ui_updates


def patch_state(repo_root: Path, patch_path: Path) -> str:
    ready, _ = run_command(["git", "-C", str(repo_root), "apply", "--check", str(patch_path)], timeout=120)
    if ready:
        return "ready"
    reversed_ok, _ = run_command(
        ["git", "-C", str(repo_root), "apply", "--reverse", "--check", str(patch_path)],
        timeout=120,
    )
    if reversed_ok:
        return "applied"
    return "conflict"


def ensure_patch_asset() -> Path:
    asset = patch_file()
    if not asset.exists():
        raise SystemExit(f"Bundled patch not found: {asset}")
    return asset


def clone_upstream_repo(dest: Path, repo_url: str, ref: str) -> Path:
    if dest.exists():
        raise SkillError(f"Destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_or_raise(["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(dest)], timeout=600)
    return dest


def maybe_create_branch(repo_root: Path, branch: str, created_clone: bool) -> str:
    current_branch = git_output(repo_root, ["branch", "--show-current"]).strip()
    if not branch:
        return current_branch
    if current_branch == branch:
        return current_branch
    if created_clone:
        run_or_raise(["git", "-C", str(repo_root), "switch", "-c", branch], timeout=120)
        return branch
    return current_branch


def apply_bundled_patch(repo_root: Path) -> str:
    bundled_patch = ensure_patch_asset()
    state = patch_state(repo_root, bundled_patch)
    if state == "applied":
        return "already_applied"
    if state == "conflict":
        raise SkillError("Bundled patch does not apply cleanly to this repo state.")
    run_or_raise(["git", "-C", str(repo_root), "apply", str(bundled_patch)], timeout=120)
    return "applied_now"


def run_bootstrap(args: argparse.Namespace) -> int:
    dest = Path(args.dest).expanduser().resolve()
    created_clone = False

    if dest.exists():
        if is_mem0_root(dest):
            repo_root = dest
        elif is_openmemory_dir(dest) and (dest.parent / ".git").exists():
            repo_root = dest.parent
        else:
            raise SystemExit(f"Destination exists but is not a mem0 repo root: {dest}")
    else:
        repo_root = clone_upstream_repo(dest, args.repo_url, args.ref)
        created_clone = True

    openmemory_dir = repo_root / "openmemory"
    branch = maybe_create_branch(repo_root, args.branch, created_clone)
    patch_result = apply_bundled_patch(repo_root)

    if args.write_env:
        api_env_path = openmemory_dir / "api" / ".env"
        ui_env_path = openmemory_dir / "ui" / ".env"
        api_env = parse_env_file(api_env_path)
        ui_env = parse_env_file(ui_env_path)
        _, api_updates, ui_updates = build_env_updates(
            api_env,
            ui_env,
            args.user,
            args.api_key,
            args.base_url,
            args.api_url,
            args.llm_model,
            args.categorization_model,
            args.embed_model,
            args.embed_dims,
        )
        upsert_env_file(api_env_path, api_updates)
        upsert_env_file(ui_env_path, ui_updates)

    print(f"Repo root: {repo_root}")
    print(f"OpenMemory dir: {openmemory_dir}")
    print(f"Origin: {git_output(repo_root, ['config', '--get', 'remote.origin.url']).strip()}")
    print(f"Branch: {branch}")
    print(f"Patch: {patch_result}")
    if args.write_env:
        print("Env: wrote api/.env and ui/.env defaults")
    else:
        print("Env: not modified")
    print(f"Next: cd {openmemory_dir} && make build && make up")
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    repo_root, openmemory_dir = resolve_repo_paths(args.root)
    api_env_path = openmemory_dir / "api" / ".env"
    ui_env_path = openmemory_dir / "ui" / ".env"
    api_env = parse_env_file(api_env_path)
    ui_env = parse_env_file(ui_env_path)

    failures: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    passes: List[Dict[str, str]] = []

    bundled_patch = ensure_patch_asset()
    patch_lines = sum(1 for _ in bundled_patch.open("r", encoding="utf-8"))
    add_item(passes, "pass", "bundled patch", f"{bundled_patch} ({patch_lines} lines)")

    add_item(passes, "pass", "repo root", str(repo_root))
    add_item(passes, "pass", "openmemory dir", str(openmemory_dir))

    origin_ok, origin_output = run_command(
        ["git", "-C", str(repo_root), "config", "--get", "remote.origin.url"],
        timeout=30,
    )
    if origin_ok and ("mem0ai/mem0" in origin_output or origin_output == DEFAULT_REPO_URL):
        add_item(passes, "pass", "origin", origin_output)
    elif origin_ok:
        add_item(warnings, "warn", "origin", f"repo origin is not official: {origin_output}")
    else:
        add_item(warnings, "warn", "origin", origin_output)

    current_branch_ok, current_branch = run_command(
        ["git", "-C", str(repo_root), "branch", "--show-current"],
        timeout=30,
    )
    if current_branch_ok:
        add_item(passes, "pass", "branch", current_branch)

    current_patch_state = patch_state(repo_root, bundled_patch)
    if current_patch_state == "applied":
        add_item(passes, "pass", "custom patch", "bundled customization patch is already applied")
    elif current_patch_state == "ready":
        add_item(warnings, "warn", "custom patch", "bundled customization patch is not applied yet")
    else:
        add_item(failures, "fail", "custom patch", "bundled customization patch does not apply cleanly")

    if api_env_path.exists():
        add_item(passes, "pass", "api/.env", f"found {api_env_path}")
    else:
        add_item(warnings, "warn", "api/.env", "missing api/.env")

    if ui_env_path.exists():
        add_item(passes, "pass", "ui/.env", f"found {ui_env_path}")
    else:
        add_item(warnings, "warn", "ui/.env", "missing ui/.env")

    shared_user = api_env.get("USER")
    ui_user = ui_env.get("NEXT_PUBLIC_USER_ID")
    if shared_user and ui_user and shared_user == ui_user:
        add_item(passes, "pass", "user-id", f"api and ui agree on {shared_user}")
    elif shared_user or ui_user:
        add_item(warnings, "warn", "user-id", f"api USER={shared_user!r}, ui NEXT_PUBLIC_USER_ID={ui_user!r}")
    else:
        add_item(warnings, "warn", "user-id", "no shared user id found in env files")

    if "OPENAI_API_KEY" in api_env:
        add_item(passes, "pass", "api/.env OPENAI_API_KEY", "present")
    else:
        add_item(warnings, "warn", "api/.env OPENAI_API_KEY", "missing")

    for key in (
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENMEMORY_LLM_MODEL",
        "OPENMEMORY_CATEGORIZATION_MODEL",
        "OPENMEMORY_EMBED_MODEL",
        "OPENMEMORY_EMBED_DIMS",
    ):
        if key in api_env:
            add_item(passes, "pass", f"api/.env {key}", api_env[key])
        else:
            add_item(warnings, "warn", f"api/.env {key}", "missing")

    if "NEXT_PUBLIC_API_URL" in ui_env:
        add_item(passes, "pass", "ui/.env NEXT_PUBLIC_API_URL", ui_env["NEXT_PUBLIC_API_URL"])
    else:
        add_item(warnings, "warn", "ui/.env NEXT_PUBLIC_API_URL", "missing")

    makefile_text = (openmemory_dir / "Makefile").read_text(encoding="utf-8")
    if "docker compose down -v" in makefile_text and "rm -f api/openmemory.db" in makefile_text:
        add_item(warnings, "warn", "Makefile", "make down is destructive in this repo")

    docker_ok, docker_output = run_command(["docker", "compose", "version"])
    if docker_ok:
        add_item(passes, "pass", "docker compose", docker_output)
    else:
        add_item(warnings, "warn", "docker compose", docker_output)

    docker_ps_ok, docker_ps_output = run_command(["docker", "ps"])
    if docker_ps_ok:
        add_item(passes, "pass", "docker ps", "daemon reachable")
    else:
        add_item(warnings, "warn", "docker ps", docker_ps_output)

    context_ok, context_output = run_command(["docker", "context", "show"])
    if context_ok:
        add_item(passes, "pass", "docker context", context_output)
    else:
        add_item(warnings, "warn", "docker context", context_output)

    if platform.system() == "Darwin":
        colima_ok, colima_output = run_command(["colima", "status"])
        if colima_ok:
            add_item(passes, "pass", "colima", colima_output)
        else:
            add_item(warnings, "warn", "colima", colima_output)

    if args.ping:
        api_url = resolve_api_url(ui_env, None)
        try:
            request = Request(f"{api_url}/api/v1/config/")
            with urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")
            add_item(passes, "pass", "api health", f"{api_url}/api/v1/config/ reachable ({len(body)} bytes)")
        except (HTTPError, URLError) as error:
            add_item(warnings, "warn", "api health", str(error))

    report = {
        "repo_root": str(repo_root),
        "openmemory_dir": str(openmemory_dir),
        "patch_state": current_patch_state,
        "failures": failures,
        "warnings": warnings,
        "passes": passes,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"Repo root: {repo_root}")
        print(f"OpenMemory dir: {openmemory_dir}")
        for bucket_name, bucket in (("PASS", passes), ("WARN", warnings), ("FAIL", failures)):
            for item in bucket:
                print(f"[{bucket_name}] {item['subject']}: {item['detail']}")
        print(f"Summary: {len(failures)} fail, {len(warnings)} warn, {len(passes)} pass")

    return 1 if failures else 0


def run_env(args: argparse.Namespace) -> int:
    _, openmemory_dir = resolve_repo_paths(args.root)
    api_env_path = openmemory_dir / "api" / ".env"
    ui_env_path = openmemory_dir / "ui" / ".env"
    api_env = parse_env_file(api_env_path)
    ui_env = parse_env_file(ui_env_path)

    user, api_updates, ui_updates = build_env_updates(
        api_env,
        ui_env,
        args.user,
        args.api_key,
        args.base_url,
        args.api_url,
        args.llm_model,
        args.categorization_model,
        args.embed_model,
        args.embed_dims,
    )

    print(f"OpenMemory dir: {openmemory_dir}")
    print("api/.env")
    for status, key, value in summarize_updates(api_env, api_updates):
        print(f"  [{status}] {key}={value}")
    if "OPENAI_API_KEY" not in api_env and args.api_key is None:
        print("  [warn] OPENAI_API_KEY is still missing and was not provided")

    print("ui/.env")
    for status, key, value in summarize_updates(ui_env, ui_updates):
        print(f"  [{status}] {key}={value}")

    if args.write:
        upsert_env_file(api_env_path, api_updates)
        upsert_env_file(ui_env_path, ui_updates)
        print("Wrote updates to api/.env and ui/.env")
    else:
        print("Dry run only. Re-run with --write to persist these values.")

    print(f"MCP URL: {build_mcp_url(args.api_url, args.client, user)}")
    return 0


def run_apply_patch(args: argparse.Namespace) -> int:
    repo_root, _ = resolve_repo_paths(args.root)
    result = apply_bundled_patch(repo_root)
    print(f"Repo root: {repo_root}")
    print(f"Patch: {result}")
    return 0


def build_payloads(
    api_env: Dict[str, str],
    vector_host: str,
    vector_port: int,
    collection_name: str,
) -> Dict[str, Dict[str, object]]:
    llm_model = api_env.get("OPENMEMORY_LLM_MODEL", DEFAULT_LLM_MODEL)
    embed_model = api_env.get("OPENMEMORY_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    embed_dims = int(api_env.get("OPENMEMORY_EMBED_DIMS", str(DEFAULT_EMBED_DIMS)))

    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": llm_model,
                "temperature": 0.1,
                "api_key": "env:OPENAI_API_KEY",
                "openai_base_url": "env:OPENAI_BASE_URL",
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": embed_model,
                "api_key": "env:OPENAI_API_KEY",
                "openai_base_url": "env:OPENAI_BASE_URL",
                "embedding_dims": embed_dims,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": collection_name,
                "host": vector_host,
                "port": vector_port,
                "embedding_model_dims": embed_dims,
            },
        },
    }


def put_json(url: str, payload: Dict[str, object]) -> Dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> Dict[str, object]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def run_apply_config(args: argparse.Namespace) -> int:
    _, openmemory_dir = resolve_repo_paths(args.root)
    api_env = parse_env_file(openmemory_dir / "api" / ".env")
    ui_env = parse_env_file(openmemory_dir / "ui" / ".env")
    api_url = resolve_api_url(ui_env, args.api_url)
    payloads = build_payloads(
        api_env,
        args.vector_host,
        args.vector_port,
        args.collection_name,
    )

    if not args.apply:
        print(json.dumps(payloads, indent=2, ensure_ascii=True))
        print("Dry run only. Re-run with --apply to send these payloads to the API.")
        return 0

    try:
        for section, payload in payloads.items():
            result = put_json(f"{api_url}/api/v1/config/mem0/{section}", payload)
            print(f"Updated {section}: {json.dumps(result, ensure_ascii=True)}")
        full_config = get_json(f"{api_url}/api/v1/config/")
        print(json.dumps(full_config, indent=2, ensure_ascii=True))
        return 0
    except (HTTPError, URLError) as error:
        print(f"Failed to apply config at {api_url}: {error}", file=sys.stderr)
        return 1


def run_mcp_url(args: argparse.Namespace) -> int:
    _, openmemory_dir = resolve_repo_paths(args.root)
    api_env = parse_env_file(openmemory_dir / "api" / ".env")
    ui_env = parse_env_file(openmemory_dir / "ui" / ".env")
    user = resolve_user(api_env, ui_env, args.user)
    api_url = resolve_api_url(ui_env, args.api_url)
    print(build_mcp_url(api_url, args.client, user))
    return 0


def main() -> int:
    args = parse_args()
    try:
        return args.func(args)
    except SkillError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
