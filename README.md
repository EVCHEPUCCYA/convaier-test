# Convaier

Convaier запускается на сервере и проверяет код при каждом push в репозиторий. Он прогоняет линтеры, отправляет изменения локальной AI-модели на ревью, проверяет безопасность и автоматически заводит задачи на доработку в YouGile. Поддерживает деплой в несколько окружений (dev/staging/prod), в том числе на удалённые серверы по SSH.

Всё работает внутри контура. Код не уходит, куда не надо.

---

## Требования

- Python 3.10+
- [Ollama](https://ollama.com) на том же сервере
- Git
- Docker — для стадий build и deploy
- YouGile — если нужно автозаведение задач

---

## Принцип работы

Разработчик делает push. GitHub или Gogs отправляет уведомление (webhook) на сервер с Convaier. Convaier клонирует репозиторий, читает его конфигурацию и запускает последовательность проверок.

Каждая проверка — это стадия. Стадии выполняются по порядку и передают результаты друг другу. Это важно: если линтер нашёл проблему, AI не будет повторять её в ревью. Если security-стадия нашла уязвимость, ревью её уже знает.

В конце все найденные проблемы уходят в YouGile как задачи.

```
push → webhook → clone → convaier.yml
                              ↓
                   commit → lint → security → review → tracker → test → build → deploy
```

Проверяются только изменённые файлы. AI работает локально через Ollama.

### Что делает каждая стадия

**commit** — смотрит, что изменилось (`git diff`). Остальные стадии работают с этим списком.

**lint** — запускает линтеры. Результаты уходят в AI-стадии, чтобы те не повторяли одно и то же.

**security** — сначала гоняет инструменты (bandit, pip-audit, npm-audit), потом отдаёт каждый изменённый файл AI на проверку. AI ищет то, что инструменты могут пропустить: небезопасные паттерны, утечки данных, логические дыры.

**review** — смотрит на качество кода, архитектуру, читаемость, потенциальные баги.

**tracker** — собирает всё найденное и создаёт задачи в YouGile. Одна проблема — одна задача. Повторный push не дублирует.

**test** — запускает тесты. Поддерживает несколько независимых наборов (unit, integration, e2e). Если тесты упали и включён `ai_analysis` — AI разбирает вывод и объясняет вероятную причину.

**build** — Docker build. Если что-то упало раньше — пропускается.

**deploy** — `docker compose up -d`. Поддерживает именованные окружения (dev/staging/prod) и SSH-деплой на удалённый сервер. Запускается с флагом `--env` для выбора окружения.

### Как AI получает задание

На каждый файл собирается отдельный запрос: роль (аудитор / ревьюер), чеклист проверок, правила команды, diff, содержимое файла, что уже нашли другие стадии.

Модель отвечает в фиксированном формате: файл, строка, severity, проблема, причина, как исправить. Convaier парсит это и превращает в задачи YouGile.

---

## Установка

```bash
git clone <repo-url>
cd convaier
pip install -e ".[all]"
```

Если нужны не все компоненты:

```bash
pip install -e ".[server]"    # webhook-сервер
pip install -e ".[security]"  # bandit, pip-audit
pip install -e ".[rag]"       # RAG (поиск по кодовой базе)
```

Установить модель в Ollama:

```bash
ollama pull qwen2.5-coder:7b
```

---

## Настройка сервера

На сервере компании создаётся один конфиг `convaier-server.yml`:

```yaml
server:
  host: 0.0.0.0
  port: 8765
  secret: "секрет-для-подписи-вебхуков"
  workspace: /var/lib/convaier/repos   # сюда клонируются репозитории
  git_token: ""                        # токен для приватных репо
  log_level: info
```

Запуск:

```bash
convaier serve --config convaier-server.yml
```

Сервер при первом push клонирует репозиторий, при следующих — обновляет и переключается на нужный коммит. Репозитории регистрировать вручную не нужно.

Проверить что работает:

```bash
curl http://your-server:8765/healthz
# {"status": "ok", "queue_size": 0}
```

### Подключить GitHub

```
GitHub → Settings → Webhooks → Add webhook

Payload URL:  http://your-server:8765/webhook
Content type: application/json
Secret:       <тот же что в convaier-server.yml>
Events:       Just the push event
```

### Подключить Gogs

```
Gogs → Repo Settings → Webhooks → Add webhook → Gogs

Payload URL:  http://your-server:8765/webhook
Secret:       <тот же секрет>
```

URL и код сервера при переходе с GitHub на Gogs не меняются — Convaier понимает оба формата.

---

## Конфигурация репозитория

В каждом репозитории лежит `convaier.yml`. Именно его читает Convaier после клонирования.

Создать шаблон:

```bash
convaier init
```

Полный пример:

```yaml
project:
  name: my-app
  language: python        # автоматически подбирает инструменты

ollama:
  host: http://localhost:11434
  model: qwen2.5-coder:7b
  timeout: 300
  num_ctx: 4096

pipeline:
  fail_fast: true         # остановиться при первой ошибке
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
    commands:
      - name: unit
        command: pytest tests/unit -q
      - name: integration
        command: pytest tests/integration -q
    ai_analysis: false        # AI-разбор упавших тестов

  build:
    dockerfile: Dockerfile
    image_name: my-app
    tag: latest

  deploy:
    compose_file: docker-compose.yml   # используется если --env не задан
    service: app
    environments:
      dev:
        compose_file: docker-compose.dev.yml
        service: app
      prod:
        compose_file: docker-compose.prod.yml
        service: app
        ssh:
          host: 192.168.1.100
          user: deploy
          key_file: ~/.ssh/id_rsa
          remote_path: /opt/my-app

reports:
  output_dir: .convaier/reports
  formats:
    - markdown
    - json

yougile:
  enabled: true
  base_url: https://yougile.com/api-v2
  token: your-api-token
  column_id: "uuid-колонки"
  min_severity: warning
```

### Языковые пресеты

Если указан `language` — инструменты подставляются автоматически. Любые настройки в `stages:` перекрывают пресет.

| Язык | Lint | Security | Test |
|------|------|----------|------|
| python | ruff | bandit, pip-audit | pytest |
| javascript | eslint | npm audit | jest |
| typescript | eslint, tsc | npm audit | jest |
| java | checkstyle | spotbugs | mvn test |
| go | golangci-lint | gosec | go test |

---

## Правила для AI

Можно добавить правила, которые модель будет учитывать при проверке — например, запрещённые паттерны, требования к документированию, специфика архитектуры проекта. Правила добавляются к встроенному чеклисту.

Самый простой способ — положить файл в репозиторий:

```
.convaier/rules/security.md   → правила для стадии security
.convaier/rules/review.md     → правила для стадии review
.convaier/rules/global.md     → применяется в обеих стадиях
```

Или прописать прямо в `convaier.yml`:

```yaml
rules:
  security: .convaier/rules/security.md
  review: |
    - Запрещено использовать eval()
    - Публичные методы должны иметь docstring
    - Новые зависимости — с обоснованием в комментарии
```

---

## Деплой в разные окружения

Окружения описываются в секции `stages.deploy.environments`. Каждое может переопределить compose-файл, сервис и способ подключения.

```yaml
stages:
  deploy:
    compose_file: docker-compose.yml   # fallback без --env

    environments:
      dev:
        compose_file: docker-compose.dev.yml
        service: app

      staging:
        compose_file: docker-compose.staging.yml
        service: app

      prod:
        compose_file: docker-compose.prod.yml
        service: app
        ssh:                           # деплой на удалённый сервер
          host: 10.0.0.50
          user: deploy
          key_file: ~/.ssh/id_rsa      # опционально
          remote_path: /opt/my-app
```

Выбор окружения при запуске:

```bash
convaier run --env dev
convaier run --env prod
convaier run              # без --env → fallback-конфиг
```

SSH-деплой вызывает `docker compose up -d` напрямую на сервере через `ssh user@host`. Ключ по умолчанию берётся из `~/.ssh/id_rsa`, можно указать другой через `key_file`.

---

## Запуск вручную

```bash
convaier run                        # весь конвейер
convaier run -s lint,security       # только указанные стадии
convaier run --full-scan            # все файлы, не только изменённые
convaier run --env prod             # деплой в конкретное окружение
convaier check                      # проверить соединение с Ollama
```

