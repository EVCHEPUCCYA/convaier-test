from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel

from convaier.server.worker import PipelineJob, get_queue, pipeline_worker

log = logging.getLogger("convaier.server")


class _RepoPayload(BaseModel):
    name: str
    full_name: str
    clone_url: str


class PushPayload(BaseModel):
    ref: str
    after: str
    repository: _RepoPayload

    @property
    def branch(self) -> str:
        return self.ref.removeprefix("refs/heads/")


def _validate_github(body: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


def _validate_gogs(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _validate_signature(
    body: bytes,
    secret: str,
    x_hub_signature_256: str | None,
    x_gogs_signature: str | None,
) -> bool:
    if not secret:
        return True
    if x_hub_signature_256:
        return _validate_github(body, x_hub_signature_256, secret)
    if x_gogs_signature:
        return _validate_gogs(body, x_gogs_signature, secret)
    return False


def create_app(workspace: Path, secret: str, git_token: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(pipeline_worker(workspace, git_token))
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="Convaier Webhook Server", lifespan=lifespan)

    @app.post("/webhook", status_code=status.HTTP_200_OK)
    async def webhook(
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
        x_gogs_signature: str | None = Header(default=None),
    ) -> dict:
        body = await request.body()

        if not _validate_signature(body, secret, x_hub_signature_256, x_gogs_signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

        try:
            payload = PushPayload.model_validate_json(body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Bad payload: {exc}") from exc

        if not payload.after.strip("0"):
            return {"status": "ignored", "reason": "branch deleted"}

        job = PipelineJob(
            full_name=payload.repository.full_name,
            clone_url=payload.repository.clone_url,
            sha=payload.after,
            branch=payload.branch,
        )
        await get_queue().put(job)
        log.info("[webhook] queued: %s @ %s (%s)", job.full_name, job.sha[:8], job.branch)
        return {"status": "queued", "repo": job.full_name, "sha": job.sha[:8]}

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "queue_size": get_queue().qsize()}

    return app
