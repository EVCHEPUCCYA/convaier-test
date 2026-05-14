import argparse
import logging
import sys
from pathlib import Path

from convaier.ui import console, print_check_fail, print_check_ok, print_presets_table


def _setup_logging(verbose: bool = False) -> None:
    if verbose:
        level = logging.DEBUG
    else:
        level = logging.ERROR
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )


def _cmd_run(args: argparse.Namespace) -> int:
    from convaier.config import load_config
    from convaier.pipeline import run_pipeline

    config_path = Path(args.config)
    if not config_path.exists():
        console.print(f"[error]Конфиг не найден: {config_path}[/]")
        console.print("[dim]Запустите 'convaier init' для создания конфига.[/]")
        return 1

    config = load_config(config_path)
    stages = args.stage.split(",") if args.stage else None
    ctx = run_pipeline(
        config,
        stage_filter=stages,
        dry_run=args.dry_run,
        full_scan=args.full_scan,
        env=args.env,
    )
    return 1 if ctx.errors else 0


def _cmd_init(args: argparse.Namespace) -> int:
    from convaier.config import generate_example_config

    target = Path(args.output)
    if target.exists() and not args.force:
        console.print(f"[error]Файл уже существует: {target}[/] [dim](используйте --force для перезаписи)[/]")
        return 1
    generate_example_config(target)
    console.print(f"[success]Создан {target}[/]")
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    from convaier.config import load_config

    config_path = Path(args.config)
    if not config_path.exists():
        console.print(f"[error]Конфиг не найден: {config_path}[/]")
        return 1

    config = load_config(config_path)

    try:
        from convaier.rag.indexer import index_project
    except ImportError:
        console.print("[error]RAG требует chromadb.[/] Установите: [bold]pip install convaier\\[rag][/]")
        return 1

    console.print(f"[dim]Индексирование проекта: {config.project_root}[/]")

    from rich.progress import Progress
    with Progress(console=console) as progress:
        task = progress.add_task("Индексирование...", total=None)
        total = index_project(config.project_root, config.ollama, force=args.force)
        progress.update(task, completed=total, total=total)

    console.print(f"[success]Готово: {total} чанков проиндексировано[/]")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    from convaier.config import load_config

    config_path = Path(args.config)
    if not config_path.exists():
        console.print(f"[error]Конфиг не найден: {config_path}[/]")
        return 1

    config = load_config(config_path)
    print_check_ok("Конфиг", str(config_path))

    if config.language:
        print_check_ok("Язык", f"{config.language} (пресет)")

    try:
        import ollama as ollama_lib
        client = ollama_lib.Client(host=config.ollama.host)
        models = client.list()
        model_names = [m.model for m in models.models] if models.models else []
        print_check_ok("Ollama", config.ollama.host)

        if config.ollama.model in model_names:
            print_check_ok("Модель", f"{config.ollama.model} (установлена)")
        else:
            print_check_fail("Модель", f"{config.ollama.model} (не найдена, запустите: ollama pull {config.ollama.model})")
            return 1
    except Exception as e:
        print_check_fail("Ollama", str(e))
        return 1

    console.print()
    console.print("[success]Все проверки пройдены[/]")
    return 0


def _cmd_presets(args: argparse.Namespace) -> int:
    from convaier.presets import PRESETS, list_presets

    filtered = {k: PRESETS[k] for k in list_presets()}
    print_presets_table(filtered)
    return 0


def _cmd_hook_install(args: argparse.Namespace) -> int:
    import importlib.resources
    import stat

    git_dir = Path(args.git_dir)
    hooks_dir = git_dir / "hooks"
    if not hooks_dir.exists():
        console.print(f"[error]Директория hooks не найдена: {hooks_dir}[/]")
        return 1

    dest = hooks_dir / "post-receive"
    if dest.exists() and not args.force:
        console.print(f"[error]Хук уже существует: {dest}[/] [dim](используйте --force для перезаписи)[/]")
        return 1

    try:
        pkg_hooks = importlib.resources.files("convaier.hooks")
        src_hook = pkg_hooks.joinpath("post-receive")
        content = src_hook.read_text(encoding="utf-8")
    except Exception as e:
        console.print(f"[error]Не удалось найти bundled хук: {e}[/]")
        return 1

    dest.write_text(content, encoding="utf-8")
    current_mode = dest.stat().st_mode
    dest.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    console.print(f"[success]Хук установлен: {dest}[/]")
    return 0


