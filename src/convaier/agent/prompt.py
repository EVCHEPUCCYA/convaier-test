from __future__ import annotations

from convaier.context import LintIssue

_BLOCK_FORMAT_EXAMPLE = """\
ФАЙЛ: src/auth.py
СТРОКА: 42
УРОВЕНЬ: critical
ПРОБЛЕМА: API-ключ задан непосредственно в коде в виде строковой константы.
ПРИЧИНА: Секреты попадают в систему контроля версий и доступны всем, у кого есть доступ к репозиторию. При утечке репозитория злоумышленник получает прямой доступ к внешнему сервису.
КАК ИСПРАВИТЬ: Перенести ключ в переменную окружения. Читать через os.environ.get(). В репозитории хранить только .env.example с пустым значением. Добавить .env в .gitignore."""

_BLOCK_FORMAT_RULES = """\
Для каждой найденной проблемы используй строго следующий формат (пустая строка между блоками):

ФАЙЛ: <путь к файлу>
СТРОКА: <номер строки или н/д>
УРОВЕНЬ: <critical | warning | info | suggestion>
ПРОБЛЕМА: <одно предложение — суть проблемы>
ПРИЧИНА: <почему это опасно или плохо — 2–4 предложения>
КАК ИСПРАВИТЬ: <конкретные шаги исправления — 2–5 предложений, без кода>

Пример:

""" + _BLOCK_FORMAT_EXAMPLE + """

Если проблем нет — выведи: НЕТ_ПРОБЛЕМ
Отвечай строго на русском языке. Не дублируй проблемы, уже указанные ниже.
Не предлагай готовый код — только текстовое описание шагов."""


def build_review_prompt(
    diff: str,
    file_contents: dict[str, str],
    lint_issues: list[LintIssue],
    focus: list[str] | None = None,
    rag_context: str = "",
    security_summary: str = "",
    extra_rules: str = "",
) -> str:
    parts = [
        "Ты — ревьюер кода. Твоя задача — только качество кода.",
        "НЕ ищи уязвимости безопасности — это задача отдельного этапа security.",
        "",
        _BLOCK_FORMAT_RULES,
        "",
        "Фокус: антипаттерны, архитектура, читаемость, поддерживаемость, потенциальные баги (не связанные с безопасностью).",
        "",
    ]

    if extra_rules:
        parts.append("== Дополнительные правила ревью ==")
        parts.append(extra_rules)
        parts.append("")

    if focus:
        parts.append(f"Дополнительный фокус: {', '.join(focus)}")
        parts.append("")

    if security_summary:
        parts.append("== Проблемы безопасности (найдены этапом security — это НЕ твоя зона, не повторяй) ==")
        parts.append(security_summary)
        parts.append("")

    if lint_issues:
        parts.append("== Замечания линтера (НЕ повторять) ==")
        for issue in lint_issues[:20]:
            parts.append(f"  {issue.tool}: {issue.file}:{issue.line} — {issue.message}")
        parts.append("")

    parts.append("== Git Diff ==")
    parts.append(diff)
    parts.append("")

    if file_contents:
        parts.append("== Содержимое изменённых файлов ==")
        for path, content in file_contents.items():
            parts.append(f"--- {path} ---")
            parts.append(content)
            parts.append("")

    if rag_context:
        parts.append(rag_context)
        parts.append("")

    return "\n".join(parts)


_SECURITY_CHECKLIST = """\
Проверь код на уязвимости. Правила без исключений:
- password/secret/key/token = строковый литерал → CRITICAL
- SQL-запрос содержит '+' или ${переменная} → CRITICAL
- innerHTML/dangerouslySetInnerHTML с пользовательскими данными → CRITICAL
- eval() / exec() с пользовательскими данными → CRITICAL
- os.system() / subprocess с интерполяцией переменных → CRITICAL
- JWT без проверки подписи или алгоритм none → CRITICAL
- console.log выводит пароль/токен/ключ → warning
- Access-Control-Allow-Origin: * в prod-конфиге → warning
- debug=True / DEBUG=True в prod-конфиге → warning
НЕТ_ПРОБЛЕМ только если ни одного из паттернов выше не найдено.\
"""


def build_security_prompt(
    tool_results: str,
    diff: str,
    file_contents: dict[str, str],
    rag_context: str = "",
    extra_rules: str = "",
) -> str:
    parts = [
        "Ты — аудитор безопасности. Ищи только уязвимости и проблемы безопасности.",
        "НЕ оценивай качество кода, архитектуру, читаемость — это задача этапа review.",
        "",
        _SECURITY_CHECKLIST,
        "",
    ]

    if extra_rules:
        parts.append("== Дополнительные правила безопасности ==")
        parts.append(extra_rules)
        parts.append("")

    parts += [
        _BLOCK_FORMAT_RULES,
        "",
    ]

    if tool_results:
        parts.append("== Уязвимости, уже найденные инструментами (НЕ повторять) ==")
        parts.append(tool_results)
        parts.append("")

    parts.append("== Git Diff ==")
    parts.append(diff)
    parts.append("")

    if file_contents:
        parts.append("== Содержимое файла ==")
        for path, content in file_contents.items():
            parts.append(f"--- {path} ---")
            parts.append(content)
            parts.append("")

    if rag_context:
        parts.append(rag_context)
        parts.append("")

    return "\n".join(parts)


def build_metrics_prompt(
    metrics_summary: str,
    avg_complexity: float,
    avg_maintainability: float,
    total_loc: int,
    coverage: float | None,
) -> str:
    parts = [
        "Ты — аналитик качества кода. Проанализируй метрики и дай рекомендации по рефакторингу.",
        "",
        "Для каждой рекомендации выведи одну строку в формате:",
        "РЕКОМЕНДАЦИЯ: <конкретная рекомендация с указанием файла>",
        "",
        "Фокус: функции с высокой цикломатической сложностью, файлы с низким индексом сопровождаемости.",
        "Выведи 3–5 рекомендаций максимум. Если всё хорошо — выведи: НЕТ_ПРОБЛЕМ",
        "",
        "Справка по метрикам:",
        "- Цикломатическая сложность: 1–5 = просто, 6–10 = умеренно, 11+ = сложно (нужен рефакторинг)",
        "- Индекс сопровождаемости: 0–9 = низкий, 10–19 = умеренный, 20+ = хороший",
        "",
        "== Сводка ==",
        f"Средняя сложность: {avg_complexity}",
        f"Средний индекс сопровождаемости: {avg_maintainability}",
        f"Всего строк кода: {total_loc}",
    ]

    if coverage is not None:
        parts.append(f"Покрытие тестами: {coverage}%")

    parts.extend([
        "",
        "== Метрики по файлам ==",
        metrics_summary,
    ])

    return "\n".join(parts)


def build_test_analysis_prompt(test_output: str, diff: str) -> str:
    return "\n".join([
        "Ты — аналитик тестов. Ниже результаты упавших тестов.",
        "Проанализируй вывод тестов и последние изменения кода, объясни вероятную причину.",
        "Отвечай на русском языке. Формат ответа:",
        "АНАЛИЗ|название_теста|вероятная_причина|предлагаемое_исправление",
        "",
        "== Вывод тестов ==",
        test_output,
        "",
        "== Последние изменения ==",
        diff,
    ])
