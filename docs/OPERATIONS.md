# Эксплуатация

## Установка из исходников

```bash
cp .env.example .env   # необязательно: install.sh создаст файл сам
./scripts/install.sh
```

`install.sh` генерирует отдельные `SECRET_KEY` и `MASTER_KEY`, если `.env` ещё нет, собирает контейнер, запускает его и ждёт успешного `/health/ready`. Успешное завершение скрипта означает, что приложение действительно отвечает локально, а не только что Docker принял команду запуска.

## Контейнер из GHCR

Каждый merge в `main` и каждый тег `v*` публикует образ `ghcr.io/f2re/bamboo-content-hub`. Compose поддерживает тот же образ через переменную:

```bash
export BAMBOO_IMAGE=ghcr.io/f2re/bamboo-content-hub:latest
docker compose -f compose.yml pull bamboo
docker compose -f compose.yml up -d --no-build bamboo
./scripts/smoke.sh
```

Для воспроизводимого production-развёртывания предпочтительнее тег релиза (`vX.Y.Z`) или SHA-тег вместо `latest`.

## Безопасное обновление из Git

```bash
./scripts/update.sh
```

Перед обновлением скрипт требует чистое рабочее дерево и создаёт архив БД/медиа. Затем выполняется `git fetch` → fast-forward → build → Alembic migration → restart → healthcheck.

Обновление считается успешным только после `/health/ready`. При любой ошибке после создания backup срабатывает автоматический rollback:

1. контейнер останавливается;
2. SQLite и медиатека восстанавливаются из pre-update backup;
3. Git возвращается к исходному SHA;
4. старый контейнер пересобирается и запускается;
5. локальный readiness проверяется повторно.

Если даже откат не вернул `/health/ready`, скрипт выводит абсолютный путь резервной копии и готовую команду `restore.sh`. Backup не удаляется автоматически.

## Backup

```bash
./scripts/backup.sh
```

SQLite копируется через native backup API, затем архивируется `data/media`. Имя содержит timestamp и PID, поэтому параллельные/последовательные операции в одну секунду не перезаписывают архив. В архив добавляется `backup-meta.txt` с временем, Git SHA и версией формата.

`MASTER_KEY` храните отдельно: без него encrypted credentials из восстановленной БД расшифровать невозможно. Сам `.env` намеренно не попадает в backup данных.

## Restore

```bash
./scripts/restore.sh backups/<archive>.tgz
```

До остановки сервиса `restore.sh`:

- проверяет, что tar-архив читается;
- распаковывает его во временный каталог;
- выполняет `PRAGMA integrity_check` над SQLite из архива;
- создаёт отдельную страховочную копию текущего состояния.

Только после этого текущая БД/медиа заменяются. После восстановления выполняется повторный integrity check, запуск контейнера и readiness smoke.

## Smoke / диагностика запуска

```bash
./scripts/smoke.sh
```

Smoke всегда проверяет локальный `127.0.0.1:${BAMBOO_PORT:-8080}`, даже если `APP_BASE_URL` указывает на публичный домен. По умолчанию он ждёт готовность до 60 секунд. Для диагностики можно задать `BAMBOO_SMOKE_URL`, `BAMBOO_SMOKE_ATTEMPTS`, `BAMBOO_SMOKE_DELAY_SECONDS`.

## CI и release gate

Pull request проходит три независимых job:

- `test`: Ruff, compileall, browser JS syntax, Bash syntax, Compose config, Alembic и pytest;
- `docker`: чистая Buildx-сборка контейнера;
- `lifecycle`: фактический `install.sh` на чистом runner → healthcheck → backup → restore → повторный healthcheck.

После merge отдельный workflow публикует GHCR image. Dependabot еженедельно проверяет Python, GitHub Actions и Docker dependencies.

## Публичный edge

Не публикуйте весь UI в интернет без аутентификации. Для OAuth/provider callback нужны публичные маршруты; административный UI безопаснее оставлять за HTTPS reverse proxy/VPN. При `TRUSTED_LAN=false` обязательно настройте admin password и HTTPS.
