from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .application import app, templates

APP_RELEASE = "0.3.0"
FEATURE_MARKER = "manual-first-browser-assist"

# Keep API metadata, cache-busting and the visible build marker synchronized.
app.version = APP_RELEASE
templates.env.globals["app_release"] = APP_RELEASE
templates.env.globals["feature_marker"] = FEATURE_MARKER

router = APIRouter()


@router.get("/new-product", response_class=HTMLResponse)
def new_product_page(request: Request):
    """JS-independent fallback for creating an item under a strict CSP."""
    return templates.TemplateResponse(request, "product_new.html", {})


@router.get("/health/version")
def health_version():
    return {
        "version": APP_RELEASE,
        "feature_marker": FEATURE_MARKER,
        "features": [
            "manual-first publishing",
            "browser-assisted Livemaster package",
            "strict-CSP product creation",
        ],
    }
