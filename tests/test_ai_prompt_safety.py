from app.ai_pack import build_prompt


def test_prompt_does_not_expose_internal_provenance_metadata():
    prompt = build_prompt(
        "REQ-PROVENANCE",
        0,
        {
            "name": "Чашка",
            "price": {"amount": 3200, "currency": "RUB"},
            "_provenance": {"product.price.amount": "confirmed"},
        },
        ["telegram"],
    )

    known_section = prompt.split("Известные данные пользователя:", 1)[1].split("JSON Schema:", 1)[0]
    assert '"price"' in known_section
    assert "_provenance" not in known_section
