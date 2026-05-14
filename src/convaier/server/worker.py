from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("convaier.server")

_queue: asyncio.Queue[PipelineJob] = asyncio.Queue()


@dataclass
class PipelineJob:
    full_name: str
    clone_url: str
    sha: str
    branch: str


def get_queue() -> asyncio.Queue[PipelineJob]:
    return _queue


async def pipeline_worker(workspace: Path, git_token: str) -> None:
    from convaier.config import load_config
    from convaier.pipeline import run_pipeline
    from convaier.server.git_ops import clone_or_update

    while True:
        job: PipelineJob = await _queue.get()
        log.info("[worker] start: %s @ %s (%s)", job.full_name, job.sha[:8], job.branch)
        try:
            repo_path: Path = await asyncio.to_thread(
                clone_or_update,
                workspace,
                job.full_name,
                job.clone_url,
                job.sha,
                git_token,
            )
            config_path = repo_path / "convaier.yml"
            if not config_path.exists():
                log.warning("[worker] no convaier.yml in %s — skipping", job.full_name)
                continue

            config = await asyncio.to_thread(load_config, config_path)
            await asyncio.to_thread(run_pipeline, config)
            log.info("[worker] done: %s", job.full_name)
        except Exception:
            log.exception("[worker] job failed: %s", job.full_name)
        finally:
            _queue.task_done()
