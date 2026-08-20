# Release checklist

Эта памятка используется перед созданием тега `vX.Y.Z`.

## 1. Код и данные

- [ ] `main` содержит только прошедшие review/CI изменения.
- [ ] Рабочая версия в `pyproject.toml` и `app.main` соответствует планируемому тегу.
- [ ] `CHANGELOG.md` переносит относящиеся к релизу пункты из `Unreleased` в секцию версии.
- [ ] Все Alembic migrations проходят на чистой базе.
- [ ] Clean install → backup → restore → healthcheck проходит в CI.
- [ ] Fault-injection update test подтверждает автоматический rollback после неуспешной миграции/обновления.

## 2. Качество

- [ ] Ruff, compileall, browser `node --check`, Bash syntax и pytest зелёные.
- [ ] Docker Buildx зелёный.
- [ ] Нет открытого P0/security blocker.
- [ ] Изменённые пользовательские flow проверены на телефоне и desktop.
- [ ] Технические статусы/ошибки не просачиваются в основной пользовательский интерфейс без объяснения.

## 3. Интеграции

Для каждой реально используемой площадки:

- [ ] health-check зелёный;
- [ ] выбран правильный account/Page/board/wall;
- [ ] выполнена небольшая приватная/тестовая публикация;
- [ ] публикация подтверждена в интерфейсе провайдера;
- [ ] ограничения review/audit конкретного приложения зафиксированы.

## 4. Backup и восстановление

- [ ] `./scripts/backup.sh` создаёт читаемый архив с `backup-meta.txt`.
- [ ] `./scripts/restore.sh <archive>` проходит integrity check до и после восстановления.
- [ ] `MASTER_KEY` сохранён отдельно от backup данных.
- [ ] На тестовой установке проверен `./scripts/update.sh`.

## 5. Публикация

После merge в `main` workflow `Release image` публикует:

- `ghcr.io/f2re/bamboo-content-hub:latest`;
- SHA-тег.

После создания тега `vX.Y.Z` публикуется одноимённый immutable release tag. Перед объявлением релиза проверьте pull/run образа на чистой машине или VM.

## 6. После релиза

- [ ] проверить `/health/ready` production-инсталляции;
- [ ] проверить scheduler и одну безопасную delivery;
- [ ] проверить свежий backup;
- [ ] оставить release notes со списком миграций, изменившихся интеграций и известных ограничений.
