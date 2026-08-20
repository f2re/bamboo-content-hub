import json

import pytest

from app.ai_pack import BambooContentPack, build_prompt, deep_fill, parse_pack


def pack(request_id="REQ-1"):
    return {
        "schema_version": "bamboo-content-pack/1.0",
        "request_id": request_id,
        "product": {"name": "Чашка", "price": {"amount": 3900, "currency": "RUB"}},
        "media": {
            "images": [{"id": "image_1", "role": "cover", "alt_text": "Чашка"}],
            "order": ["image_1"],
            "recommended_cover": "image_1",
        },
    }


def test_parse_markdown_json():
    parsed = parse_pack("```json\n" + json.dumps(pack(), ensure_ascii=False) + "\n```", "REQ-1")
    assert parsed.product.name == "Чашка"


def test_request_id_mismatch():
    with pytest.raises(ValueError):
        parse_pack(json.dumps(pack()), "OTHER")


def test_domain_validation():
    data = pack()
    data["product"]["price"]["amount"] = -1
    with pytest.raises(Exception):
        BambooContentPack.model_validate(data)


def test_deep_fill_human_wins():
    assert deep_fill(
        {"price": 4200, "name": ""}, {"price": 3900, "name": "Туман"}
    ) == {"price": 4200, "name": "Туман"}


def test_prompt_is_complete_runtime_contract_for_all_requested_channels():
    prompt = build_prompt(
        "REQ-2",
        2,
        {"name": "Чашка", "price": {"amount": 3900, "currency": "RUB"}},
        ["instagram", "telegram", "tiktok", "youtube", "livemaster"],
    )
    assert "ЗАДАЧА" in prompt
    assert "Контракт ответа:" in prompt
    assert "request_id: REQ-2" in prompt
    assert "image_1, image_2" in prompt
    assert "полный пакет со всеми корневыми разделами" in prompt
    assert "В media.images верни по одному элементу" in prompt
    assert "Не копируй один и тот же текст" in prompt
    assert "Instagram —" in prompt
    assert "Telegram —" in prompt
    assert "privacy всегда null" in prompt
    assert "YouTube —" in prompt
    assert "Ярмарка мастеров —" in prompt
    assert "Не выдумывай URL" in prompt
    assert '"amount": 3900' in prompt
    assert '"title": "BambooContentPack"' in prompt


def test_prompt_without_media_explicitly_requires_empty_media_section():
    prompt = build_prompt("REQ-3", 0, {"name": "Ваза"}, ["instagram"])
    assert "Технические идентификаторы вложений в порядке прикрепления: нет медиа" in prompt
    assert "media.images=[], media.order=[]" in prompt
