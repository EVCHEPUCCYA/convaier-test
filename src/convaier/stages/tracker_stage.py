"""Этап конвейера: создание задач в YouGile по найденным проблемам."""
from __future__ import annotations

import logging

from convaier.context import LintIssue, PipelineContext, ReviewComment, SecurityIssue
from convaier.messages import (
    ISSUE_LABEL_FIX,
    ISSUE_LABEL_PROBLEM,
    ISSUE_LABEL_REASON,
    TRACKER_CREATED,
    TRACKER_DISABLED,
    TRACKER_NO_ISSUES,
)
from convaier.stages import Stage, StageResult, register

log = logging.getLogger("convaier")

_SEV_ORDER: dict[str, int] = {
    "critical":   4,
    "high":       3,
    "warning":    2,
    "info":       1,
    "suggestion": 0,
}


@register("tracker")
class TrackerStage(Stage):
    def run(self, ctx: PipelineContext) -> StageResult:
        yg_cfg = ctx.config.yougile

        if not yg_cfg.enabled:
            return StageResult(success=True, summary=TRACKER_DISABLED)

        created: list[dict] = []
        skipped_dedup: int = 0
        errors: list[str] = []

        try:
            from convaier.util.yougile import YouGileClient
            client = YouGileClient(
                base_url=yg_cfg.base_url,
                token=yg_cfg.token,
                column_id=yg_cfg.column_id,
                timeout=yg_cfg.timeout,
            )
        except Exception as e:
            ctx.tracker_results = {"created": [], "skipped_dedup": 0, "errors": [str(e)]}
            return StageResult(success=True, summary=f"YouGile: ошибка инициализации — {e}")

        min_sev = _SEV_ORDER.get(yg_cfg.min_severity.lower(), 2)
        candidates = _collect_candidates(ctx, min_sev)

        if not candidates:
            ctx.tracker_results = {"created": [], "skipped_dedup": 0, "errors": []}
            return StageResult(success=True, summary=TRACKER_NO_ISSUES)

        for title, description, severity in candidates:
            try:
                existing = client.find_tasks_by_title(title)
                if existing:
                    skipped_dedup += 1
                    log.info("  YouGile: пропущен дубль: %s", title[:60])
                    continue

                task = client.create_task(title, description)
                task_id = task.get("id", "?")
                created.append({"id": task_id, "title": title})
                log.info("  YouGile: создана задача %s", task_id)

            except Exception as e:
                errors.append(f"{title[:50]}: {e}")
                log.warning("  YouGile ошибка: %s", e)

        ctx.tracker_results = {
            "created": created,
            "skipped_dedup": skipped_dedup,
            "errors": errors,
        }

        n = len(created)
        summary_msg = TRACKER_CREATED.format(n=n) if n else TRACKER_NO_ISSUES
        if skipped_dedup:
            summary_msg += f", {skipped_dedup} дублей пропущено"
        if errors:
            summary_msg += f", {len(errors)} ошибок"

        return StageResult(success=True, summary=summary_msg)


def _clean_title_msg(msg: str) -> str:
    """Убирает версионный диапазон ('pkg@<1.2: text') и URL ('→ https://...') из заголовка."""
    # Strip "pkg@<version: " prefix
    if ": " in msg:
        after = msg.split(": ", 1)[1]
        if len(after) > 10:
            msg = after
    # Strip " → https://..." suffix
    for sep in (" → http", " -> http"):
        idx = msg.find(sep)
        if idx != -1:
            msg = msg[:idx]
    return msg.strip()


def _collect_candidates(
    ctx: PipelineContext,
    min_sev: int,
) -> list[tuple[str, str, str]]:
    """Собрать (title, description, severity) из всех источников проблем."""
    seen: set[str] = set()
    results: list[tuple[str, str, str]] = []

    def _add(title: str, description: str, severity: str) -> None:
        if _SEV_ORDER.get(severity.lower(), 0) < min_sev:
            return
        key = title.strip().lower()[:120]
        if key in seen:
            return
        seen.add(key)
        results.append((title, description, severity))

    # Lint
    for issue in ctx.lint_results:
        loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
        title = f"[lint/{issue.tool}] {loc} — {issue.message[:80]}"[:120]
        description = _build_lint_issue_desc(issue, loc)
        _add(title, description, issue.severity)

    # Статические инструменты: security_issues
    for issue in ctx.security_issues:
        loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
        short_msg = _clean_title_msg(issue.message)[:80]
        title = f"[{issue.tool}] {short_msg}"[:120]
        description = _build_tool_issue_desc(issue, loc)
        _add(title, description, issue.severity)

    # AI-анализ безопасности
    for comment in ctx.security_ai_comments:
        loc = f"{comment.file}:{comment.line}" if comment.line else comment.file
        title = f"[security] {loc} — {comment.message[:80]}"[:120]
        description = _build_review_comment_desc(comment, loc, "security")
        _add(title, description, comment.severity)

    # AI-ревью кода
    for comment in ctx.review_comments:
        loc = f"{comment.file}:{comment.line}" if comment.line else comment.file
        title = f"[review] {loc} — {comment.message[:80]}"[:120]
        description = _build_review_comment_desc(comment, loc, "review")
        _add(title, description, comment.severity)

    return results


def _build_lint_issue_desc(issue: LintIssue, loc: str) -> str:
    parts = [issue.message]
    parts.append(f"[{loc}]  Уровень: {issue.severity}  |  Инструмент: {issue.tool}")
    return "\n\n".join(parts)


def _build_tool_issue_desc(issue: SecurityIssue, loc: str) -> str:
    parts = [issue.message]
    if issue.cwe:
        cwe_num = issue.cwe.removeprefix("CWE-")
        parts.append(f"[Стандарт] CWE-{cwe_num}")
    parts.append(f"[{loc}]  Уровень: {issue.severity}  |  Инструмент: {issue.tool}")
    return "\n\n".join(parts)


def _build_review_comment_desc(comment: ReviewComment, loc: str, source: str) -> str:
    parts = [comment.message]
    if comment.reason:
        parts.append(f"[{ISSUE_LABEL_REASON}] {comment.reason}")
    if comment.fix:
        parts.append(f"[{ISSUE_LABEL_FIX}] {comment.fix}")
    parts.append(f"[{loc}]  Уровень: {comment.severity}  |  Этап: {source}")
    return "\n\n".join(parts)
