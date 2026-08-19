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
from .models import DeliveryStatus, IntegrationAccount, MediaAsset, Product, Publication, PublicationStatus, WebhookEvent
from .oauth import begin_oauth, exchange_code, refresh_account, revoke_account
from .publisher import process_delivery
from .security import (
    CredentialCipher,
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
                        logger.exception("Delivery processing failed", extra={"delivery_id": delivery.id})
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
    publications = list(db.scalars(select(Publication).order_by(Publication.created_at.desc()).limit(8)))
    return templates.TemplateResponse(request, "dashboard.html", {"products": products, "publications": publications})


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


@app.post("/products/{product_id}/media")
async def upload_media(product_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    start = len(product.media)
    try:
        for idx, upload in enumerate(files):
            await save_upload(db, settings, product, upload, start + idx)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.get("/products/{product_id}/ai", response_class=HTMLResponse)
def ai_page(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    request_id = product.ai_request_id or f"BCP-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    if not product.ai_request_id:
        product.ai_request_id = request_id
        db.commit()
    known = {"name": product.name, "sku": product.sku, "product_type": product.product_type, **(product.facts or {})}
    prompt = build_prompt(request_id, len(product.media), known, ["instagram", "vk", "telegram", "pinterest", "facebook", "tiktok", "youtube", "livemaster"])
    return templates.TemplateResponse(request, "ai.html", {"product": product, "prompt": prompt})


@app.post("/api/products/{product_id}/ai/preview")
async def ai_preview(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = product_or_404(db, product_id)
    body = await request.json()
    try:
        pack = parse_pack(body.get("text", ""), product.ai_request_id)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "pack": pack.model_dump(), "needs_confirmation": [x.model_dump() for x in pack.needs_confirmation], "assumptions": [x.model_dump() for x in pack.assumptions]}


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
    products = {p.id: p for p in db.scalars(select(Product))}
    return templates.TemplateResponse(request, "publications.html", {"publications": publications, "products": products})


@app.post("/products/{product_id}/publications")
def publication_create(
    product_id: str,
    channels: list[str] = Form(default=[]),
    media_ids: list[str] = Form(default=[]),
    scheduled_at: str = Form(default=""),
    action: str = Form(default="draft"),
    db: Session = Depends(get_db),
):
    product = product_or_404(db, product_id)
    try:
        when = parse_local_datetime(scheduled_at, settings.app_timezone)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    publication = create_publication(db, product, channels or ["demo"], media_ids, when)
    if action == "publish":
        publication.status = PublicationStatus.scheduled.value
        publication.scheduled_at = datetime.now(UTC)
        db.commit()
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
    accounts = {a.provider: a for a in db.scalars(select(IntegrationAccount))}
    providers = ["google", "pinterest", "tiktok", "meta", "vk", "telegram"]
    return templates.TemplateResponse(request, "connections.html", {"accounts": accounts, "providers": providers})


@app.post("/api/integrations/telegram")
async def save_telegram(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    if not body.get("bot_token") or not body.get("chat_id"):
        raise HTTPException(422, "Нужны bot_token и chat_id")
    account = db.scalar(select(IntegrationAccount).where(IntegrationAccount.provider == "telegram", IntegrationAccount.account_key == "default"))
    if not account:
        account = IntegrationAccount(provider="telegram", account_key="default")
        db.add(account)
    account.encrypted_credentials = CredentialCipher(settings).encrypt_json({"bot_token": body["bot_token"], "chat_id": body["chat_id"]})
    account.status = "connected"
    db.commit()
    return {"ok": True}


@app.get("/api/oauth/{provider}/start")
def oauth_start(provider: str, db: Session = Depends(get_db)):
    try:
        url = begin_oauth(db, settings, provider)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(url, status_code=303)


@app.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
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
    account = db.scalar(select(IntegrationAccount).where(IntegrationAccount.provider == provider, IntegrationAccount.account_key == "default"))
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
    return FileResponse(safe_media_path(settings.media_dir, asset.stored_filename), media_type=asset.mime_type)


@app.get("/api/media/{asset_id}/public-url")
def public_media_url(asset_id: str, db: Session = Depends(get_db)):
    if not db.get(MediaAsset, asset_id):
        raise HTTPException(404)
    token = sign_media_token(settings, asset_id)
    return {"url": f"{settings.app_base_url.rstrip('/')}/media/public/{token}", "ttl_seconds": settings.signed_media_ttl_seconds}


@app.get("/media/public/{token}")
def public_media(token: str, db: Session = Depends(get_db)):
    try:
        asset_id = verify_media_token(settings, token)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(404)
    return FileResponse(safe_media_path(settings.media_dir, asset.stored_filename), media_type=asset.mime_type)


@app.get("/webhooks/meta")
def meta_webhook_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and settings.webhook_verify_token and hmac.compare_digest(token or "", settings.webhook_verify_token):
        return HTMLResponse(challenge or "")
    raise HTTPException(403)


@app.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413)
    if provider == "meta" and settings.meta_webhook_secret:
        supplied = request.headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(settings.meta_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(403, "invalid webhook signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "invalid JSON") from exc
    external_id = request.headers.get("x-event-id") or hashlib.sha256(raw).hexdigest()
    event = WebhookEvent(provider=provider, external_event_id=external_id, payload=payload)
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
