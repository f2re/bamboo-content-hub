# Эксплуатация

## Установка
`cp .env.example .env && ./scripts/install.sh`

## Обновление
`./scripts/update.sh` выполняет backup → `git fetch` → fast-forward → build → migrations → restart → smoke. Локальные изменения блокируют автоматическое обновление.

## Backup
`./scripts/backup.sh`. SQLite копируется через native backup API, затем архивируется media. `MASTER_KEY` храните отдельно: без него encrypted credentials восстановить невозможно.

## Restore
`./scripts/restore.sh backups/<archive>.tgz` сначала создаёт страховочную копию, останавливает writer, восстанавливает DB/media, делает `PRAGMA integrity_check`, стартует Hub и выполняет smoke test.

## Публичный edge
Не публикуйте весь UI в интернет без аутентификации. Наружу достаточно проксировать `/oauth/*`, `/webhooks/*`, `/media/public/*`; UI используйте через LAN/VPN.
