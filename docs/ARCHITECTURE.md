# Архитектура

Bamboo Content Hub — модульный монолит. Один FastAPI-процесс обслуживает UI/API и лёгкий SQL-backed scheduler. SQLite WAL используется по умолчанию; доменный слой не зависит от SQLite и может работать с PostgreSQL.

Поток данных: Product → MediaAsset → Bamboo Content Pack → ChannelContent → Publication → Delivery → Connector. Ошибка одного Delivery не меняет результат другого. `idempotency_key` защищает от повторной логической доставки.

OAuth отделён от коннекторов. `IntegrationAccount` хранит только зашифрованный blob credentials и метаданные. `OAuthState` хранит SHA-256 state и зашифрованный PKCE verifier. Публичная поверхность должна ограничиваться OAuth callback, webhooks и временными signed media URLs.
