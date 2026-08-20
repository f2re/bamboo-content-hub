from __future__ import annotations

from .application import app, settings
from .manual_publish import router as manual_publish_router
from .publication_overrides import install_publication_overrides

app.include_router(manual_publish_router)
install_publication_overrides(app)

__all__ = ["app", "settings"]
