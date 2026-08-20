# План разработки

## Текущее состояние — 0.3.0
- [x] Local-first FastAPI app, SQLite WAL, Alembic, Docker Compose.
- [x] Каталог изделий, локальная медиатека и ручной редактор характеристик.
- [x] CSP-safe создание изделия: dialog controller + самостоятельный fallback `/new-product` без JavaScript.
- [x] Редактирование отдельных текстов Instagram, VK, Telegram, Pinterest, Facebook, TikTok, YouTube и Ярмарки мастеров.
- [x] Bamboo Content Pack 1.0: versioned schema, request ID, строгий JSON/Pydantic import, runtime prompt, редакционные правила и встроенная справка.
- [x] Надёжная очередь публикаций: timezone, atomic claim/lease, retries, stuck recovery, независимые delivery.
- [x] Режим без developer app для VK, Instagram, Facebook, Pinterest, TikTok и YouTube: текст, media package, ZIP, прямой переход и подтверждение результата.
- [x] Browser-assisted публикация Ярмарки мастеров через штатную авторизацию пользователя, copy-ready JSON и bookmarklet без доступа к cookies.
- [x] Автоматические адаптеры Telegram, VK, Pinterest, Instagram, Facebook, TikTok и YouTube сохранены как опциональный расширенный режим.
- [x] OAuth: state/PKCE, encrypted token storage, refresh/revoke и health checks.
- [x] Переключение manual/automatic без удаления сохранённых OAuth-реквизитов.
- [x] Пошаговое подключение из UI: официальный API скрыт под progressive disclosure; показываются реальные требования business/professional account, app review/audit и HTTPS.
- [x] Автоматический выбор Pinterest Board / Meta Page+Instagram / VK wall в API-режиме.
- [x] Admin auth, Argon2, session/CSRF, security headers, upload signature validation.
- [x] Signed public media URLs и Meta webhook verification/idempotency storage.
- [x] Фото с телефона/HEIC, EXIF orientation, resize/JPEG, ffmpeg H.264/AAC MP4, upload progress, reorder/delete/cover.
- [x] Светлая адаптивная mobile/desktop оболочка, version marker, cache-busting assets и понятные статусы.
- [x] Backup/restore/update scripts и CI: Ruff, compileall, JavaScript syntax, Alembic, pytest, Docker build.

## Открытый P1
- [ ] UX публикаций: календарь week/month, duplicate/reschedule и окончательная accessibility/mobile ревизия — остаток #14.
- [ ] Media pipeline: хранение оригинала отдельно от delivery variants, metadata/poster/crop и provider-specific variants без ненужного upscale.
- [ ] Release engineering: clean-volume/upgrade/restore E2E, GHCR, Dependabot, rollback, branch protection и release checklist — #16 / PR #29.
- [ ] Browser assistant: поддерживаемые selector profiles с версионированием и управляемыми обновлениями при изменениях сторонних форм.
- [ ] Provider-specific подсказки ручного пакета: безопасные размеры/форматы, cover preview и предупреждения перед открытием площадки.

## После стабилизации
- [ ] Analytics и provider-specific метрики.
- [ ] Опциональное расширение браузерного помощника на другие площадки без стабильного публичного API — только локально, без передачи паролей/cookies и без автоматического окончательного submit.
- [ ] Многопользовательские роли и аудит действий, если Hub выйдет за пределы одной доверенной локальной установки.
