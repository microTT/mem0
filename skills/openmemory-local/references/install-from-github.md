# Install From GitHub

Publish this skill under:

- repo: `microTT/mem0`
- path: `skills/openmemory-local`

After the branch is pushed to GitHub, users can install it in either of these ways. The installed skill will then clone the official `mem0ai/mem0` repo and apply the bundled customization patch; it does not clone the `microTT/mem0` fork for runtime work.

## Install by repo and path

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo microTT/mem0 \
  --path skills/openmemory-local
```

## Install by GitHub URL

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --url https://github.com/microTT/mem0/tree/main/skills/openmemory-local
```

## List installable skills from this repo

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/list-skills.py" \
  --repo microTT/mem0 \
  --path skills
```

Because the skill lives directly under `skills/`, listing must explicitly pass `--path skills`.

After installation, restart Codex so the new skill is picked up.

## First Bootstrap After Install

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/openmemory-local/scripts/openmemory_local.py" \
  bootstrap --dest /path/to/mem0 --write-env --user <user-id>
```
