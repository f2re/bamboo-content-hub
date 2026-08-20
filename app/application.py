from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ai_pack import build_prompt, parse_pack
from .config import get_settings
from .db import SessionLocal, get_db
from .integrations.service import (
    CHANNELS_BY_PROVIDER,
    channel_health,
    merge_provider_config,
    provider_config_fields,
    public_provider_config,
)
from .models import (
    DeliveryStatus,
    IntegrationAccount,
    MediaAsset,
    Product,
    Publication,
    PublicationStatus,
    WebhookEvent,
)
from .oauth import begin_oauth, exchange_code, refresh_account, revoke_account
from .publisher import process_delivery
from .security import (
    create_session_token,
    safe_media_path,
    sign_media_token,
    verify_admin_password,
    verify_media_token,
)
from .services import (
    apply_ai_pack,
    create_publication,
    due_deliveries,
    format_local_datetime,
    parse_local_datetime,
    save_upload,
)
from .web_security import SESSION_COOKIE, SecurityMiddleware

settings = get_settings()
logger = logging.getLogger("bamboo.scheduler")

PROVIDER_LABELS = {
    "google": "Google / YouTube",
    "pinterest": "Pinterest",
    "tiktok": "TikTok",
    "meta": "Meta / Instagram / Facebook",
    "vk": "VK",
    "telegram": "Telegram",
}
CHANNEL_LABELS = {
    "youtube": "YouTube",
    "pinterest": "Pinterest",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "vk": "VK",
    "telegram": "Telegram",
}
STATUS_LABELS = {
    "connected": "Подключено",
    "configured": "Настроено частично",
    "reauthorize": "Нужно переподключить",
    "error": "Ошибка подключения",
}


def _template_context(request: Request) -> dict:
    return {
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "auth_enabled": not settings.trusted_lan,
    }


templates = Jinja2Templates(directory="templates", context_processors=[_template_context])


def _local_datetime(value: datetime | None) -> str:
    return format_local_datetime(value, settings.app_timezone)


