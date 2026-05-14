from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

log = logging.getLogger("convaier.server")


def _inject_token(clone_url: str, token: str) -> str:
    if not token:
        return clone_url
    parsed = urlparse(clone_url)
    if parsed.scheme not in ("http", "https"):
        return clone_url
    port_part = f":{parsed.port}" if parsed.port else ""
    authed = parsed._replace(netloc=f"{token}@{parsed.hostname}{port_part}")
    return urlunparse(authed)


def _run(args: list[str], cwd: Path | None = None, timeout: int = 300) -> None:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args[:3])} failed (exit {result.returncode}):\n{result.stderr[:400]}"
        )


def clone_or_update(
    workspace: Path,
    full_name: str,
    clone_url: str,
    sha: str,
    git_token: str = "",
) -> Path:
    repo_path = workspace / Path(*full_name.split("/"))
    authed_url = _inject_token(clone_url, git_token)

    if not (repo_path / ".git").exists():
        repo_path.mkdir(parents=True, exist_ok=True)
        log.info("[git] cloning %s into %s", full_name, repo_path)
        _run(["git", "clone", authed_url, str(repo_path)], timeout=300)
    else:
        log.info("[git] fetching %s", full_name)
        _run(["git", "fetch", "--prune", authed_url], cwd=repo_path, timeout=120)

    log.info("[git] checkout %s", sha[:8])
    _run(["git", "checkout", "--force", sha], cwd=repo_path, timeout=60)

    return repo_path
