from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_command(
    cmd: str | list[str],
    cwd: Path | None = None,
    timeout: int = 300,
) -> RunResult:
    use_shell = isinstance(cmd, str)
    if not use_shell:
        cmd_str = cmd[0]
    else:
        cmd_str = cmd.split()[0] if cmd else ""

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=use_shell,
        )
        return RunResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired:
        return RunResult(returncode=-1, stdout="", stderr=f"Timeout after {timeout}s")
    except FileNotFoundError:
        return RunResult(returncode=-1, stdout="", stderr=f"Command not found: {cmd_str}")
