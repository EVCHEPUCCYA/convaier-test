from __future__ import annotations

import logging
import re
import time

from convaier.context import PipelineContext, TestResults
from convaier.stages import Stage, StageResult, register
from convaier.util.proc import run_command

log = logging.getLogger("convaier")

# pytest: "5 passed, 2 failed, 1 skipped"
_PYTEST_RE = re.compile(r"(\d+)\s+passed|(\d+)\s+failed|(\d+)\s+skipped")
# Jest: "Tests: 2 failed, 1 passed, 3 total"
_JEST_RE = re.compile(r"Tests:\s+(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+passed,\s*)?(?:(\d+)\s+skipped,\s*)?(\d+)\s+total")


def _parse_test_output(output: str) -> TestResults:
    results = TestResults(output=output)

    jest_match = _JEST_RE.search(output)
    if jest_match:
        results.failed = int(jest_match.group(1) or 0)
        results.passed = int(jest_match.group(2) or 0)
        results.skipped = int(jest_match.group(3) or 0)
        return results

    for match in _PYTEST_RE.finditer(output):
        if match.group(1):
            results.passed = int(match.group(1))
        if match.group(2):
            results.failed = int(match.group(2))
        if match.group(3):
            results.skipped = int(match.group(3))
    return results


@register("test")
class TestStage(Stage):
    def run(self, ctx: PipelineContext) -> StageResult:
        commands_cfg = self.stage_config.get("commands")
        if commands_cfg:
            commands = [(c["name"], c["command"]) for c in commands_cfg if c.get("command")]
        else:
            commands = [("test", self.stage_config.get("command", "pytest --tb=short -q"))]

        ai_analysis = self.stage_config.get("ai_analysis", False)

        all_output: list[str] = []
        total_passed = total_failed = total_skipped = 0
        t0 = time.monotonic()

        for suite_name, cmd in commands:
            log.info("  Running [%s]: %s", suite_name, cmd)
            result = run_command(cmd, cwd=ctx.project_root, timeout=600)
            output = result.stdout + result.stderr
            tr = _parse_test_output(output)
            total_passed += tr.passed
            total_failed += tr.failed
            total_skipped += tr.skipped
            all_output.append(f"[{suite_name}]\n{output}")
            if not result.ok and total_failed > 0:
                break

        duration = time.monotonic() - t0
        combined_output = "\n".join(all_output)

        test_results = TestResults(
            passed=total_passed,
            failed=total_failed,
            skipped=total_skipped,
            duration=duration,
            output=combined_output,
        )
        ctx.test_results = test_results

        if total_failed > 0 and ai_analysis:
            try:
                from convaier.agent.client import agent_loop, create_client
                from convaier.agent.prompt import build_test_analysis_prompt
                from convaier.ui import print_detail

                print_detail("AI analysing test failures...")
                client = create_client(ctx.config.ollama)
                prompt = build_test_analysis_prompt(combined_output[:4000], ctx.git_diff or "")
                messages = [{"role": "user", "content": prompt}]
                analysis = agent_loop(
                    client=client,
                    model=ctx.config.ollama.model,
                    messages=messages,
                    tools=[],
                    project_root=ctx.project_root,
                    max_rounds=1,
                    num_ctx=ctx.config.ollama.num_ctx,
                )
                ctx.test_results.ai_analysis = analysis
                print_detail(f"AI: {analysis[:300]}")
            except Exception as e:
                log.warning("  AI test analysis failed: %s", e)

        summary = f"{total_passed} passed, {total_failed} failed, {total_skipped} skipped ({duration:.1f}s)"
        success = total_failed == 0
        return StageResult(success=success, summary=summary)
