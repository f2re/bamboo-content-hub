# Changelog

## Unreleased
- AI prompt теперь всегда формируется как полный runtime-контракт для конкретного изделия: все корневые разделы Bamboo Content Pack, правила каналов, media mapping и актуальная JSON Schema.
- Страница «Импорт из ИИ» стала copy/paste-потоком: готовый запрос, подписи image_1…N рядом с медиа, обновление из текущей карточки и надёжное копирование также по HTTP в локальной сети.
- Из справки удалён статический промпт для копирования, чтобы пользователь не мог случайно использовать устаревший шаблон вместо runtime-запроса.
- README фиксирует единый пользовательский источник промпта — `/products/{id}/ai`.
- Расширен AI prompt: отдельные редакционные правила для Instagram, VK, Telegram, Pinterest, Facebook, TikTok, YouTube и Ярмарки мастеров.
- Добавлена встроенная справка по AI workflow, фактологическим ограничениям и импорту `Bamboo Content Pack`.
- README и `docs/AI_IMPORT.md` содержат единый порядок работы и карту полей площадок.

## 0.2.0
- Реальный local-first core: products, media, AI import, publications/deliveries.
- OAuth state/PKCE/exchange/refresh/revoke and encrypted credential storage.
- Signed public media URL and webhook event storage with Meta HMAC verification.
- Responsive PWA UI and deployment/update/backup tooling.
