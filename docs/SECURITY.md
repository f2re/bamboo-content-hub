# Security model

- OAuth `state`: криптографически случайный, в БД хранится hash, TTL 10 минут, single-use.
- PKCE S256 используется для провайдеров, где flow это поддерживает.
- Access/refresh tokens шифруются Fernet-ключом, производным от `MASTER_KEY`; master key не хранится в БД.
- Signed media URL содержит asset id, expiration, nonce и HMAC SHA-256.
- Media path строится только из серверного `stored_filename`, дополнительно проверяется `resolve()` boundary.
- Meta webhook: HMAC `X-Hub-Signature-256`, идемпотентность по event id/digest.
- `.env`, DB и пользовательские media исключены из Git.

Текущий `TRUSTED_LAN=true` предназначен для LAN/VPN. До прямого открытия административного UI в интернет необходимо включить отдельную admin-auth/session/CSRF работу из P1 backlog.
