from __future__ import annotations

import json
import logging

from convaier.context import LintIssue, PipelineContext
from convaier.stages import Stage, StageResult, register
from convaier.util.proc import run_command

log = logging.getLogger("convaier")


def _parse_eslint_json(output: str, project_root: str = "") -> list[LintIssue]:
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return []
    issues = []
    for file_result in data:
        filepath = file_result.get("filePath", "")
        if project_root and filepath.startswith(project_root):
            filepath = filepath[len(project_root):].lstrip("/\\")
        for msg in file_result.get("messages", []):
            rule = msg.get("ruleId") or "?"
            sev = "warning" if msg.get("severity", 2) >= 2 else "info"
            issues.append(LintIssue(
                tool="eslint",
                file=filepath,
                line=msg.get("line", 0),
                message=f"[{rule}] {msg.get('message', '')}",
                severity=sev,
            ))
    return issues


_PARSERS = {
    "eslint": _parse_eslint_json,
}


def _parse_lint_output(tool_name: str, stdout: str) -> list[LintIssue]:
    issues = []
    for line in stdout.splitlines():
        parts = line.split(":", 3)
        if len(parts) >= 4:
            try:
                issues.append(LintIssue(
                    tool=tool_name,
                    file=parts[0].strip(),
                    line=int(parts[1].strip()),
                    message=parts[3].strip() if len(parts) > 3 else parts[2].strip(),
                ))
            except (ValueError, IndexError):
                continue
    return issues


@register("lint")
class LintStage(Stage):
    def run(self, ctx: PipelineContext) -> StageResult:
        tools = self.stage_config.get("tools", [])
        if not tools:
            return StageResult(success=True, summary="линтеры не настроены")

        fail_on_error = self.stage_config.get("fail_on_error", True)
        all_issues: list[LintIssue] = []
        any_failed = False

        for tool_cfg in tools:
            name = tool_cfg.get("name", "unknown")
            command = tool_cfg.get("command", "")
            if not command:
                continue

            log.info("  Running %s: %s", name, command)
            result = run_command(command, cwd=ctx.project_root)

            parser = _PARSERS.get(name)
            if parser:
                issues = parser(result.stdout, str(ctx.project_root))
            else:
                issues = _parse_lint_output(name, result.stdout)
            all_issues.extend(issues)

            if not result.ok:
                any_failed = True
                log.warning("  %s: %d issue(s)", name, len(issues))
            else:
                log.info("  %s: OK", name)

        ctx.lint_results = all_issues
        ctx.lint_passed = not any_failed

        success = not any_failed or not fail_on_error
        summary = f"{len(all_issues)} замечаний от {len(tools)} инструмента(ов)"
        return StageResult(success=success, summary=summary)
