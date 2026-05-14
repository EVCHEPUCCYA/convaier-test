"""Все строки пользовательского интерфейса на русском языке."""
from __future__ import annotations

# Статусы этапов
STAGE_SKIPPED = "пропущен"
STAGE_DRY = "dry-run"
PIPELINE_FAIL_FAST = "Fail-fast: конвейер остановлен"

# Pipeline
PIPELINE_PASSED = "УСПЕШНО"
PIPELINE_FAILED = "ОШИБКА"
PIPELINE_ERRORS = "ошибок"

# Full-scan
FULL_SCAN_LABEL = "полный скан"
FULL_SCAN_NO_CHANGES = "нет изменений"

# Commit
COMMIT_CHANGED = "{n} файл(ов) изменено"
COMMIT_NO_CHANGES = "нет изменений"
COMMIT_FULL_SCAN = "{n} файл(ов) (полный скан)"

# Security
SECURITY_NO_ISSUES = "нет проблем безопасности"
SECURITY_ISSUES_FOUND = "{n} проблем(ы) найдено"

# Review
REVIEW_NO_ISSUES = "нет замечаний"
REVIEW_ISSUES_FOUND = "{n} файл(ов), {c} замечан(ий)"

# Tracker (YouGile)
TRACKER_DISABLED = "пропущен (yougile.enabled: false)"
TRACKER_NO_ISSUES = "нет проблем для создания задач"
TRACKER_CREATED = "{n} задач(и) создано"

# Иконки и стили по severity
SEV_ICONS: dict[str, str] = {
    "critical":   "✗",
    "high":       "✗",
    "warning":    "⚠",
    "info":       "ℹ",
    "suggestion": "→",
}
SEV_STYLES: dict[str, str] = {
    "critical":   "bold red",
    "high":       "red",
    "warning":    "yellow",
    "info":       "cyan",
    "suggestion": "dim",
}

ISSUE_LABEL_PROBLEM = "Проблема"
ISSUE_LABEL_REASON  = "Причина"
ISSUE_LABEL_FIX     = "Как исправить"

# CLI
CLI_CONFIG_NOT_FOUND = "Конфиг не найден: {path}"
CLI_CONFIG_HINT = "Запустите 'convaier init' для создания конфига."
CLI_FILE_EXISTS = "Файл уже существует: {path}"
CLI_FILE_EXISTS_HINT = "(используйте --force для перезаписи)"
CLI_CREATED = "Создан {path}"
CLI_INDEXED = "Готово: {n} чанков проиндексировано"
CLI_ALL_OK = "Все проверки пройдены"
CLI_RAG_MISSING = "RAG требует chromadb. Установите: pip install convaier[rag]"
CLI_INDEXING = "Индексирование..."
CLI_HOOK_NO_DIR = "Директория hooks не найдена: {path}"
CLI_HOOK_EXISTS = "Хук уже существует: {path}"
CLI_HOOK_EXISTS_HINT = "(используйте --force для перезаписи)"
CLI_HOOK_INSTALLED = "Хук установлен: {path}"
CLI_HOOK_STATUS_OK = "установлен"
CLI_HOOK_STATUS_MODIFIED = "установлен (изменён)"
CLI_HOOK_STATUS_MISSING = "не установлен"
CLI_HOOK_NO_COMMAND = "Укажите подкоманду: install | status"
