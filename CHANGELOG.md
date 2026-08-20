# Changelog

## Unreleased
- Расширен AI prompt: отдельные редакционные правила для Instagram, VK, Telegram, Pinterest, Facebook, TikTok, YouTube и Ярмарки мастеров.
- Добавлена встроенная справка по AI workflow, фактологическим ограничениям и импорту `Bamboo Content Pack`.
- README и `docs/AI_IMPORT.md` теперь содержат единый порядок работы, базовый промпт и карту полей площадок.
- Добавлен полноценный ручной редактор карточки изделия: цена, размеры, материалы, техника, уход, наличие и тексты всех поддерживаемых площадок.
- Улучшена медиатека: HEIC/HEIF detection, автоориентация и уменьшение изображений, нормализация видео через ffmpeg, прогресс загрузки, перестановка, обложка и удаление файлов.
- Экран AI preview показывает человеку предлагаемые факты, вопросы и предположения вместо обязательного просмотра сырого JSON.
- На странице подключений добавлены встроенные инструкции по токенам/OAuth, callback URL и официальные точки входа провайдеров.
- Технические статусы публикаций заменены понятными русскими состояниями; хэштеги нормализуются перед отправкой.

## 0.2.0
- Реальный local-first core: products, media, AI import, publications/deliveries.
- OAuth state/PKCE/exchange/refresh/revoke and encrypted credential storage.
- Signed public media URL and webhook event storage with Meta HMAC verification.
- Responsive PWA UI and deployment/update/backup tooling.
