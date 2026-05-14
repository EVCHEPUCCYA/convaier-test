"""Fast regex-based security pre-scanner. No external tools required."""
from __future__ import annotations

import re
from pathlib import Path

from convaier.context import SecurityIssue

# (pattern, severity, message)
# Порядок важен: более специфичные паттерны — раньше
_PATTERNS: list[tuple[str, str, str]] = [
    # --- Hardcoded secrets ---
    (
        r'(?:password|passwd|secret|api_?key|apikey|token|jwt_?secret|'
        r'db_?pass(?:word)?|auth_?token|private_?key|access_?key)\s*(?:=|:)\s*'
        r'["\'][^"\']{4,}["\']',
        "critical",
        "Захардкоженный секрет",
    ),
    # --- SQL injection: конкатенация строк ---
    (
        r'(?:query|execute|db\.(?:query|run|exec|all|get))\s*\(["\']'
        r'(?:SELECT|INSERT|UPDATE|DELETE|DROP)[^"\']*["\'\s]*\+',
        "critical",
        "SQL-инъекция: конкатенация строк в запросе",
    ),
    # --- SQL injection: template literal с переменной ---
    (
        r'(?:query|execute|db\.(?:query|run|exec|all|get))\s*\(`'
        r'(?:SELECT|INSERT|UPDATE|DELETE|DROP)[^`]*\$\{',
        "critical",
        "SQL-инъекция: интерполяция переменной в SQL-запросе",
    ),
    # --- XSS: innerHTML с присваиванием ---
    (
        r'\.innerHTML\s*\+?=\s*(?!["\'](?:\s*["\'])?(?:\s*;)?$)',
        "critical",
        "XSS через innerHTML",
    ),
    # --- XSS: dangerouslySetInnerHTML с переменной ---
    (
        r'dangerouslySetInnerHTML\s*=\s*\{\s*\{\s*__html\s*:\s*(?!["\'])',
        "critical",
        "XSS через dangerouslySetInnerHTML с динамическими данными",
    ),
    # --- Логирование секретов ---
    (
        r'(?:console\.log|console\.error|console\.warn|print|logger\.\w+)'
        r'\s*\([^)]*(?:password|passwd|secret|token|api_?key|jwt)',
        "warning",
        "Логирование чувствительных данных",
    ),
    # --- eval() с переменной ---
    (
        r'\beval\s*\(\s*(?!["\'])',
        "warning",
        "Использование eval() с нестроковым аргументом",
    ),
    # --- Открытый debug-эндпоинт ---
    (
        r'(?:app|router)\.(?:get|post|all)\s*\(\s*["\']/?debug["\']',
        "warning",
        "Открытый debug-эндпоинт",
    ),
]

_COMPILED = [
    (re.compile(pat, re.IGNORECASE), sev, msg)
    for pat, sev, msg in _PATTERNS
]

_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rs", ".php", ".rb",
}


def scan_file(filepath: Path, project_root: Path) -> list[SecurityIssue]:
    if filepath.suffix.lower() not in _CODE_EXTENSIONS:
        return []

    try:
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    rel_path = str(filepath.relative_to(project_root))
    issues: list[SecurityIssue] = []
    seen: set[tuple[str, int, str]] = set()

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#", "*", "/*")):
            continue

        for regex, severity, message in _COMPILED:
            if regex.search(line):
                key = (rel_path, lineno, message)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(SecurityIssue(
                    tool="regex-scanner",
                    file=rel_path,
                    line=lineno,
                    severity=severity,
                    message=message,
                    cwe="",
                ))

    return issues


def scan_files(filepaths: list[str], project_root: Path) -> list[SecurityIssue]:
    """Сканирует список файлов, возвращает все найденные проблемы."""
    issues: list[SecurityIssue] = []
    for filename in filepaths:
        fpath = project_root / filename
        if fpath.is_file():
            issues.extend(scan_file(fpath, project_root))
    return issues
