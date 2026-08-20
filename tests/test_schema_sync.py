import json
from pathlib import Path

from app.ai_pack import BambooContentPack


def test_checked_in_content_pack_schema_matches_pydantic_model():
    checked_in = json.loads(Path("spec/bamboo-content-pack-1.0.schema.json").read_text())
    generated = BambooContentPack.model_json_schema()

    assert checked_in == generated
