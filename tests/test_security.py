import pytest
from app.config import get_settings
from app.security import CredentialCipher, sign_media_token, verify_media_token, safe_media_path

def test_cipher_roundtrip():
    c=CredentialCipher(get_settings());assert c.decrypt_json(c.encrypt_json({"access_token":"secret"}))["access_token"]=="secret"
def test_signed_media_roundtrip():
    s=get_settings();token=sign_media_token(s,"abc",ttl=60);assert verify_media_token(s,token)=="abc"
def test_signed_media_expired():
    s=get_settings();token=sign_media_token(s,"abc",ttl=-1)
    with pytest.raises(ValueError): verify_media_token(s,token)
def test_safe_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError): safe_media_path(tmp_path,"../x")
