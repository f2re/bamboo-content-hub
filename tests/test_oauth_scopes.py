from app.config import get_settings
from app.oauth import provider_registry


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


def test_google_oauth_scopes_cover_upload_health_and_status():
    scopes = set(provider_registry(get_settings())["google"].scopes)

    assert YOUTUBE_UPLOAD_SCOPE in scopes
    assert YOUTUBE_READ_SCOPE in scopes
