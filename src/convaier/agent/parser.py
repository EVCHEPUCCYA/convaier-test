"""Парсинг структурированных ответов AI-модели в список Issue."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("convaier")


def _fix_mojibake(text: str) -> str:
    """Fix UTF-8 Cyrillic decoded as Windows-1251 (common with small Ollama models)."""
    try:
        fixed = text.encode("cp1251").decode("utf-8")
        def _score(s: str) -> int:
            return sum(1 for c in s if "А" <= c <= "я" or c.isascii())
        if _score(fixed) > _score(text):
            return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return text


@dataclass
class Issue:
    file: str
    line: int | None
    severity: str        # critical / warning / info / suggestion
    problem: str         # ПРОБЛЕМА
    reason: str = ""     # ПРИЧИНА
    fix: str = ""        # КАК ИСПРАВИТЬ


def parse_model_response(text: str, legacy_prefix: str = "") -> list[Issue]:
    """Парсит ответ модели в список Issue.

    Форматы (в порядке приоритета):
    1. Новый блочный формат: ФАЙЛ:/СТРОКА:/УРОВЕНЬ:/ПРОБЛЕМА:/ПРИЧИНА:/КАК ИСПРАВИТЬ:
       Блоки разделены пустой строкой.
    2. Старый pipe-формат: {legacy_prefix}|file|severity|message

    Никогда не бросает исключений.
    """
    if not text or not text.strip():
        return []

    try:
        blocks = _parse_blocks(text)
        if blocks:
            return blocks
    except Exception as e:
        log.debug("Block parser failed: %s", e)

    if legacy_prefix:
        try:
            return _parse_legacy(text, legacy_prefix)
        except Exception as e:
            log.debug("Legacy parser failed: %s", e)

    return []


def _parse_blocks(text: str) -> list[Issue]:
    """Парсит многострочные блоки вида КЛЮЧ: значение, разделённые пустой строкой."""
    issues: list[Issue] = []

    # Разбиваем на блоки по двум и более переводам строки
    raw_blocks = re.split(r"\n{2,}", text.strip())

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        kv: dict[str, str] = {}
        current_key: str | None = None
        current_lines: list[str] = []

        for line in block.splitlines():
            # Ищем строку вида "КЛЮЧ: значение"
            m = re.match(r"^([А-ЯA-Z\s]+):\s*(.*)", line)
            if m:
                # Сохраняем предыдущий ключ
                if current_key is not None:
                    kv[current_key] = " ".join(current_lines).strip()
                current_key = m.group(1).strip()
                current_lines = [m.group(2).strip()] if m.group(2).strip() else []
            elif current_key is not None:
                # Продолжение многострочного значения
                current_lines.append(line.strip())

        if current_key is not None:
            kv[current_key] = " ".join(current_lines).strip()

        # Проверяем обязательные поля
        file_val = kv.get("ФАЙЛ", "").strip()
        level_val = kv.get("УРОВЕНЬ", "").strip().lower()
        problem_val = kv.get("ПРОБЛЕМА", "").strip()

        if not file_val or not level_val or not problem_val:
            continue

        # Номер строки
        line_raw = kv.get("СТРОКА", "").strip()
        try:
            line_num: int | None = int(line_raw) if line_raw and line_raw != "н/д" else None
        except ValueError:
            line_num = None

        issues.append(Issue(
            file=file_val,
            line=line_num,
            severity=level_val,
            problem=_fix_mojibake(problem_val),
            reason=_fix_mojibake(kv.get("ПРИЧИНА", "").strip()),
            fix=_fix_mojibake(kv.get("КАК ИСПРАВИТЬ", "").strip()),
        ))

    return issues


def _parse_legacy(text: str, prefix: str) -> list[Issue]:
    """Парсит строки вида PREFIX|file|severity|message."""
    issues: list[Issue] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(f"{prefix}|"):
            continue
        parts = line.split("|", 3)
        if len(parts) >= 4:
            try:
                issues.append(Issue(
                    file=parts[1].strip(),
                    line=None,
                    severity=parts[2].strip().lower(),
                    problem=_fix_mojibake(parts[3].strip()),
                ))
            except Exception:
                continue
    return issues
