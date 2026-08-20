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

## ИИ: готовый запрос без ручной сборки

Рабочий промпт **не надо брать из README, править или собирать по частям**. Он формируется на лету для конкретного изделия на странице **Изделия → нужное изделие → Импорт из ИИ** (`/products/{id}/ai`).

На этой странице Bamboo Content Hub автоматически подставляет:
- текущий `request_id`;
- известные факты изделия;
- количество и порядок фото/видео (`image_1...N`);
- редакционные правила Bamboo Pottery;
- отдельные требования для Instagram, VK, Telegram, Pinterest, Facebook, TikTok, YouTube и Ярмарки мастеров;
- полный контракт ответа;
- актуальную JSON Schema `bamboo-content-pack/1.0` из установленной версии приложения.

Порядок работы фактически сводится к трём действиям:
1. Откройте **Импорт из ИИ** и нажмите **Скопировать готовый запрос**. Ничего в нём не дописывайте.
2. Вставьте запрос в мультимодальную модель и приложите показанные на странице фото/видео в том же порядке.
3. Скопируйте один JSON-ответ обратно в Hub, нажмите **Проверить**, затем **Импортировать**.

Если карточка изделия или медиа изменились, на странице есть **Обновить из карточки**: страница заново формирует рабочий запрос из текущего состояния.

Что готовит один `Bamboo Content Pack`:

| Площадка | Поля |
|---|---|
| Instagram | `caption`, `hashtags` |
| VK | `text`, `hashtags` |
| Telegram | `text`, `button_text`, `button_url` |
| Pinterest | `title`, `description`, `keywords`, `board_suggestion`, `destination_url` |
| Facebook | `text` |
| TikTok | `caption`, `hashtags`; `privacy` ИИ оставляет `null` |
| YouTube | `title`, `description`, `tags` |
| Ярмарка мастеров | `title`, `short_description`, `description`, `keywords`, `category_suggestion` |

ИИ не должен придумывать цену, материалы, размеры, объём, массу, глазурь, режим обжига, food-safe, ПММ/СВЧ, наличие, сроки, скидки, ссылки или доставку. Неизвестные важные факты остаются пустыми и при необходимости попадают в `needs_confirmation`; предположения — в `assumptions`.

Пользовательский источник истины для промпта — именно страница `/products/{id}/ai`. Документация только объясняет механику и не заменяет автоматически сформированный запрос.

Полная инструкция: [docs/AI_IMPORT.md](docs/AI_IMPORT.md). В приложении — **Справка** в навигации.

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
- [AI import](docs/AI_IMPORT.md) — порядок работы с ИИ и поля площадок;
- [Integrations](docs/INTEGRATIONS.md);
- [Operations](docs/OPERATIONS.md);
- [Security](docs/SECURITY.md).

## Важное ограничение
Код OAuth и ядро интеграций не равны «живому production-доступу» к аккаунту. Instagram/Pinterest/TikTok/VK/YouTube требуют ваши developer credentials, а часть возможностей — review/audit приложения. Hub показывает это как подключение, а не имитирует успешную реальную публикацию.
