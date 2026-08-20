from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .application import product_or_404, settings, templates
from .db import get_db
from .integrations.service import provider_connection_mode
from .services import create_publication, parse_local_datetime

router = APIRouter()


def _as_bool(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _value(form, name: str, default: str = "") -> str:
    value = form.get(name, default)
    return str(value or default)


@router.get("/products/{product_id}", response_class=HTMLResponse)
def product_page(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    product = product_or_404(db, product_id)
    manual_modes = {
        "instagram": provider_connection_mode(db, settings, "meta") == "manual",
        "facebook": provider_connection_mode(db, settings, "meta") == "manual",
        "pinterest": provider_connection_mode(db, settings, "pinterest") == "manual",
        "tiktok": provider_connection_mode(db, settings, "tiktok") == "manual",
        "youtube": provider_connection_mode(db, settings, "google") == "manual",
        "vk": provider_connection_mode(db, settings, "vk") == "manual",
    }
    return templates.TemplateResponse(
        request,
        "product.html",
        {"product": product, "manual_modes": manual_modes},
    )


@router.post("/products/{product_id}/publications")
async def publication_create(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    product = product_or_404(db, product_id)
    form = await request.form()
    selected_channels = list(dict.fromkeys(form.getlist("channels") or ["demo"]))
    media_ids = list(dict.fromkeys(form.getlist("media_ids")))
    action = _value(form, "action", "draft")

    try:
        requested_time = parse_local_datetime(
            _value(form, "scheduled_at"),
            settings.app_timezone,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    selected_media = [item for item in product.media if item.id in set(media_ids)]
    overrides: dict[str, dict] = {}

    tiktok_manual = provider_connection_mode(db, settings, "tiktok") == "manual"
    if "tiktok" in selected_channels:
        if not selected_media:
            raise HTTPException(422, "Для TikTok выберите фото или видео")
        if not tiktok_manual:
            creator_checked = _as_bool(form.get("tiktok_creator_checked"))
            privacy = _value(form, "tiktok_privacy_level").strip()
            consent = _as_bool(form.get("tiktok_direct_post_consent"))
            commercial = _as_bool(form.get("tiktok_commercial_content_toggle"))
            own_brand = _as_bool(form.get("tiktok_brand_organic_toggle"))
            branded = _as_bool(form.get("tiktok_brand_content_toggle"))
            if not creator_checked:
                raise HTTPException(
                    422,
                    "Сначала обновите сведения о подключённом TikTok аккаунте",
                )
            if not privacy:
                raise HTTPException(422, "Выберите видимость TikTok")
            if not consent:
                raise HTTPException(422, "Подтвердите отправку материалов в TikTok")
            if commercial and not (own_brand or branded):
                raise HTTPException(
                    422,
                    "Для коммерческого контента выберите свой бренд, сторонний бренд или оба",
                )
            if not commercial and (own_brand or branded):
                raise HTTPException(422, "Включите декларацию коммерческого контента TikTok")
            if branded and privacy == "SELF_ONLY":
                raise HTTPException(
                    422,
                    "Платное партнёрство TikTok нельзя публиковать с видимостью «Только я»",
                )
            current = dict((product.channel_content or {}).get("tiktok") or {})
            overrides["tiktok"] = {
                "title": _value(form, "tiktok_title").strip() or current.get("title", ""),
                "caption": _value(form, "tiktok_caption").strip()
                or current.get("caption", ""),
                "privacy_level": privacy,
                "disable_comment": _as_bool(form.get("tiktok_disable_comment")),
                "disable_duet": _as_bool(form.get("tiktok_disable_duet")),
                "disable_stitch": _as_bool(form.get("tiktok_disable_stitch")),
                "commercial_content_toggle": commercial,
                "brand_organic_toggle": own_brand,
                "brand_content_toggle": branded,
                "is_aigc": _as_bool(form.get("tiktok_is_aigc")),
                "auto_add_music": _as_bool(form.get("tiktok_auto_add_music")),
                "direct_post_consent": True,
            }

    youtube_manual = provider_connection_mode(db, settings, "google") == "manual"
    if "youtube" in selected_channels:
        if len(selected_media) != 1 or selected_media[0].media_type != "video":
            raise HTTPException(422, "Для YouTube выберите ровно одно видео")
        current = dict((product.channel_content or {}).get("youtube") or {})
        title = _value(form, "youtube_title").strip() or current.get("title") or product.name
        description = _value(form, "youtube_description") or current.get("description", "")
        values = {
            "title": title,
            "description": description,
            "tags": current.get("tags") or [],
        }
        if not youtube_manual:
            privacy = _value(form, "youtube_privacy_status").strip().lower()
            if privacy not in {"private", "unlisted", "public"}:
                raise HTTPException(422, "Выберите видимость YouTube")
            values["privacy_status"] = privacy
        overrides["youtube"] = values

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


def _remove_route(app, path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", None) or set())
        )
    ]


def install_publication_overrides(app) -> None:
    _remove_route(app, "/products/{product_id}", "GET")
    _remove_route(app, "/products/{product_id}/publications", "POST")
    app.include_router(router)
