from __future__ import annotations

import logging
import time

from convaier.context import DeployResult, PipelineContext
from convaier.stages import Stage, StageResult, register
from convaier.util.docker import compose_up, compose_up_ssh

log = logging.getLogger("convaier")


@register("deploy")
class DeployStage(Stage):
    def should_skip(self, ctx: PipelineContext) -> bool:
        if ctx.errors:
            return True
        if ctx.build_result and not ctx.build_result.success:
            return True
        return False

    def run(self, ctx: PipelineContext) -> StageResult:
        env = ctx.env
        env_override = self.stage_config.get("environments", {}).get(env, {}) if env else {}

        compose_file = env_override.get("compose_file") or self.stage_config.get("compose_file", "docker-compose.yml")
        service = env_override.get("service") or self.stage_config.get("service")
        ssh_cfg = env_override.get("ssh") or self.stage_config.get("ssh")

        log.info("  Deploying via %s (env=%s)", compose_file, env or "default")

        t0 = time.monotonic()

        if ssh_cfg:
            host = ssh_cfg["host"]
            user = ssh_cfg.get("user", "ubuntu")
            result = compose_up_ssh(
                host=host,
                user=user,
                key_file=ssh_cfg.get("key_file", ""),
                remote_path=ssh_cfg["remote_path"],
                compose_file=compose_file,
                service=service,
            )
            target = f"{user}@{host}"
        else:
            result = compose_up(ctx.project_root, compose_file, service)
            target = "local"

        duration = time.monotonic() - t0

        ctx.deploy_result = DeployResult(
            service=service or "all",
            success=result.ok,
            output=result.stdout + result.stderr,
            duration=duration,
            target=target,
        )

        env_label = env or "local"
        summary_base = f"'{service or 'all'}' deployed ({env_label} → {target}, {duration:.1f}s)"

        if not result.ok:
            log.error("  Deploy failed:\n%s", result.stderr[-500:])
            return StageResult(success=False, summary=f"Deploy failed: {result.stderr[:100]}")

        return StageResult(success=True, summary=summary_base)
