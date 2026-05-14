from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    model: str = "qwen2.5-coder:3b"
    timeout: int = 300
    num_ctx: int = 4096


@dataclass
class PipelineConfig:
    fail_fast: bool = True
    stages: list[str] = field(default_factory=lambda: [
        "commit", "lint", "security", "review", "tracker", "test", "build", "deploy",
    ])


@dataclass
class LintTool:
    command: str
    name: str


@dataclass
class YouGileConfig:
    enabled: bool = False
    base_url: str = "https://yougile.com/api-v2"
    token: str = ""
    column_id: str = ""
    min_severity: str = "warning"
    timeout: int = 30


@dataclass
class ReportsConfig:
    output_dir: str = ".convaier/reports"
    formats: list[str] = field(default_factory=lambda: ["markdown", "json"])


@dataclass
class Config:
    project_name: str = "project"
    language: str = ""
    project_root: Path = field(default_factory=Path.cwd)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    stages: dict = field(default_factory=dict)
    reports: ReportsConfig = field(default_factory=ReportsConfig)
    yougile: YouGileConfig = field(default_factory=YouGileConfig)
    rules: dict[str, str] = field(default_factory=dict)


_CONVENTION_RULE_FILES = {
    "global":   ".convaier/rules/global.md",
    "security": ".convaier/rules/security.md",
    "review":   ".convaier/rules/review.md",
}


def _resolve_rules_text(value: str, project_root: Path) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if "\n" not in stripped:
        candidate = project_root / stripped
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return stripped


