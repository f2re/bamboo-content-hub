# План разработки

## Текущее состояние
- [x] Local-first FastAPI app, SQLite WAL, Alembic, Docker Compose.
- [x] Каталог изделий, локальная медиатека и ручной редактор характеристик.
- [x] Редактирование отдельных текстов Instagram, VK, Telegram, Pinterest, Facebook, TikTok, YouTube и Ярмарки мастеров.
- [x] Bamboo Content Pack 1.0: versioned schema, request_id, строгий JSON/Pydantic import, полноценный runtime-промпт, редакционные правила и встроенная справка.
- [x] Надёжная очередь публикаций: timezone, atomic claim/lease, retries, stuck recovery, независимые delivery.
- [x] Режим без developer app для VK, Instagram, Facebook, Pinterest, TikTok и YouTube: готовый текст, media package, ZIP, прямой переход и ручное подтверждение результата.
- [x] Автоматические адаптеры Telegram, VK, Pinterest, Instagram, Facebook, TikTok и YouTube сохранены как опциональный расширенный режим; ручной экспорт Ярмарки мастеров.
- [x] OAuth: state/PKCE, encrypted token storage, refresh/revoke и health checks.
- [x] Переключение manual/automatic без удаления сохранённых OAuth-реквизитов; существующие автоматические подключения остаются совместимыми.
- [x] Пошаговое подключение из UI: официальный API скрыт под progressive disclosure, автоматический выбор Pinterest Board / Meta Page+Instagram / VK wall без ручного поиска ID.
- [x] Admin auth, Argon2, session/CSRF, security headers, upload signature validation.
- [x] Signed public media URLs и Meta webhook verification/idempotency storage.
- [x] Базовая оптимизация медиа: фото с телефона/HEIC, EXIF orientation, resize/JPEG, ffmpeg H.264/AAC MP4, upload progress, reorder/delete/cover.
- [x] Адаптивная mobile/desktop оболочка и понятные русские статусы публикаций.
- [x] Backup/restore/update scripts и CI: Ruff, compileall, JavaScript syntax, Alembic, pytest, Docker build.

## Открытый P1
- [ ] UX: календарь week/month, duplicate/reschedule и окончательная accessibility/mobile ревизия — остаток #14.
- [ ] Media pipeline: хранение оригинала отдельно от delivery variants, metadata/poster/crop и provider-specific variants без ненужного upscale.
- [ ] Release engineering: coverage, clean-volume/upgrade/restore E2E, GHCR, Dependabot, rollback, branch protection и release checklist — #16.
- [ ] Ручные пакеты: provider-specific подсказки по формату/ограничениям и опциональный локальный browser companion без доступа к cookies.

## После стабилизации
- [ ] Analytics и provider-specific метрики.
- [ ] Автоматизированный browser companion только для площадок без стабильного публичного API, если он действительно потребуется; пароли и cookies в Bamboo не хранить.
