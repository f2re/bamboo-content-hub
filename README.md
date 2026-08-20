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

## ИИ: как подготовить тексты для всех площадок

Канонический рабочий промпт формируется кодом `app/ai_pack.py::build_prompt()` для конкретного изделия. В интерфейсе он публикуется в карточке изделия: **Изделия → нужное изделие → Импорт из ИИ** (`/products/{id}/ai`). Не составляйте `request_id` и JSON Schema вручную: хаб вставляет их в запрос сам.

Порядок работы:
1. Создайте изделие и внесите все известные факты. Человеческие данные имеют приоритет над данными ИИ.
2. Загрузите фото/видео в том порядке, в котором модель должна их рассматривать.
3. Откройте **Импорт из ИИ** и нажмите **Скопировать запрос**.
4. Передайте этот запрос и те же медиа мультимодальной модели, способной вернуть строгий JSON.
5. Скопируйте весь JSON-ответ модели обратно в Bamboo Content Hub.
6. Нажмите **Проверить**. Просмотрите `needs_confirmation` и `assumptions`; неизвестные характеристики не должны превращаться в факты.
7. Нажмите **Импортировать**. Хаб заполнит только пустые значения и сохранит отдельный контент для площадок.
8. Перед публикацией выберите медиа, канал, время и обязательные параметры самой площадки. Например, видимость и коммерческие декларации TikTok задаются человеком, а не ИИ.

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

Базовая часть промпта выглядит так; рабочая версия дополнительно содержит реальные `request_id`, список медиа, известные данные изделия, правила выбранных площадок и актуальную JSON Schema:

```text
Ты — контент-редактор гончарной мастерской Bamboo Pottery.

Верни ТОЛЬКО один валидный JSON без Markdown и пояснений.
Используй schema_version bamboo-content-pack/1.0 и request_id <request_id>.
Медиа идут в порядке прикрепления и внутри схемы называются: image_1...N.
Подготовь отдельный вариант контента для запрошенных площадок.

Считай известные данные пользователя источником истины. По вложенным медиа
описывай только то, что действительно видно или слышно. Не придумывай цену,
материал, размеры, объём, массу, глазурь, режим обжига, food-safe, ПММ, СВЧ,
наличие, сроки, скидки, ссылки или доставку. Неизвестное оставляй пустым и
добавляй вопрос в needs_confirmation. Предположения записывай в assumptions.

Сформируй общий content и отдельный, реально адаптированный текст для каждой
площадки. Не копируй один текст во все каналы. Тон Bamboo Pottery — спокойный,
тёплый, человеческий и предметный, без рекламных клише и выдуманной срочности.
URL не выдумывай. Параметры публикации и согласия, которые выбирает человек,
не угадывай; channels.tiktok.privacy оставляй null.

<известные данные изделия>
<актуальная JSON Schema>
```

Полная пользовательская инструкция и правила по каждой площадке: [docs/AI_IMPORT.md](docs/AI_IMPORT.md). В запущенном приложении она также доступна через **Справка** в навигации и со страницы **Импорт из ИИ**.

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
- [AI import](docs/AI_IMPORT.md) — порядок работы с ИИ, промпт и поля площадок;
- [Integrations](docs/INTEGRATIONS.md);
- [Operations](docs/OPERATIONS.md);
- [Security](docs/SECURITY.md).

## Важное ограничение
Код OAuth и ядро интеграций не равны «живому production-доступу» к аккаунту. Instagram/Pinterest/TikTok/VK/YouTube требуют ваши developer credentials, а часть возможностей — review/audit приложения. Hub показывает это как подключение, а не имитирует успешную реальную публикацию.
