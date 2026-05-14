from __future__ import annotations

import asyncio
import json
import logging

from convaier.agent.client import agent_loop, create_client
from convaier.agent.prompt import build_security_prompt
from convaier.agent.tools import REVIEW_TOOLS
from convaier.context import PipelineContext, ReviewComment, SecurityIssue
from convaier.stages import Stage, StageResult, register
from convaier.util.proc import run_command

log = logging.getLogger("convaier")


def _parse_bandit_json(output: str) -> list[SecurityIssue]:
    issues = []
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return issues

    for result in data.get("results", []):
        severity = result.get("issue_severity", "MEDIUM").lower()
        issues.append(SecurityIssue(
            tool="bandit",
            file=result.get("filename", ""),
            line=result.get("line_number", 0),
            severity=severity,
            message=result.get("issue_text", ""),
            cwe=str(result.get("issue_cwe", {}).get("id", "")),
        ))
    return issues


def _parse_pip_audit_json(output: str) -> list[SecurityIssue]:
    issues = []
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return issues

    vulnerabilities = data if isinstance(data, list) else data.get("dependencies", [])
    for dep in vulnerabilities:
        for vuln in dep.get("vulns", []):
            issues.append(SecurityIssue(
                tool="pip-audit",
                file="requirements",
                line=0,
                severity="high",
                message=f"{dep.get('name', '?')}=={dep.get('version', '?')}: {vuln.get('id', '')} — {vuln.get('description', '')}",
                cwe="",
            ))
    return issues


def _parse_npm_audit_json(output: str) -> list[SecurityIssue]:
    issues = []
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return issues

    _SEV_MAP = {"critical": "critical", "high": "high", "moderate": "warning", "low": "info"}
    seen_sources: set = set()

    for pkg_name, vuln in data.get("vulnerabilities", {}).items():
        severity = _SEV_MAP.get(vuln.get("severity", "low"), "info")
        for item in vuln.get("via", []):
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            if source in seen_sources:
                continue
            seen_sources.add(source)

            title = item.get("title", pkg_name)
            url = item.get("url", "")
            cwe = ", ".join(item.get("cwe", []))
            msg = f"{pkg_name}@{vuln.get('range', '?')}: {title}"
            if url:
                msg += f" → {url}"

            issues.append(SecurityIssue(
                tool="npm-audit",
                file="package.json",
                line=0,
                severity=severity,
                message=msg,
                cwe=cwe,
            ))
    return issues


_PARSERS = {
    "bandit": _parse_bandit_json,
    "pip-audit": _parse_pip_audit_json,
    "npm-audit": _parse_npm_audit_json,
}


def _parse_ai_response(response: str) -> list[ReviewComment]:
    from convaier.agent.parser import parse_model_response
    issues = parse_model_response(response, legacy_prefix="SECURITY")
    return [
        ReviewComment(
            file=i.file,
            line=i.line or 0,
            severity=i.severity,
            message=i.problem,
            reason=i.reason,
            fix=i.fix,
        )
        for i in issues
    ]


async def _run_parallel(analyze_fn, files: list[str], max_workers: int) -> list[ReviewComment]:
    """Запускает analyze_fn для каждого файла с ограничением max_workers параллельных задач."""
    semaphore = asyncio.Semaphore(max_workers)
    results: list[ReviewComment] = []
    lock = asyncio.Lock()

    async def bounded(filename: str) -> None:
        async with semaphore:
            comments = await asyncio.to_thread(analyze_fn, filename)
            async with lock:
                results.extend(comments)

    await asyncio.gather(*[bounded(f) for f in files])
    return results


@register("security")
class SecurityStage(Stage):
    def run(self, ctx: PipelineContext) -> StageResult:
        tools = self.stage_config.get("tools", [
            {"command": "python -m bandit -r . -f json --quiet", "name": "bandit"},
        ])
        ai_review = self.stage_config.get("ai_review", False)
        fail_on_critical = self.stage_config.get("fail_on_critical", True)
        max_workers = self.stage_config.get("max_workers", 1)

        all_issues: list[SecurityIssue] = []

        for tool_cfg in tools:
            name = tool_cfg.get("name", "unknown")
            command = tool_cfg.get("command", "")
            if not command:
                continue

            log.info("  Running %s: %s", name, command)
            result = run_command(command, cwd=ctx.project_root)

            parser = _PARSERS.get(name)
            if parser:
                issues = parser(result.stdout)
            else:
                try:
                    issues = _parse_bandit_json(result.stdout)
                except Exception:
                    issues = []

            all_issues.extend(issues)

            if issues:
                log.warning("  %s: %d issue(s)", name, len(issues))
            else:
                log.info("  %s: OK", name)

        ctx.security_issues = all_issues

        if ai_review and (ctx.git_diff or ctx.changed_files):
            from convaier.ui import print_detail

            use_rag = self.stage_config.get("use_rag", False)

            extra_rules = "\n".join(filter(None, [
                ctx.config.rules.get("global", ""),
                ctx.config.rules.get("security", ""),
            ]))

            code_files = [
                f for f in ctx.changed_files[:20]
                if (ctx.project_root / f).is_file()
                and (ctx.project_root / f).suffix in (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go")
            ]

            def _analyze_file(filename: str) -> list[ReviewComment]:
                client = create_client(ctx.config.ollama)
                fpath = ctx.project_root / filename
                content = fpath.read_text(errors="replace")[:5_000]

                rag_context = ""
                if use_rag:
                    try:
                        from convaier.rag.search import build_rag_context_for_file
                        rag_context = build_rag_context_for_file(
                            filename, content, ctx.project_root, ctx.config.ollama,
                        )
                    except Exception:
                        pass

                file_issues = [i for i in all_issues if i.file.endswith(filename)]
                tool_summary = "\n".join(
                    f"[{i.severity}] {i.tool}: {i.file}:{i.line} — {i.message}"
                    for i in file_issues
                )

                print_detail(f"AI scanning {filename}...")

                try:
                    prompt = build_security_prompt(
                        tool_summary, ctx.git_diff, {filename: content}, rag_context,
                        extra_rules=extra_rules,
                    )
                    messages = [{"role": "user", "content": prompt}]
                    response = agent_loop(
                        client=client,
                        model=ctx.config.ollama.model,
                        messages=messages,
                        tools=REVIEW_TOOLS,
                        project_root=ctx.project_root,
                        max_rounds=3,
                        num_ctx=ctx.config.ollama.num_ctx,
                    )
                    comments = _parse_ai_response(response)
                    if comments:
                        from convaier.ui import render_issue_line
                        for c in comments:
                            print_detail(render_issue_line(c.file, c.line or None, c.severity, c.message))
                    else:
                        print_detail(f"{filename}: OK")
                    return comments
                except Exception as e:
                    print_detail(f"{filename}: AI failed ({e})", "error")
                    return []

            all_ai_comments = asyncio.run(_run_parallel(_analyze_file, code_files, max_workers))
            ctx.security_ai_comments = all_ai_comments
        else:
            all_ai_comments = []

        total = len(all_issues) + len(ctx.security_ai_comments)
        has_critical = any(
            i.severity in ("critical", "high") for i in all_issues
        ) or any(
            c.severity == "critical" for c in ctx.security_ai_comments
        )

        success = not (has_critical and fail_on_critical)
        summary = f"{total} проблем(ы) найдено" if total else "нет проблем безопасности"
        return StageResult(success=success, summary=summary)
