from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from convaier.context import PipelineContext

log = logging.getLogger("convaier")


def _render_markdown(ctx: PipelineContext) -> str:
    lines = [
        "# Отчёт convaier",
        f"**Проект**: {ctx.config.project_name} | "
        f"**Дата**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"**Результат**: {'УСПЕШНО' if not ctx.errors else 'ОШИБКА'}",
        "",
    ]

    # Timings
    if ctx.timings:
        lines.append("## Время выполнения")
        for stage, t in ctx.timings.items():
            lines.append(f"- **{stage}**: {t:.1f}s")
        lines.append("")

    # Commit
    if ctx.changed_files:
        mode = " (полный скан)" if ctx.full_scan else ""
        lines.append("## Изменения")
        lines.append(f"- Файлов{mode}: {len(ctx.changed_files)}")
        for f in ctx.changed_files[:20]:
            lines.append(f"  - `{f}`")
        lines.append("")

    # Lint
    if ctx.lint_results:
        lines.append("## Линтер")
        lines.append("| Инструмент | Файл | Строка | Сообщение |")
        lines.append("|------|------|------|---------|")
        for issue in ctx.lint_results[:50]:
            lines.append(f"| {issue.tool} | `{issue.file}` | {issue.line} | {issue.message} |")
        lines.append("")

    # Security
    if ctx.security_issues or ctx.security_ai_comments:
        lines.append("## Безопасность")
        if ctx.security_issues:
            lines.append("### Инструменты")
            lines.append("| Инструмент | Файл | Строка | Уровень | CWE | Сообщение |")
            lines.append("|------|------|------|----------|-----|---------|")
            for issue in ctx.security_issues[:50]:
                cwe_raw = issue.cwe or ""
                cwe = f"CWE-{cwe_raw.removeprefix('CWE-')}" if cwe_raw else "-"
                lines.append(f"| {issue.tool} | `{issue.file}` | {issue.line} | {issue.severity} | {cwe} | {issue.message} |")
            lines.append("")
        if ctx.security_ai_comments:
            lines.append("### AI-анализ")
            for c in ctx.security_ai_comments:
                loc = f"`{c.file}:{c.line}`" if c.line else f"`{c.file}`"
                lines.append(f"#### {loc} [{c.severity}]")
                lines.append(f"> {c.message}")
                if c.reason:
                    lines.append(f"> **Причина:** {c.reason}")
                if c.fix:
                    lines.append(f"> **Как исправить:** {c.fix}")
                lines.append("")
        lines.append("")

    # Review
    if ctx.review_comments:
        lines.append("## Ревью кода (AI)")
        for c in ctx.review_comments:
            loc = f"`{c.file}:{c.line}`" if c.line else f"`{c.file}`"
            lines.append(f"### {loc} [{c.severity}]")
            lines.append(f"> {c.message}")
            if c.reason:
                lines.append(f"> **Причина:** {c.reason}")
            if c.fix:
                lines.append(f"> **Как исправить:** {c.fix}")
            lines.append("")

    # Metrics (legacy — сохраняем для обратной совместимости)
    if ctx.metrics_result:
        mr = ctx.metrics_result
        lines.append("## Метрики кода")
        lines.append(f"- **Средняя сложность**: {mr.avg_complexity}")
        lines.append(f"- **Средний индекс сопровождаемости**: {mr.avg_maintainability}")
        lines.append(f"- **Всего строк кода**: {mr.total_loc}")
        if mr.coverage is not None:
            lines.append(f"- **Покрытие тестами**: {mr.coverage}%")
        lines.append("")
        if mr.files:
            lines.append("| Файл | Сложность | Сопровождаемость | LOC |")
            lines.append("|------|-----------|-----------------|-----|")
            for fm in mr.files:
                lines.append(f"| `{fm.file}` | {fm.complexity} | {fm.maintainability} | {fm.loc} |")
            lines.append("")
        if mr.ai_recommendations:
            lines.append("### Рекомендации AI")
            for r in mr.ai_recommendations:
                lines.append(f"- {r}")
            lines.append("")

    # Tracker (YouGile)
    if ctx.tracker_results is not None:
        yr = ctx.tracker_results
        lines.append("## YouGile")
        created = yr.get("created", [])
        if created:
            lines.append(f"- Создано задач: {len(created)}")
            for task in created[:20]:
                lines.append(f"  - [{task.get('id', '?')}] {task.get('title', '')}")
        skipped = yr.get("skipped_dedup", 0)
        if skipped:
            lines.append(f"- Пропущено (дубли): {skipped}")
        errs = yr.get("errors", [])
        if errs:
            lines.append(f"- Ошибок: {len(errs)}")
            for e in errs[:5]:
                lines.append(f"  - {e}")
        if not created and not skipped and not errs:
            lines.append("- Нет новых задач")
        lines.append("")

    # Tests
    if ctx.test_results:
        tr = ctx.test_results
        lines.append("## Тесты")
        lines.append(f"- {tr.passed} прошло, {tr.failed} упало, {tr.skipped} пропущено")
        if tr.duration:
            lines.append(f"- Время: {tr.duration:.1f}s")
        if tr.ai_analysis:
            lines.append("")
            lines.append("### AI-анализ падений")
            for entry in tr.ai_analysis.strip().split("\n"):
                if entry.startswith("АНАЛИЗ|"):
                    parts = entry.split("|", 3)
                    if len(parts) == 4:
                        _, test_name, reason, fix = parts
                        lines.append(f"**{test_name.strip()}**")
                        lines.append(f"> Причина: {reason.strip()}")
                        lines.append(f"> Как исправить: {fix.strip()}")
                        lines.append("")
        lines.append("")

    # Build
    if ctx.build_result:
        br = ctx.build_result
        status = "OK" if br.success else "ОШИБКА"
        lines.append("## Сборка")
        lines.append(f"- Образ: `{br.image}:{br.tag}` — {status} ({br.duration:.1f}s)")
        lines.append("")

    # Deploy
    if ctx.deploy_result:
        dr = ctx.deploy_result
        status = "OK" if dr.success else "ОШИБКА"
        lines.append("## Деплой")
        lines.append(f"- Сервис `{dr.service}` — {status}")
        lines.append("")

    # Errors
    if ctx.errors:
        lines.append("## Ошибки")
        for err in ctx.errors:
            lines.append(f"- **{err.stage}**: {err.error}")
        lines.append("")

    lines.append("---")
    lines.append("*Создано автоматически утилитой convaier*")
    return "\n".join(lines)


def _safe_asdict(ctx: PipelineContext) -> dict:
    d = asdict(ctx)
    # Convert Path objects to strings
    d["project_root"] = str(ctx.project_root)
    return d


def generate_reports(ctx: PipelineContext) -> list[Path]:
    output_dir = Path(ctx.config.reports.output_dir)
    if not output_dir.is_absolute():
        output_dir = ctx.project_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    paths: list[Path] = []
    formats = ctx.config.reports.formats

    if "json" in formats:
        p = output_dir / f"run-{ts}.json"
        data = _safe_asdict(ctx)
        p.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        paths.append(p)

    if "markdown" in formats:
        p = output_dir / f"run-{ts}.md"
        p.write_text(_render_markdown(ctx), encoding="utf-8")
        paths.append(p)

    return paths
