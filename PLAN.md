# План разработки

## 0.2.0 — текущая реализация
- [x] Local-first FastAPI app, SQLite WAL, Alembic.
- [x] Каталог изделий и медиатека.
- [x] Bamboo Content Pack 1.0, prompt generator, strict import/merge.
- [x] Публикации, delivery state, retry/idempotency foundation.
- [x] Demo, Telegram и ручной Livemaster connector.
- [x] OAuth framework: state, PKCE, exchange, encrypted token storage, refresh, revoke.
- [x] Signed media URLs и Meta webhook verification/idempotency storage.
- [x] Responsive PWA shell, design.md.
- [x] Docker Compose, migrations, backup/restore/update scripts, CI.

## Следующий backlog
### P1
- Реальные публикационные адаптеры Instagram/Facebook/Pinterest/VK/TikTok/YouTube поверх готового OAuth/core.
- Provider-specific webhook verifiers для подключаемых событий.
- UI редактирования всех структурированных характеристик и channel content.
- Локальная admin-auth (Argon2/session/CSRF) для установок вне доверенной LAN.

### P2
- ffmpeg/libvips media variants и capability matrix площадок.
- Календарь week/month, drag & drop, duplicate/reschedule.
- Browser companion для площадок без API.

### P3
- Analytics и provider-specific метрики после стабилизации публикаций.
