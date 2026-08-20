# План разработки

## Текущее состояние
- [x] Local-first FastAPI app, SQLite WAL, Alembic, Docker Compose.
- [x] Каталог изделий, локальная медиатека и ручной редактор характеристик.
- [x] Редактирование отдельных текстов Instagram, VK, Telegram, Pinterest, Facebook, TikTok, YouTube и Ярмарки мастеров.
- [x] Bamboo Content Pack 1.0: versioned schema, request_id, строгий JSON/Pydantic import, полноценный runtime-промпт, редакционные правила и встроенная справка.
- [x] Критичные AI-факты защищены серверно подписанным подтверждением; provenance `user/ai/confirmed`, реальные media refs и schema sync проверяются тестами.
- [x] Надёжная очередь публикаций: timezone, atomic claim/lease, retries, stuck recovery, независимые delivery.
- [x] Автоматические адаптеры Telegram, VK, Pinterest, Instagram, Facebook, TikTok и YouTube; ручной экспорт Ярмарки мастеров.
- [x] OAuth: state/PKCE, encrypted token storage, refresh/revoke и health checks.
- [x] Пошаговое подключение из UI: официальные ссылки, callback, зашифрованные Client ID/Secret и автоматический выбор Pinterest Board / Meta Page+Instagram / VK wall без ручного поиска ID.
- [x] Preflight публикации: готовность подключения и совместимость выбранных медиа проверяются до создания внешней отправки.
- [x] Admin auth, Argon2, session/CSRF, security headers, upload signature validation.
- [x] Signed public media URLs и Meta webhook verification/idempotency storage.
- [x] Базовая оптимизация медиа: фото с телефона/HEIC, EXIF orientation, resize/JPEG, ffmpeg H.264/AAC MP4, upload progress, reorder/delete/cover.
- [x] Адаптивная mobile/desktop оболочка и понятные русские статусы публикаций.
- [x] Безопасная эксплуатация: collision-safe backup, validated restore, retrying smoke и automatic update rollback к исходному Git SHA + данным.
- [x] Release CI: Ruff, compileall, browser JS syntax, Bash syntax, Compose config, Alembic, pytest, Docker build и clean install/backup/restore/rollback lifecycle.
- [x] GHCR publication для `main`/`v*`, Dependabot и release checklist.

## Открытый P1
- [ ] AI import: расширить path-by-path diff и channel/domain sanitization/negative payload coverage — остаток #15.
- [ ] UX: календарь week/month, duplicate/reschedule и окончательная accessibility/mobile ревизия — остаток #14.
- [ ] Media pipeline: хранение оригинала отдельно от delivery variants, metadata/poster/crop и provider-specific variants без ненужного upscale.
- [ ] Release engineering: coverage threshold/report, branch protection/required CI, service worker/offline shell либо снятие PWA-обещания, финальные screenshots/release notes — остаток #16.
- [ ] PostgreSQL: либо реализовать и тестировать как отдельный backend, либо окончательно исключить из заявлений; текущий production path — SQLite.

## После стабилизации
- [ ] Analytics и provider-specific метрики.
- [ ] Browser companion только для площадок без стабильного публичного API, если он действительно потребуется.