def _safe_next_path(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _optional_float(value: str) -> float | None:
    value = value.strip().replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise HTTPException(422, f"Некорректное число: {value}") from exc


def _text_list(value: str) -> list[str]:
    if not value.strip():
        return []
    return [item.strip().lstrip("#") for item in value.replace("\n", ",").split(",") if item.strip()]


def _tri_state(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"yes", "true", "1", "on"}:
        return True
    if normalized in {"no", "false", "0", "off"}:
        return False
    return None


def _normalize_media_order(product: Product) -> None:
    for index, asset in enumerate(sorted(product.media, key=lambda item: item.sort_order)):
        asset.sort_order = index


templates.env.filters["local_datetime"] = _local_datetime


async def scheduler_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                for delivery in due_deliveries(db):
                    try:
                        await process_delivery(db, settings, delivery)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Delivery processing failed",
                            extra={"delivery_id": delivery.id},
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler iteration failed")
        await asyncio.sleep(settings.scheduler_interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(scheduler_loop()) if settings.scheduler_enabled else None
    try:
        yield
    finally:
        if task:
            task.cancel()


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(SecurityMiddleware, settings=settings)
app.mount("/static", StaticFiles(directory="static"), name="static")


def product_or_404(db: Session, product_id: str) -> Product:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Изделие не найдено")
    return product


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if settings.trusted_lan:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next_path": _safe_next_path(next), "error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    password: str = Form(...),
    next: str = Form(default="/"),
):
    if settings.trusted_lan:
        return RedirectResponse("/", status_code=303)
    if not verify_admin_password(settings.admin_password_hash, password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next_path": _safe_next_path(next), "error": "Неверный пароль"},
            status_code=401,
        )
    session_token, _csrf = create_session_token(settings)
    response = RedirectResponse(_safe_next_path(next), status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/health/live")
def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    test_path = settings.media_dir / ".write-test"
    test_path.write_text("ok")
    test_path.unlink(missing_ok=True)
    return {"status": "ready"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    products = list(db.scalars(select(Product).order_by(Product.updated_at.desc()).limit(6)))
    publications = list(
        db.scalars(select(Publication).order_by(Publication.created_at.desc()).limit(8))
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"products": products, "publications": publications},
    )


@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request, db: Session = Depends(get_db)):
    products = list(db.scalars(select(Product).order_by(Product.updated_at.desc())))
    return templates.TemplateResponse(request, "products.html", {"products": products})


@app.post("/products")
def create_product(name: str = Form(...), db: Session = Depends(get_db)):
    product = Product(name=name.strip() or "Без названия")
    db.add(product)
    db.commit()
    return RedirectResponse(f"/products/{product.id}", status_code=303)


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_page(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    return templates.TemplateResponse(request, "product.html", {"product": product})


@app.post("/products/{product_id}")
def update_product(
    product_id: str,
    name: str = Form(...),
    product_type: str = Form(default=""),
    sku: str = Form(default=""),
    collection: str = Form(default=""),
    description: str = Form(default=""),
    price_amount: str = Form(default=""),
    price_currency: str = Form(default="RUB"),
    materials: str = Form(default=""),
    techniques: str = Form(default=""),
    glaze: str = Form(default=""),
    firing: str = Form(default=""),
    height_mm: str = Form(default=""),
    diameter_mm: str = Form(default=""),
    volume_ml: str = Form(default=""),
    weight_g: str = Form(default=""),
    dishwasher: str = Form(default="unknown"),
    microwave: str = Form(default="unknown"),
    food_safe: str = Form(default="unknown"),
    availability: str = Form(default=""),
    instagram_caption: str = Form(default=""),
    instagram_hashtags: str = Form(default=""),
    vk_text: str = Form(default=""),
    vk_hashtags: str = Form(default=""),
    telegram_text: str = Form(default=""),
    telegram_button_text: str = Form(default=""),
    telegram_button_url: str = Form(default=""),
    pinterest_title: str = Form(default=""),
    pinterest_description: str = Form(default=""),
    pinterest_keywords: str = Form(default=""),
    pinterest_destination_url: str = Form(default=""),
    facebook_text: str = Form(default=""),
    tiktok_caption: str = Form(default=""),
    tiktok_hashtags: str = Form(default=""),
    youtube_title: str = Form(default=""),
    youtube_description: str = Form(default=""),
    youtube_tags: str = Form(default=""),
    livemaster_title: str = Form(default=""),
    livemaster_short_description: str = Form(default=""),
    livemaster_description: str = Form(default=""),
    livemaster_keywords: str = Form(default=""),
    db: Session = Depends(get_db),
):
    product = product_or_404(db, product_id)
    product.name = name.strip() or "Без названия"
    product.product_type = product_type.strip() or None
    product.sku = sku.strip() or None
    product.collection = collection.strip() or None
    product.description = description.strip() or None

    facts = dict(product.facts or {})
    facts.update(
        {
            "price": {
                "amount": _optional_float(price_amount),
                "currency": price_currency.strip().upper() or "RUB",
            },
            "materials": _text_list(materials),
            "techniques": _text_list(techniques),
            "glaze": glaze.strip() or None,
            "firing": firing.strip() or None,
            "dimensions": {
                "height_mm": _optional_float(height_mm),
                "diameter_mm": _optional_float(diameter_mm),
                "volume_ml": _optional_float(volume_ml),
                "weight_g": _optional_float(weight_g),
            },
            "care": {
                "dishwasher": _tri_state(dishwasher),
                "microwave": _tri_state(microwave),
                "food_safe": _tri_state(food_safe),
            },
            "availability": availability.strip() or None,
        }
    )
    product.facts = facts

    channel_content = dict(product.channel_content or {})
    channel_content.update(
        {
            "instagram": {
                **dict(channel_content.get("instagram") or {}),
                "caption": instagram_caption.strip(),
                "hashtags": _text_list(instagram_hashtags),
            },
            "vk": {
                **dict(channel_content.get("vk") or {}),
                "text": vk_text.strip(),
                "hashtags": _text_list(vk_hashtags),
            },
            "telegram": {
                **dict(channel_content.get("telegram") or {}),
                "text": telegram_text.strip(),
                "button_text": telegram_button_text.strip(),
                "button_url": telegram_button_url.strip(),
            },
            "pinterest": {
                **dict(channel_content.get("pinterest") or {}),
                "title": pinterest_title.strip(),
                "description": pinterest_description.strip(),
                "keywords": _text_list(pinterest_keywords),
                "destination_url": pinterest_destination_url.strip(),
            },
            "facebook": {
                **dict(channel_content.get("facebook") or {}),
                "text": facebook_text.strip(),
            },
            "tiktok": {
                **dict(channel_content.get("tiktok") or {}),
                "caption": tiktok_caption.strip(),
                "hashtags": _text_list(tiktok_hashtags),
            },
            "youtube": {
                **dict(channel_content.get("youtube") or {}),
                "title": youtube_title.strip(),
                "description": youtube_description.strip(),
                "tags": _text_list(youtube_tags),
            },
            "livemaster": {
                **dict(channel_content.get("livemaster") or {}),
                "title": livemaster_title.strip(),
                "short_description": livemaster_short_description.strip(),
                "description": livemaster_description.strip(),
                "keywords": _text_list(livemaster_keywords),
            },
        }
    )
    product.channel_content = channel_content
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Такой артикул уже используется другим изделием") from exc
    return RedirectResponse(f"/products/{product_id}?saved=1", status_code=303)


@app.post("/products/{product_id}/media")
async def upload_media(
    product_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    product = product_or_404(db, product_id)
    start = len(product.media)
    try:
        for idx, upload in enumerate(files):
            await save_upload(db, settings, product, upload, start + idx)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.delete("/api/products/{product_id}/media/{asset_id}")
def delete_media(product_id: str, asset_id: str, db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    asset = db.get(MediaAsset, asset_id)
    if not asset or asset.product_id != product.id:
        raise HTTPException(404, "Медиафайл не найден")
    path = safe_media_path(settings.media_dir, asset.stored_filename)
    db.delete(asset)
    db.flush()
    _normalize_media_order(product)
    db.commit()
    path.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/products/{product_id}/media/order")
async def reorder_media(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    body = await request.json()
    ordered_ids = body.get("ids") if isinstance(body, dict) else None
    if not isinstance(ordered_ids, list) or not all(isinstance(item, str) for item in ordered_ids):
        raise HTTPException(422, "Передайте список media ids")
    current = {asset.id: asset for asset in product.media}
    if len(ordered_ids) != len(current) or set(ordered_ids) != set(current):
        raise HTTPException(422, "Порядок должен содержать все фотографии и видео изделия")
    for index, asset_id in enumerate(ordered_ids):
        current[asset_id].sort_order = index
    db.commit()
    return {"ok": True}


@app.get("/products/{product_id}/ai", response_class=HTMLResponse)
def ai_page(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    request_id = product.ai_request_id or (
        f"BCP-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    )
    if not product.ai_request_id:
        product.ai_request_id = request_id
        db.commit()
    known = {
        "name": product.name,
        "sku": product.sku,
        "product_type": product.product_type,
        **(product.facts or {}),
    }
    prompt = build_prompt(
        request_id,
        len(product.media),
        known,
        [
            "instagram",
            "vk",
            "telegram",
            "pinterest",
            "facebook",
            "tiktok",
            "youtube",
            "livemaster",
        ],
    )
    return templates.TemplateResponse(
        request,
        "ai.html",
        {"product": product, "prompt": prompt},
    )


@app.post("/api/products/{product_id}/ai/preview")
async def ai_preview(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    body = await request.json()
    try:
        pack = parse_pack(body.get("text", ""), product.ai_request_id)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "ok": True,
        "pack": pack.model_dump(),
        "needs_confirmation": [item.model_dump() for item in pack.needs_confirmation],
        "assumptions": [item.model_dump() for item in pack.assumptions],
    }


@app.post("/api/products/{product_id}/ai/import")
async def ai_import(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    body = await request.json()
    try:
        pack = parse_pack(body.get("text", ""), product.ai_request_id)
        apply_ai_pack(db, product, pack)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "redirect": f"/products/{product_id}"}


@app.get("/publications", response_class=HTMLResponse)
def publications_page(request: Request, db: Session = Depends(get_db)):
    publications = list(db.scalars(select(Publication).order_by(Publication.created_at.desc())))
    products = {product.id: product for product in db.scalars(select(Product))}
    return templates.TemplateResponse(
        request,
        "publications.html",
        {"publications": publications, "products": products},
    )


@app.post("/products/{product_id}/publications")
def publication_create(
    product_id: str,
    channels: list[str] = Form(default=[]),
    media_ids: list[str] = Form(default=[]),
    scheduled_at: str = Form(default=""),
    action: str = Form(default="draft"),
    tiktok_creator_checked: bool = Form(default=False),
    tiktok_title: str = Form(default=""),
    tiktok_caption: str = Form(default=""),
    tiktok_privacy_level: str = Form(default=""),
    tiktok_disable_comment: bool = Form(default=False),
    tiktok_disable_duet: bool = Form(default=False),
    tiktok_disable_stitch: bool = Form(default=False),
    tiktok_commercial_content_toggle: bool = Form(default=False),
    tiktok_brand_organic_toggle: bool = Form(default=False),
    tiktok_brand_content_toggle: bool = Form(default=False),
    tiktok_is_aigc: bool = Form(default=False),
    tiktok_auto_add_music: bool = Form(default=False),
    tiktok_direct_post_consent: bool = Form(default=False),
    youtube_title: str = Form(default=""),
    youtube_description: str = Form(default=""),
    youtube_privacy_status: str = Form(default=""),
    db: Session = Depends(get_db),
):
    product = product_or_404(db, product_id)
    selected_channels = list(dict.fromkeys(channels or ["demo"]))
    try:
        requested_time = parse_local_datetime(scheduled_at, settings.app_timezone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    selected_media = [item for item in product.media if item.id in set(media_ids)]
    overrides: dict[str, dict] = {}

    if "tiktok" in selected_channels:
        if not selected_media:
            raise HTTPException(422, "Для TikTok выберите фото или видео")
        if not tiktok_creator_checked:
            raise HTTPException(422, "Сначала обновите сведения о подключённом TikTok аккаунте")
        if not tiktok_privacy_level.strip():
            raise HTTPException(422, "Выберите видимость TikTok")
        if not tiktok_direct_post_consent:
            raise HTTPException(422, "Подтвердите отправку материалов в TikTok")
        if tiktok_commercial_content_toggle and not (
            tiktok_brand_organic_toggle or tiktok_brand_content_toggle
        ):
            raise HTTPException(
                422,
                "Для коммерческого контента выберите свой бренд, сторонний бренд или оба",
            )
        if not tiktok_commercial_content_toggle and (
            tiktok_brand_organic_toggle or tiktok_brand_content_toggle
        ):
            raise HTTPException(422, "Включите декларацию коммерческого контента TikTok")
        if tiktok_brand_content_toggle and tiktok_privacy_level == "SELF_ONLY":
            raise HTTPException(
                422,
                "Платное партнёрство TikTok нельзя публиковать с видимостью «Только я»",
            )
        current = dict((product.channel_content or {}).get("tiktok") or {})
        overrides["tiktok"] = {
            "title": tiktok_title.strip() or current.get("title", ""),
            "caption": tiktok_caption.strip() or current.get("caption", ""),
            "privacy_level": tiktok_privacy_level.strip(),
            "disable_comment": tiktok_disable_comment,
            "disable_duet": tiktok_disable_duet,
            "disable_stitch": tiktok_disable_stitch,
            "commercial_content_toggle": tiktok_commercial_content_toggle,
            "brand_organic_toggle": tiktok_brand_organic_toggle,
            "brand_content_toggle": tiktok_brand_content_toggle,
            "is_aigc": tiktok_is_aigc,
            "auto_add_music": tiktok_auto_add_music,
            "direct_post_consent": True,
        }

    if "youtube" in selected_channels:
        if len(selected_media) != 1 or selected_media[0].media_type != "video":
            raise HTTPException(422, "Для YouTube выберите ровно одно видео")
        current = dict((product.channel_content or {}).get("youtube") or {})
        effective_title = youtube_title.strip() or current.get("title") or product.name
        privacy = youtube_privacy_status.strip().lower()
        if not effective_title:
            raise HTTPException(422, "Укажите заголовок YouTube")
        if privacy not in {"private", "unlisted", "public"}:
            raise HTTPException(422, "Выберите видимость YouTube")
        overrides["youtube"] = {
            "title": effective_title,
            "description": youtube_description or current.get("description", ""),
            "tags": current.get("tags") or [],
            "privacy_status": privacy,
        }

    publish_at = requested_time or (datetime.now(UTC) if action == "publish" else None)
    try:
        create_publication(
            db,
            product,
            selected_channels,
            media_ids,
            publish_at,
            overrides,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/publications", status_code=303)


@app.post("/api/publications/{publication_id}/publish")
async def publication_publish(publication_id: str, db: Session = Depends(get_db)):
    publication = db.get(Publication, publication_id)
    if not publication:
        raise HTTPException(404)
    publication.status = PublicationStatus.scheduled.value
    publication.scheduled_at = datetime.now(UTC)
    for delivery in publication.deliveries:
        if delivery.status == DeliveryStatus.failed.value:
            delivery.status = DeliveryStatus.pending.value
            delivery.next_attempt_at = None
    db.commit()
    for delivery in publication.deliveries:
        if delivery.status in (
            DeliveryStatus.pending.value,
            DeliveryStatus.retry_wait.value,
            DeliveryStatus.processing.value,
        ):
            await process_delivery(db, settings, delivery)
    return {"ok": True}


@app.get("/connections", response_class=HTMLResponse)
def connections_page(request: Request, db: Session = Depends(get_db)):
    accounts = {account.provider: account for account in db.scalars(select(IntegrationAccount))}
    providers = ["google", "pinterest", "tiktok", "meta", "vk", "telegram"]
    integrations = []
    for provider in providers:
        account = accounts.get(provider)
        integrations.append(
            {
                "provider": provider,
                "label": PROVIDER_LABELS[provider],
                "account": account,
                "status_label": STATUS_LABELS.get(
                    account.status if account else "",
                    "Не подключено",
                ),
                "fields": provider_config_fields(provider),
                "config": public_provider_config(db, settings, provider),
                "channels": [
                    {"name": channel, "label": CHANNEL_LABELS.get(channel, channel)}
                    for channel in CHANNELS_BY_PROVIDER.get(provider, ())
                ],
            }
        )
    return templates.TemplateResponse(
        request,
        "connections.html",
        {"integrations": integrations, "app_base_url": settings.app_base_url.rstrip("/")},
    )


async def _save_integration_config(
    provider: str,
    request: Request,
    db: Session,
) -> dict:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Ожидался JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Ожидался JSON-объект")
    metadata = {item["name"]: item for item in provider_config_fields(provider)}
    normalized = dict(body)
    for name, field in metadata.items():
        if name in normalized and field.get("type") == "checkbox":
            normalized[name] = _bool_value(normalized[name])
    try:
        account = merge_provider_config(db, settings, provider, normalized)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "ok": True,
        "status": account.status,
        "config": public_provider_config(db, settings, provider),
    }


@app.post("/api/integrations/telegram")
async def save_telegram(request: Request, db: Session = Depends(get_db)):
    return await _save_integration_config("telegram", request, db)


@app.post("/api/integrations/{provider}/config")
async def integration_config(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
):
    return await _save_integration_config(provider, request, db)


@app.get("/api/integrations/{channel}/health")
async def integration_health(channel: str, db: Session = Depends(get_db)):
    return await channel_health(db, settings, channel)


@app.get("/api/oauth/{provider}/start")
def oauth_start(provider: str, db: Session = Depends(get_db)):
    try:
        url = begin_oauth(db, settings, provider)
    except ValueError as exc:
        provider_label = PROVIDER_LABELS.get(provider, provider)
        raise HTTPException(
            400,
            f"{provider_label}: сначала задайте Client ID/Secret приложения в .env по инструкции на экране подключений",
        ) from exc
    return RedirectResponse(url, status_code=303)


@app.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(f"/connections?error={error}", status_code=303)
    if not code or not state:
        raise HTTPException(400, "OAuth callback is missing code/state")
    try:
        await exchange_code(db, settings, provider, code, state)
    except Exception as exc:
        raise HTTPException(400, f"OAuth failed: {exc}") from exc
    return RedirectResponse("/connections?connected=1", status_code=303)


@app.post("/api/integrations/{provider}/refresh")
async def integration_refresh(provider: str, db: Session = Depends(get_db)):
    account = db.scalar(
        select(IntegrationAccount).where(
            IntegrationAccount.provider == provider,
            IntegrationAccount.account_key == "default",
        )
    )
    if not account:
        raise HTTPException(404)
    try:
        await refresh_account(db, settings, account)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "status": account.status}


@app.delete("/api/integrations/{provider}")
async def integration_delete(provider: str, db: Session = Depends(get_db)):
    await revoke_account(db, settings, provider)
    return {"ok": True}


@app.get("/media/{asset_id}")
def local_media(asset_id: str, db: Session = Depends(get_db)):
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(404)
    return FileResponse(
        safe_media_path(settings.media_dir, asset.stored_filename),
        media_type=asset.mime_type,
    )


@app.get("/api/media/{asset_id}/public-url")
def public_media_url(asset_id: str, db: Session = Depends(get_db)):
    if not db.get(MediaAsset, asset_id):
        raise HTTPException(404)
    token = sign_media_token(settings, asset_id)
    return {
        "url": f"{settings.app_base_url.rstrip('/')}/media/public/{token}",
        "ttl_seconds": settings.signed_media_ttl_seconds,
    }


@app.get("/media/public/{token}")
def public_media(token: str, db: Session = Depends(get_db)):
    try:
        asset_id = verify_media_token(settings, token)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(404)
    return FileResponse(
        safe_media_path(settings.media_dir, asset.stored_filename),
        media_type=asset.mime_type,
    )


@app.get("/webhooks/meta")
def meta_webhook_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if (
        mode == "subscribe"
        and settings.webhook_verify_token
        and hmac.compare_digest(token or "", settings.webhook_verify_token)
    ):
        return HTMLResponse(challenge or "")
    raise HTTPException(403)


@app.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413)
    if provider == "meta" and settings.meta_webhook_secret:
        supplied = request.headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(
            settings.meta_webhook_secret.encode(),
            raw,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(403, "invalid webhook signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "invalid JSON") from exc
    external_id = request.headers.get("x-event-id") or hashlib.sha256(raw).hexdigest()
    event = WebhookEvent(
        provider=provider,
        external_event_id=external_id,
        payload=payload,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return JSONResponse({"ok": True, "duplicate": True})
    event.processed_at = datetime.now(UTC)
    event.result = "stored"
    db.commit()
    return {"ok": True}
