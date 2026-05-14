from __future__ import annotations

import logging

from convaier.context import PipelineContext
from convaier.stages import Stage, StageResult, register
from convaier.util.git import get_changed_files, get_diff

log = logging.getLogger("convaier")


@register("commit")
class CommitStage(Stage):
    def run(self, ctx: PipelineContext) -> StageResult:
        if ctx.full_scan:
            return self._run_full_scan(ctx)
        return self._run_diff(ctx)

    def _run_diff(self, ctx: PipelineContext) -> StageResult:
        target = self.stage_config.get("diff_target", "HEAD~1")

        diff_result = get_diff(ctx.project_root, target)
        if not diff_result.ok:
            return StageResult(success=False, summary=f"git diff failed: {diff_result.stderr}")

        ctx.git_diff = diff_result.stdout
        ctx.changed_files = get_changed_files(ctx.project_root, target)

        if not ctx.changed_files:
            return StageResult(success=True, summary="нет изменений")

        log.info("Изменённые файлы (%d): %s", len(ctx.changed_files), ", ".join(ctx.changed_files[:10]))
        return StageResult(
            success=True,
            summary=f"{len(ctx.changed_files)} файл(ов) изменено",
        )

    def _run_full_scan(self, ctx: PipelineContext) -> StageResult:
        try:
            from convaier.rag.chunker import CODE_EXTENSIONS, SKIP_DIRS
        except ImportError:
            # Если RAG не установлен — используем встроенные константы
            CODE_EXTENSIONS = {
                ".py", ".js", ".ts", ".tsx", ".jsx",
                ".java", ".go", ".rs", ".c", ".cpp", ".h",
                ".rb", ".php", ".swift", ".kt",
            }
            SKIP_DIRS = {
                ".git", ".convaier", "__pycache__", "node_modules",
                ".venv", "venv", ".tox", "dist", "build",
            }

        files: list[str] = []
        for path in ctx.project_root.rglob("*"):
            if not path.is_file():
                continue
            # Пропускаем директории из SKIP_DIRS
            parts = path.relative_to(ctx.project_root).parts
            if any(part in SKIP_DIRS for part in parts):
                continue
            if path.suffix in CODE_EXTENSIONS:
                files.append(str(path.relative_to(ctx.project_root)))

        ctx.git_diff = ""
        ctx.changed_files = files

        log.info("Полный скан: %d файл(ов)", len(files))
        return StageResult(
            success=True,
            summary=f"{len(files)} файл(ов) (полный скан)",
        )
