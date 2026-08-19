# Security model

## Режимы доступа

По умолчанию `TRUSTED_LAN=true`: интерфейс рассчитан на доверенную LAN/VPN и не требует логина.

Для доступа через reverse proxy/Интернет:

1. задайте внешний `APP_BASE_URL=https://...`;
2. выполните `bash scripts/set-admin-password.sh`;
3. убедитесь, что `SECRET_KEY` и отдельный `MASTER_KEY` случайные и длиннее 32 символов;
4. установите `TRUSTED_LAN=false` и перезапустите сервис.

При небезопасной конфигурации public-mode приложение fail-closed и не стартует.

## Административный интерфейс

- пароль хранится только как Argon2 hash (`ADMIN_PASSWORD_HASH`);
- сессия подписана HMAC, HttpOnly, SameSite=Strict и получает Secure flag при HTTPS;
- смена Argon2 hash автоматически делает ранее выданные сессии недействительными;
- POST/PUT/PATCH/DELETE требуют same-origin `Origin`/`Referer` либо CSRF token;
- JavaScript API-вызовы автоматически передают `X-CSRF-Token`;
- login/OAuth/webhook endpoints имеют per-process rate limits;
- logout удаляет session cookie.

## HTTP hardening

Middleware выставляет CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, Referrer-Policy и Permissions-Policy. На HTTPS также включается HSTS.

## Секреты и OAuth

- OAuth `state`: криптографически случайный, в БД хранится hash, TTL 10 минут, single-use.
- PKCE S256 используется для провайдеров, где flow это поддерживает.
- Access/refresh tokens шифруются Fernet-ключом, производным от `MASTER_KEY`; master key не хранится в БД.
- `.env`, DB и пользовательские media исключены из Git.

## Медиа

- signed media URL содержит asset id, expiration, nonce и HMAC SHA-256;
- локальный путь строится только из серверного `stored_filename` и проверяется через `resolve()` boundary;
- upload не доверяет имени файла или browser `Content-Type`: формат определяется по сигнатуре;
- разрешены JPEG/PNG/GIF/WebP, MP4/QuickTime/WebM; SVG/HTML и неизвестные форматы отклоняются.

## Webhooks

Meta webhook проверяет HMAC `X-Hub-Signature-256`; события идемпотентны по event id/digest. Provider-specific verifier для остальных площадок должен быть реализован вместе с соответствующим publishing adapter, см. #11.
