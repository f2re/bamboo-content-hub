# Подключения соцсетей

Документ содержит эксплуатационные требования; перед production-подключением сверяйте scopes и review-требования с текущей официальной документацией провайдера.

## Telegram
Создайте бота через BotFather, добавьте его администратором канала и в «Подключения» укажите bot token и chat ID/`@channel`. Токен хранится зашифрованно.

## Google / YouTube
Создайте OAuth Web Application в Google Cloud, включите YouTube Data API и зарегистрируйте callback:
`https://<ваш-host>/oauth/google/callback`.
Хаб запрашивает offline access для возможности публикаций по расписанию и сохраняет refresh token зашифрованно.

## Pinterest
Создайте приложение Pinterest Developer и callback `/oauth/pinterest/callback`. Нужны scopes чтения досок и создания Pins. Production-возможности зависят от уровня доступа приложения.

## TikTok
Создайте TikTok developer app, подключите Login Kit/Content Posting и callback `/oauth/tiktok/callback`. Для публичного Direct Post приложение должно соответствовать текущим audit/review-требованиям TikTok.

## Meta / Instagram / Facebook
Создайте Meta app и настройте разрешённый callback `/oauth/meta/callback`. Набор permissions и версия Graph API меняются; endpoints вынесены в `.env`. Для Instagram publishing могут потребоваться публично доступные HTTPS media URLs — Hub генерирует краткоживущие signed URLs.

## VK
Создайте приложение VK ID и зарегистрируйте `/oauth/vk/callback`. Endpoints вынесены в `.env`, чтобы обновлять OAuth-профиль независимо от ядра.

## Ярмарка мастеров
В базовой версии используется контролируемый ручной экспорт. Скрытые undocumented endpoints сайта не используются.
