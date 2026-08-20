# Changelog

## 0.3.0

### Основной пользовательский поток
- Исправлено создание изделий при строгой Content Security Policy: удалены inline `onclick`, добавлен CSP-safe dialog controller и самостоятельный fallback `/new-product` без JavaScript.
- Для VK, Instagram, Facebook, Pinterest, TikTok и YouTube режим **«Без приложения»** стал основным: Bamboo готовит отдельный текст, выбранные медиа, ZIP и прямой переход на площадку.
- Ручные публикации получают состояние «Пакет готов»/«Ожидает публикации вручную» и завершаются явным подтверждением пользователя; ссылка на пост необязательна.
- TikTok и YouTube в ручном режиме не требуют API-only параметров creator info, privacy и consent: пользователь выбирает их в штатном интерфейсе площадки.

### Ярмарка мастеров
- Добавлен browser-assisted flow через обычную авторизацию пользователя на `livemaster.ru`.
- Пакет содержит copy-ready поля карточки и `browser-fill.json` со schema `bamboo-browser-fill/1`.
- Добавлена закладка-помощник **«Bamboo → заполнить Ярмарку»**, которая локально находит и заполняет пустые поля по label/name/placeholder/ARIA.
- Помощник не читает cookies, пароль, local storage и сетевые запросы, не вызывает внешние API, не перезаписывает непустые поля и не нажимает окончательную публикацию.
- Фото и видео остаются в ZIP/individual download: скрытый выбор локальных файлов браузером не используется.

### Подключения и прозрачность
- Официальная API-автоматизация сохранена как раскрываемый расширенный режим; существующие OAuth-подключения остаются совместимыми.
- В UI добавлены реальные предварительные требования: business/professional account, developer app, permissions, review/audit и HTTPS-домен — только когда они действительно нужны конкретному API.
- На странице подключений добавлена отдельная карточка Ярмарки мастеров «Через браузер».
- В левом нижнем углу показывается версия `v0.3.0 · без приложений`; добавлен endpoint `/health/version` и feature marker `manual-first-browser-assist`.
- Статические CSS/JS получают version query string, чтобы браузер не оставался на старой OAuth-first версии после обновления.

### ИИ и медиатека
- AI prompt формируется на лету для конкретного изделия: request ID, факты, media mapping `image_1...N`, правила площадок и актуальная JSON Schema.
- Критичные AI-факты защищены явным серверно подписанным подтверждением; сохраняется provenance `user / ai / confirmed`.
- Улучшена медиатека: HEIC/HEIF detection, автоориентация, уменьшение изображений, ffmpeg-нормализация видео, прогресс загрузки, перестановка, обложка и удаление.

### Интерфейс и эксплуатация
- Пользовательская оболочка переведена на принудительно светлую Apple-like систему с адаптивной двухколоночной структурой подключений и progressive disclosure.
- Добавлена проверка готовности площадок и совместимости медиа до фактической отправки.
- Исправлено самоблокирование `scripts/update.sh`: generated backups игнорируются Git, а реальные локальные изменения выводятся списком без автоматических `reset`/`clean`.
- CI проверяет Ruff, compileall, JavaScript syntax, Alembic, полный pytest и Docker build.

## 0.2.0
- Local-first core: products, media, AI import, publications/deliveries.
- OAuth state/PKCE/exchange/refresh/revoke and encrypted credential storage.
- Signed public media URL and webhook event storage with Meta HMAC verification.
- Responsive PWA UI and deployment/update/backup tooling.
