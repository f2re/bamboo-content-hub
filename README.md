# Bamboo Content Hub

Локальный контент-центр Bamboo Pottery: изделие и медиа создаются один раз, ИИ возвращает структурированный `Bamboo Content Pack`, а Hub подготавливает отдельный контент и публикационные задания для соцсетей.

## Что уже работает
- каталог изделий, ручной редактор характеристик и текстов площадок;
- загрузка/оптимизация фото и видео, порядок медиа, обложка и удаление;
- `bamboo-content-pack/1.0`: полный runtime prompt → preview/import → безопасное merge;
- отдельные channel contents;
- черновики/расписание, delivery status, retries и idempotency foundation;
- автоматические Telegram, VK, Pinterest, Instagram, Facebook, TikTok и YouTube; ручной поток Ярмарки мастеров;
- OAuth state/PKCE/exchange/refresh/revoke и encrypted token storage;
- пошаговый экран подключений: Client ID/Secret можно сохранить из UI, а доски/страницы/стены определить автоматически;
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

Рабочий промпт **не надо брать из README, править или собирать по частям**. Он формируется на лету для конкретного изделия на странице **Изделия → нужное изделие → Подготовка с ИИ** (`/products/{id}/ai`).

На этой странице Bamboo Content Hub автоматически подставляет:
- текущий `request_id`;
- известные факты изделия;
- количество и порядок фото/видео (`image_1...N`);
- редакционные правила Bamboo Pottery;
- отдельные требования для Instagram, VK, Telegram, Pinterest, Facebook, TikTok, YouTube и Ярмарки мастеров;
- полный контракт ответа;
- актуальную JSON Schema `bamboo-content-pack/1.0` из установленной версии приложения.

Порядок работы сводится к трём действиям:
1. Нажмите **Скопировать готовый запрос**. Ничего в нём не дописывайте.
2. Вставьте запрос в мультимодальную модель и приложите показанные на странице фото/видео в том же порядке.
3. Скопируйте один JSON-ответ обратно в Hub, нажмите **Проверить**, затем **Импортировать**.

Если карточка изделия или медиа изменились, нажмите **Обновить из карточки**: страница заново формирует запрос из текущего состояния.

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

Полная инструкция: [docs/AI_IMPORT.md](docs/AI_IMPORT.md).

## Подключения: без поиска ID и редактирования `.env`

Для обычной настройки откройте **Подключения**. Карточка каждой площадки сама показывает порядок действий и готовые официальные ссылки.

Для OAuth-площадок:
1. Откройте кабинет разработчика кнопкой в Bamboo и создайте приложение.
2. Скопируйте показанный callback URL в Redirect URI приложения.
3. Вставьте Client ID и Client Secret прямо в Bamboo и сохраните. Secret хранится зашифрованно.
4. Нажмите **Подключить аккаунт** и подтвердите OAuth на сайте площадки.
5. Pinterest/Meta/VK: нажмите **Найти…** и выберите доску/страницу/стену по названию. Bamboo сам подставит `board_id`, `facebook_page_id`/`instagram_user_id` или `owner_id`.

Существующие переменные OAuth в `.env` продолжают работать, но для новой установки они не обязательны. Telegram подключается ещё проще: открыть BotFather → вставить токен → указать `@имя_канала` → проверить.

Важно: многие OAuth-провайдеры не принимают callback вида `http://192.168.x.x`. Для реального OAuth настройте в `APP_BASE_URL` доступный HTTPS-адрес; экран подключений показывает готовый callback и предупреждает о небезопасном LAN HTTP.

Подробности и ссылки: [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).

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
- [AI import](docs/AI_IMPORT.md) — runtime-промпт и импорт Bamboo Content Pack;
- [Integrations](docs/INTEGRATIONS.md) — пошаговые подключения и официальные ссылки;
- [Operations](docs/OPERATIONS.md);
- [Security](docs/SECURITY.md).

## Важное ограничение
Наличие адаптера не отменяет требований самой площадки. Instagram/Pinterest/TikTok/VK/YouTube могут требовать developer credentials, подтверждённый домен, review/audit приложения или специальные права аккаунта. Hub показывает реальные состояния и ошибки подключения, а не имитирует успешную публикацию.