def _load_rules(raw_rules: dict, stages_raw: dict, project_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, conv_path in _CONVENTION_RULE_FILES.items():
        parts: list[str] = []
        p = project_root / conv_path
        if p.is_file():
            parts.append(p.read_text(encoding="utf-8").strip())
        v = raw_rules.get(key)
        if v:
            parts.append(_resolve_rules_text(str(v), project_root))
        v2 = stages_raw.get(key, {}).get("rules")
        if v2:
            parts.append(_resolve_rules_text(str(v2), project_root))
        result[key] = "\n".join(filter(None, parts))
    return result


_OLLAMA_DEFAULTS = OllamaConfig()
_PIPELINE_DEFAULTS = PipelineConfig()
_REPORTS_DEFAULTS = ReportsConfig()
_YOUGILE_DEFAULTS = YouGileConfig()


def _parse_ollama(raw: dict) -> OllamaConfig:
    return OllamaConfig(
        host=raw.get("host", _OLLAMA_DEFAULTS.host),
        model=raw.get("model", _OLLAMA_DEFAULTS.model),
        timeout=raw.get("timeout", _OLLAMA_DEFAULTS.timeout),
        num_ctx=raw.get("num_ctx", _OLLAMA_DEFAULTS.num_ctx),
    )


def _parse_pipeline(raw: dict) -> PipelineConfig:
    return PipelineConfig(
        fail_fast=raw.get("fail_fast", True),
        stages=raw.get("stages", list(_PIPELINE_DEFAULTS.stages)),
    )


def _parse_reports(raw: dict) -> ReportsConfig:
    return ReportsConfig(
        output_dir=raw.get("output_dir", _REPORTS_DEFAULTS.output_dir),
        formats=raw.get("formats", list(_REPORTS_DEFAULTS.formats)),
    )


def _parse_yougile(raw: dict) -> YouGileConfig:
    return YouGileConfig(
        enabled=raw.get("enabled", _YOUGILE_DEFAULTS.enabled),
        base_url=raw.get("base_url", _YOUGILE_DEFAULTS.base_url),
        token=raw.get("token", _YOUGILE_DEFAULTS.token),
        column_id=raw.get("column_id", _YOUGILE_DEFAULTS.column_id),
        min_severity=raw.get("min_severity", _YOUGILE_DEFAULTS.min_severity),
        timeout=raw.get("timeout", _YOUGILE_DEFAULTS.timeout),
    )


def load_config(path: Path) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    project_root = path.parent.resolve()
    project = raw.get("project", {})
    language = project.get("language", "")

    stages_config = raw.get("stages", {})

    # Apply language preset (user config overrides preset defaults)
    if language:
        from convaier.presets import apply_preset
        stages_config = apply_preset(language, stages_config)

    rules = _load_rules(raw.get("rules", {}), stages_config, project_root)

    return Config(
        project_name=project.get("name", project_root.name),
        language=language,
        project_root=project_root,
        ollama=_parse_ollama(raw.get("ollama", {})),
        pipeline=_parse_pipeline(raw.get("pipeline", {})),
        stages=stages_config,
        reports=_parse_reports(raw.get("reports", {})),
        yougile=_parse_yougile(raw.get("yougile", {})),
        rules=rules,
    )


EXAMPLE_CONFIG = """\
project:
  name: my-app
  language: python          # preset: python, javascript, typescript, java, go

ollama:
  host: http://localhost:11434
  model: qwen2.5-coder:3b
  timeout: 300
  num_ctx: 4096              # context window (lower = faster)

pipeline:
  fail_fast: true
  stages:
    - commit
    - lint
    - security
    - review
    - tracker
    - test
    - build
    - deploy

stages:
  commit:
    diff_target: HEAD~1

  lint:
    tools:
      - command: ruff check .
        name: ruff

  security:
    tools:
      - command: python -m bandit -r . -f json --quiet
        name: bandit
      - command: python -m pip_audit --format=json
        name: pip-audit
    ai_review: true
    fail_on_critical: true

  review:
    focus:
      - security
      - performance
    max_files: 20
    max_diff_lines: 3000

  test:
    command: pytest --tb=short -q

  build:
    dockerfile: Dockerfile
    image_name: my-app
    tag: latest

  deploy:
    compose_file: docker-compose.yml
    service: app

reports:
  output_dir: .convaier/reports
  formats:
    - markdown
    - json

# Интеграция с YouGile (опционально)
# yougile:
#   enabled: false
#   base_url: https://yougile.com/api-v2
#   token: your-api-token
#   column_id: "uuid-колонки-куда-создавать-задачи"
#   min_severity: warning   # critical / warning / info / suggestion
#   timeout: 30

# Правила для AI-стадий (опционально, все аддитивны)
# Способ 1 — convention: создать файл .convaier/rules/security.md (подхватывается автоматически)
# Способ 2 — путь к файлу:
# rules:
#   global: .convaier/rules/global.md      # применяется ко всем AI-стадиям
#   security: .convaier/rules/security.md  # только для security
#   review: .convaier/rules/review.md      # только для review
# Способ 3 — inline текст:
# rules:
#   review: |
#     - Все публичные методы должны иметь docstring
#     - Запрещено использовать eval()
#     - Новые зависимости требуют обоснования в комментарии
"""


def generate_example_config(path: Path) -> None:
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    secret: str = ""
    workspace: Path = field(default_factory=lambda: Path("/var/lib/convaier/workspace"))
    git_token: str = ""
    log_level: str = "info"


def load_server_config(path: Path) -> ServerConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    srv = raw.get("server", raw)
    return ServerConfig(
        host=srv.get("host", "0.0.0.0"),
        port=int(srv.get("port", 8765)),
        secret=srv.get("secret", ""),
        workspace=Path(srv.get("workspace", "/var/lib/convaier/workspace")),
        git_token=srv.get("git_token", ""),
        log_level=srv.get("log_level", "info"),
    )


SERVER_EXAMPLE_CONFIG = """\
server:
  host: 0.0.0.0
  port: 8765
  secret: "replace-with-your-webhook-secret"
  workspace: /var/lib/convaier/workspace
  git_token: ""        # для приватных репо: github_pat_xxx или Gogs token
  log_level: info
"""
