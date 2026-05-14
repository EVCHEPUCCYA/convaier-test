from __future__ import annotations

from pathlib import Path

from convaier.util.proc import RunResult, run_command


def compose_up_ssh(
    host: str,
    user: str,
    key_file: str,
    remote_path: str,
    compose_file: str,
    service: str | None = None,
) -> RunResult:
    remote_cmd = f"cd {remote_path} && docker compose -f {compose_file} up -d"
    if service:
        remote_cmd += f" {service}"
    cmd = ["ssh"]
    if key_file:
        cmd += ["-i", str(Path(key_file).expanduser())]
    cmd += ["-o", "StrictHostKeyChecking=no", f"{user}@{host}", remote_cmd]
    return run_command(cmd, timeout=180)


def build_image(
    cwd: Path,
    dockerfile: str = "Dockerfile",
    image_name: str = "app",
    tag: str = "latest",
) -> RunResult:
    return run_command(
        ["docker", "build", "-f", dockerfile, "-t", f"{image_name}:{tag}", "."],
        cwd=cwd,
        timeout=600,
    )


def compose_up(
    cwd: Path,
    compose_file: str = "docker-compose.yml",
    service: str | None = None,
) -> RunResult:
    cmd = ["docker", "compose", "-f", compose_file, "up", "-d"]
    if service:
        cmd.append(service)
    return run_command(cmd, cwd=cwd, timeout=120)


def compose_down(
    cwd: Path,
    compose_file: str = "docker-compose.yml",
) -> RunResult:
    return run_command(
        ["docker", "compose", "-f", compose_file, "down"],
        cwd=cwd,
        timeout=60,
    )
