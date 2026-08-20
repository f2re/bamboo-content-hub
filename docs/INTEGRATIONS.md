# Подключения соцсетей

Экран **«Подключения»** рассчитан на обычного пользователя: редактировать `.env` для OAuth больше не обязательно. Client ID и Client Secret можно сохранить прямо в интерфейсе; секрет хранится зашифрованно и после сохранения не показывается. Значения из `.env` по-прежнему поддерживаются как совместимый fallback.

## Общий порядок

Для Google/YouTube, Pinterest, TikTok, Meta и VK карточка подключения ведёт по трём шагам:

1. Нажмите готовую ссылку **«Открыть …»** и создайте приложение у площадки.
2. Скопируйте показанный Bamboo **Callback URL**, добавьте его в Redirect URI/Callback URL приложения, затем вставьте Client ID и Client Secret обратно в Bamboo и сохраните.
3. Нажмите **«Подключить аккаунт»** и подтвердите OAuth на официальной странице площадки.

Если площадке нужен конкретный объект публикации, искать числовой ID вручную обычно не требуется:

- Pinterest → **«Найти мои доски Pinterest»**;
- Meta → **«Найти мои страницы Meta»**, Bamboo одновременно подставит Facebook Page ID и связанный Instagram Professional ID;
- VK → **«Найти доступные стены VK»**, Bamboo предложит личную стену и доступные сообщества.

После выбора Bamboo сам заполняет ID и сохраняет его. Текстовые поля ID оставлены как fallback для редких случаев, когда API не возвращает нужный объект.

## Готовые официальные ссылки

| Площадка | Куда нажимать |
|---|---|
| Telegram | https://t.me/BotFather |
| Google / YouTube OAuth | https://console.cloud.google.com/apis/credentials |
| Включить YouTube Data API | https://console.cloud.google.com/apis/library/youtube.googleapis.com |
| Pinterest Apps | https://developers.pinterest.com/apps/ |
| Pinterest: создание приложения | https://developers.pinterest.com/docs/getting-started/connect-app/ |
| TikTok Developers | https://developers.tiktok.com/ |
| TikTok: создание приложения | https://developers.tiktok.com/doc/getting-started-create-an-app |
| Meta Apps | https://developers.facebook.com/apps/ |
| Meta: создание приложения | https://developers.facebook.com/docs/development/create-an-app/ |
| VK ID: создание приложения | https://id.vk.com/about/business/go/docs/ru/vkid/latest/vk-id/connection/create-application |

Эти же ссылки встроены непосредственно в карточки «Подключения», поэтому открывать документацию отдельно для обычной настройки не нужно.

## Callback URL и HTTPS

Bamboo показывает готовый callback вида:

```text
<APP_BASE_URL>/oauth/<provider>/callback
```

Его нужно вставить у провайдера **без изменений**. OAuth-провайдеры могут отклонять обычный `http://192.168.x.x:8080`. Для production-подключений используйте доступный HTTPS-адрес в `APP_BASE_URL`. Интерфейс показывает предупреждение, если текущий адрес выглядит как небезопасный LAN HTTP.

## Матрица адаптеров

| Канал | Режим | Медиа | Проверка подключения | Состояние после отправки |
|---|---|---|---|---|
| Telegram | автоматический | текст, фото, видео, группы до 10 файлов | `getMe` | опубликовано сразу |
| VK | автоматический | текст, фото | профиль/стена | опубликовано сразу |
| Pinterest | автоматический | одно изображение | OAuth + доска | опубликовано сразу |
| Instagram | автоматический | фото, карусель, видео | Meta Graph API | опрос контейнера до готовности |
| Facebook | автоматический | текст, фото, видео | Meta Graph API | опубликовано сразу |
| TikTok | Direct Post | одно видео либо до 35 фото | свежий `creator_info` | опрос `publish/status/fetch` |
| YouTube | resumable upload | одно видео | `channels.list(mine=true)` | опрос обработки видео |
| Ярмарка мастеров | ручной экспорт | по инструкции | не требуется | подтверждает пользователь |

## Telegram

1. Нажмите **«Открыть BotFather»**.
2. Создайте бота командой `/newbot` и скопируйте токен.
3. Добавьте бота администратором канала с правом публикации.
4. В Bamboo вставьте токен и `@имя_канала`. Для публичного канала числовой chat ID искать не нужно.
5. Нажмите **«Сохранить Telegram»**, затем **«Проверить подключение»**.

## Google / YouTube

1. Откройте Google Cloud из карточки Bamboo.
2. Включите YouTube Data API.
3. Создайте OAuth Web Application.
4. Скопируйте callback из Bamboo в Authorized redirect URIs.
5. Скопируйте Client ID и Client Secret в Bamboo, сохраните и нажмите **«Подключить аккаунт»**.

Bamboo запрашивает offline access, хранит refresh token зашифрованно и автоматически обновляет access token. Категория видео остаётся дополнительным параметром; по умолчанию используется `22` (People & Blogs).

## Pinterest

Создайте Pinterest app, добавьте callback, сохраните Client ID/Secret в Bamboo и выполните OAuth. После этого нажмите **«Найти мои доски Pinterest»** — Hub запросит доступные доски через API и предложит их человеческими названиями. `board_id` вручную нужен только как fallback. Раздел доски остаётся необязательным дополнительным полем.

Для публикации требуются scopes `boards:read`, `boards:write`, `pins:read`, `pins:write`. Production-возможности зависят от уровня доступа Pinterest приложения.

## TikTok

1. Создайте TikTok developer app.
2. Добавьте Login Kit и Content Posting API.
3. Зарегистрируйте callback из Bamboo.
4. Сохраните Client key/Client secret в Bamboo и подключите аккаунт.
5. Перед публикацией Hub сам получает актуальный `creator_info` и показывает допустимую видимость и ограничения.

Для публикации фото нужен подтверждённый публичный HTTPS-домен/URL prefix, с которого TikTok сможет скачать signed media URL. До прохождения TikTok review/audit Direct Post может быть ограничен тестовыми пользователями и видимостью.

## Meta / Instagram / Facebook

1. Создайте Meta app по ссылке из карточки.
2. Добавьте callback Bamboo.
3. Сохраните App ID и App Secret, выполните OAuth.
4. Нажмите **«Найти мои страницы Meta»**.
5. Выберите страницу по названию. Bamboo автоматически сохранит её Facebook Page ID и, если он связан, Instagram Professional ID.

Для Instagram publishing медиа должны быть доступны Meta по публичному HTTPS URL; Hub генерирует краткоживущие signed URL.

## VK

1. Создайте VK ID приложение по готовой ссылке.
2. Зарегистрируйте callback Bamboo.
3. Сохраните Client ID/Secret и выполните OAuth.
4. Нажмите **«Найти доступные стены VK»**.
5. Выберите личную страницу или сообщество — Bamboo сам сохранит положительный/отрицательный `owner_id`.

## Ярмарка мастеров

Используется контролируемый ручной экспорт. Скрытые undocumented endpoints сайта не используются.

## Проверка перед production

CI проверяет контракты адаптеров, OAuth, payload, retry/status flow и сборку. Реальная отправка во внешние аккаунты не выполняется в CI, поскольку требует пользовательских токенов, подтверждённых доменов и review/audit провайдера.

После подключения каждого аккаунта нажмите **«Проверить …»**, затем создайте одну приватную/тестовую публикацию и убедитесь, что результат появился на площадке.
