from __future__ import annotations

import asyncio
import logging
import re

from convaier.agent.client import agent_loop, create_client
from convaier.agent.prompt import build_review_prompt
from convaier.agent.tools import REVIEW_TOOLS
from convaier.context import LintIssue, PipelineContext, ReviewComment
from convaier.stages import Stage, StageResult, register
from convaier.ui import print_detail
from convaier.util.proc import run_command

log = logging.getLogger("convaier")

MAX_DIFF_LINES = 500
MAX_FILE_SIZE = 5_000


def _extract_file_diff(full_diff: str, filename: str) -> str:
    """Extract diff chunk for a specific file."""
    pattern = rf"(diff --git a/{re.escape(filename)} .*?)(?=diff --git a/|\Z)"
    match = re.search(pattern, full_diff, re.DOTALL)
    return match.group(1) if match else ""


def _truncate(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + f"\n... (truncated, {len(lines)} total)"


def _parse_lint_output(tool_name: str, stdout: str) -> list[LintIssue]:
    """Parse lint tool output in format: file:line:col: message."""
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


def _run_linters(tools: list[dict], project_root) -> list[LintIssue]:
    """Run configured lint tools and collect issues."""
    all_issues: list[LintIssue] = []
    for tool_cfg in tools:
        name = tool_cfg.get("name", "unknown")
        command = tool_cfg.get("command", "")
        if not command:
            continue

        print_detail(f"linting with {name}...")
        result = run_command(command, cwd=project_root)
        issues = _parse_lint_output(name, result.stdout)
        all_issues.extend(issues)

        if issues:
            print_detail(f"{name}: {len(issues)} issue(s)", "warn")
        else:
            print_detail(f"{name}: OK", "info")

    return all_issues


def _parse_review_response(response: str) -> list[ReviewComment]:
    from convaier.agent.parser import parse_model_response
    issues = parse_model_response(response, legacy_prefix="COMMENT")
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


def _review_single_file(
    filename: str,
    file_diff: str,
    file_content: str,
    focus: list[str],
    rag_context: str,
    security_summary: str,
    lint_issues: list[LintIssue],
    client,
    model: str,
    project_root,
    num_ctx: int = 4096,
    extra_rules: str = "",
) -> list[ReviewComment]:
    """Review a single file with AI."""
    prompt = build_review_prompt(
        diff=file_diff,
        file_contents={filename: file_content},
        lint_issues=lint_issues,
        focus=focus,
        rag_context=rag_context,
        security_summary=security_summary,
        extra_rules=extra_rules,
    )

    messages = [{"role": "user", "content": prompt}]
    response = agent_loop(
        client=client,
        model=model,
        messages=messages,
        tools=REVIEW_TOOLS,
        project_root=project_root,
        max_rounds=3,
        num_ctx=num_ctx,
    )
    return _parse_review_response(response)


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


@register("review")
class ReviewStage(Stage):
    def should_skip(self, ctx: PipelineContext) -> bool:
        return not ctx.git_diff and not ctx.changed_files

    def run(self, ctx: PipelineContext) -> StageResult:
        max_files = self.stage_config.get("max_files", 20)
        focus = self.stage_config.get("focus", [])
        use_rag = self.stage_config.get("use_rag", False)
        lint_tools = self.stage_config.get("lint_tools", [])
        max_workers = self.stage_config.get("max_workers", 1)
        extra_rules = "\n".join(filter(None, [
            ctx.config.rules.get("global", ""),
            ctx.config.rules.get("review", ""),
        ]))

        code_files = []
        for f in ctx.changed_files[:max_files]:
            fpath = ctx.project_root / f
            if fpath.is_file() and fpath.suffix in (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs"):
                code_files.append(f)

        if not code_files:
            return StageResult(success=True, summary="нет файлов для проверки")

        all_lint_issues: list[LintIssue] = []
        if lint_tools:
            all_lint_issues = _run_linters(lint_tools, ctx.project_root)
            ctx.lint_results = all_lint_issues

        security_summary_lines = [
            f"[{si.severity}] {si.tool}: {si.file}:{si.line} — {si.message}"
            for si in ctx.security_issues
        ] + [
            f"[{c.severity}] security-ai: {c.file}:{c.line} — {c.message}"
            for c in ctx.security_ai_comments
        ]
        security_summary = "\n".join(security_summary_lines)

        def _analyze_file(filename: str) -> list[ReviewComment]:
            client = create_client(ctx.config.ollama)
            fpath = ctx.project_root / filename

            content = fpath.read_text(errors="replace")
            if len(content) > MAX_FILE_SIZE:
                content = content[:MAX_FILE_SIZE] + "\n... (truncated)"

            file_diff = _extract_file_diff(ctx.git_diff, filename)
            if not file_diff:
                file_diff = "(new or modified file, no diff extracted)\n"
            file_diff = _truncate(file_diff, MAX_DIFF_LINES)

            file_sec_lines = [
                f"[{si.severity}] {si.tool}: {si.file}:{si.line} — {si.message}"
                for si in ctx.security_issues if si.file.endswith(filename)
            ] + [
                f"[{c.severity}] security-ai: {c.file}:{c.line} — {c.message}"
                for c in ctx.security_ai_comments if c.file.endswith(filename)
            ]
            file_security = "\n".join(file_sec_lines) if file_sec_lines else security_summary
            file_lint = [i for i in all_lint_issues if i.file.endswith(filename)]

            rag_context = ""
            if use_rag:
                try:
                    from convaier.rag.search import build_rag_context_for_file
                    rag_context = build_rag_context_for_file(
                        filename, content, ctx.project_root, ctx.config.ollama,
                    )
                except Exception:
                    pass

            print_detail(f"reviewing {filename}...")
            try:
                comments = _review_single_file(
                    filename, file_diff, content, focus, rag_context,
                    file_security, file_lint,
                    client, ctx.config.ollama.model, ctx.project_root,
                    num_ctx=ctx.config.ollama.num_ctx,
                    extra_rules=extra_rules,
                )
                if comments:
                    from convaier.ui import render_issue_line
                    for c in comments:
                        print_detail(render_issue_line(c.file, c.line or None, c.severity, c.message))
                else:
                    print_detail(f"{filename}: OK", "info")
                return comments
            except Exception as e:
                print_detail(f"{filename}: failed ({e})", "error")
                return []

        all_comments = asyncio.run(_run_parallel(_analyze_file, code_files, max_workers))

        # Дедупликация: модель иногда повторяет одинаковые блоки в ответе
        seen: set[str] = set()
        deduped: list[ReviewComment] = []
        for c in all_comments:
            key = f"{c.file}:{c.line}:{c.message[:80]}".lower()
            if key not in seen:
                seen.add(key)
                deduped.append(c)
        ctx.review_comments = deduped

        parts = []
        if all_lint_issues:
            parts.append(f"{len(all_lint_issues)} замечаний линтера")
        parts.append(f"{len(code_files)} файл(ов) проверено")
        if all_comments:
            parts.append(f"{len(all_comments)} замечан(ий)")

        return StageResult(success=True, summary=", ".join(parts))