def _cmd_hook_status(args: argparse.Namespace) -> int:
    import os
    import stat

    git_dir = Path(args.git_dir)
    hook_path = git_dir / "hooks" / "post-receive"

    if not hook_path.exists():
        print_check_fail("post-receive", f"не установлен (нет файла {hook_path})")
        return 1

    # Проверка исполняемости — пропускаем на Windows (там нет Unix-битов)
    if os.name != "nt":
        mode = hook_path.stat().st_mode
        if not (mode & stat.S_IXUSR):
            print_check_fail("post-receive", f"файл есть, но не исполняемый: {hook_path}")
            return 1

    content = hook_path.read_text(encoding="utf-8", errors="replace")
    if "convaier" not in content:
        print_check_fail("post-receive", "установлен (изменён — не вызывает convaier)")
        return 0

    print_check_ok("post-receive", f"установлен — {hook_path}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
        from convaier.server.app import create_app
    except ImportError:
        console.print(
            "[error]Webhook-сервер требует дополнительных зависимостей.[/] "
            "Установите: [bold]pip install convaier[server][/]"
        )
        return 1

    from convaier.config import load_server_config

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        console.print(f"[error]Конфиг сервера не найден: {cfg_path}[/]")
        console.print("[dim]Создайте convaier-server.yml (см. документацию)[/]")
        return 1

    srv = load_server_config(cfg_path)
    srv.workspace.mkdir(parents=True, exist_ok=True)

    app = create_app(workspace=srv.workspace, secret=srv.secret, git_token=srv.git_token)

    console.print(f"[success]Convaier webhook-сервер запускается[/] на {srv.host}:{srv.port}")
    uvicorn.run(app, host=srv.host, port=srv.port, log_level=srv.log_level)
    return 0


def _cmd_hook(args: argparse.Namespace) -> int:
    if not getattr(args, "hook_command", None):
        console.print("[error]Укажите подкоманду: install | status[/]")
        return 1
    if args.hook_command == "install":
        return _cmd_hook_install(args)
    if args.hook_command == "status":
        return _cmd_hook_status(args)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="convaier",
        description="Локальный AI-конвейер CI/CD",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод")

    sub = parser.add_subparsers(dest="command")

    # run
    run_p = sub.add_parser("run", help="Запустить конвейер")
    run_p.add_argument("-c", "--config", default="convaier.yml", help="Путь к конфиг-файлу")
    run_p.add_argument("-s", "--stage", help="Этапы через запятую")
    run_p.add_argument("--dry-run", action="store_true", help="Показать этапы без запуска")
    run_p.add_argument("--full-scan", action="store_true",
                       help="Анализировать все файлы проекта (без git diff)")
    run_p.add_argument("--env", default="", metavar="ENV",
                       help="Окружение деплоя (dev/staging/prod)")

    # init
    init_p = sub.add_parser("init", help="Создать пример конфига")
    init_p.add_argument("-o", "--output", default="convaier.yml", help="Путь к выходному файлу")
    init_p.add_argument("-f", "--force", action="store_true", help="Перезаписать существующий файл")

    # index
    index_p = sub.add_parser("index", help="Индексировать проект для RAG")
    index_p.add_argument("-c", "--config", default="convaier.yml", help="Путь к конфиг-файлу")
    index_p.add_argument("-f", "--force", action="store_true", help="Переиндексировать с нуля")

    # presets
    sub.add_parser("presets", help="Список доступных пресетов языков")

    # check
    check_p = sub.add_parser("check", help="Проверить конфиг и подключение к Ollama")
    check_p.add_argument("-c", "--config", default="convaier.yml", help="Путь к конфиг-файлу")

    # serve
    serve_p = sub.add_parser("serve", help="Запустить webhook-сервер")
    serve_p.add_argument(
        "-c", "--config",
        default="convaier-server.yml",
        help="Путь к конфигу сервера (по умолчанию: convaier-server.yml)",
    )

    # hook
    hook_p = sub.add_parser("hook", help="Управление git-хуками")
    hook_sub = hook_p.add_subparsers(dest="hook_command")

    hook_install_p = hook_sub.add_parser("install", help="Установить post-receive хук")
    hook_install_p.add_argument(
        "--git-dir", default=".git", help="Путь к .git директории (по умолчанию: .git)"
    )
    hook_install_p.add_argument("-f", "--force", action="store_true", help="Перезаписать существующий хук")

    hook_status_p = hook_sub.add_parser("status", help="Проверить статус установки хука")
    hook_status_p.add_argument(
        "--git-dir", default=".git", help="Путь к .git директории (по умолчанию: .git)"
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "run": _cmd_run, "init": _cmd_init, "index": _cmd_index,
        "presets": _cmd_presets, "check": _cmd_check,
        "serve": _cmd_serve, "hook": _cmd_hook,
    }
    sys.exit(handlers[args.command](args))
