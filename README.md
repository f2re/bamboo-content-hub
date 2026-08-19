# Bamboo Content Hub

Локальный контент-центр Bamboo Pottery: изделие и медиа создаются один раз, ИИ возвращает структурированный `Bamboo Content Pack`, а Hub подготавливает отдельный контент и публикационные задания для соцсетей.

## Что уже работает
- каталог изделий и загрузка фото/видео;
- `bamboo-content-pack/1.0`: prompt → preview/import → безопасное merge;
- отдельные channel contents;
- черновики/расписание, delivery status, retries и idempotency foundation;
- demo channel, Telegram Bot API, ручной поток Ярмарки мастеров;
- OAuth framework для Google/YouTube, Pinterest, TikTok, Meta и VK: state, PKCE, encrypted tokens, refresh/revoke;
- signed public media URL и webhook storage/Meta signature verification;
- адаптивный PWA-интерфейс;
- SQLite WAL + Alembic, Docker Compose, backup/restore/update.

## Быстрый старт
```bash
git clone https://github.com/f2re/bamboo-content-hub.git
cd bamboo-content-hub
./scripts/install.sh
```
Откройте `http://localhost:8080`.

## Разработка
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload --port 8080
pytest
```

## Документация
- [design.md](design.md) — визуальная система;
- [PLAN.md](PLAN.md) — фактический roadmap;
- [AI import](docs/AI_IMPORT.md);
- [Integrations](docs/INTEGRATIONS.md);
- [Operations](docs/OPERATIONS.md);
- [Security](docs/SECURITY.md);

## Важное ограничение
Код OAuth и ядро интеграций не равны «живому production-доступу» к аккаунту. Instagram/Pinterest/TikTok/VK/YouTube требуют ваши developer credentials, а часть возможностей — review/audit приложения. Hub показывает это как подключение, а не имитирует успешную реальную публикацию.
