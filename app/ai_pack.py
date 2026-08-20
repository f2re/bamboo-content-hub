from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import get_settings


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Price(StrictModel):
    amount: float | None = Field(default=None, ge=0, le=10_000_000)
    currency: str = "RUB"


class Dimensions(StrictModel):
    height_mm: float | None = Field(default=None, gt=0, lt=2000)
    diameter_mm: float | None = Field(default=None, gt=0, lt=2000)
    volume_ml: float | None = Field(default=None, gt=0, lt=10000)
    weight_g: float | None = Field(default=None, gt=0, lt=100000)


class Care(StrictModel):
    dishwasher: bool | None = None
    microwave: bool | None = None
    food_safe: bool | None = None


class ProductPack(StrictModel):
    name: str | None = None
    product_type: str | None = None
    collection: str | None = None
    sku: str | None = None
    price: Price = Field(default_factory=Price)
    materials: list[str] = Field(default_factory=list)
    techniques: list[str] = Field(default_factory=list)
    glaze: str | None = None
    firing: str | None = None
    dimensions: Dimensions = Field(default_factory=Dimensions)
    care: Care = Field(default_factory=Care)
    availability: str | None = None


class Visual(StrictModel):
    summary: str = ""
    colors: list[str] = Field(default_factory=list)
    textures: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)
    distinctive_features: list[str] = Field(default_factory=list)


class Content(StrictModel):
    headline: str = ""
    short_description: str = ""
    full_description: str = ""
    story: str = ""
    call_to_action: str = ""


class Instagram(StrictModel):
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)


class VK(StrictModel):
    text: str = ""
    hashtags: list[str] = Field(default_factory=list)


class Telegram(StrictModel):
    text: str = ""
    button_text: str = ""
    button_url: str = ""


class Pinterest(StrictModel):
    title: str = ""
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    board_suggestion: str = ""
    destination_url: str = ""


class Facebook(StrictModel):
    text: str = ""


class TikTok(StrictModel):
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    privacy: str | None = None


class YouTube(StrictModel):
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class Livemaster(StrictModel):
    title: str = ""
    short_description: str = ""
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    category_suggestion: str = ""


class Channels(StrictModel):
    instagram: Instagram = Field(default_factory=Instagram)
    vk: VK = Field(default_factory=VK)
    telegram: Telegram = Field(default_factory=Telegram)
    pinterest: Pinterest = Field(default_factory=Pinterest)
    facebook: Facebook = Field(default_factory=Facebook)
    tiktok: TikTok = Field(default_factory=TikTok)
    youtube: YouTube = Field(default_factory=YouTube)
    livemaster: Livemaster = Field(default_factory=Livemaster)


class MediaImage(StrictModel):
    id: str = Field(pattern=r"^image_[1-9][0-9]*$")
    role: Literal["cover", "product", "detail", "lifestyle", "process", "packaging", "other"] = "other"
    alt_text: str = ""


class Media(StrictModel):
    recommended_cover: str | None = None
    order: list[str] = Field(default_factory=list)
    images: list[MediaImage] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_refs(self):
        ids = {item.id for item in self.images}
        refs = set(self.order)
        if self.recommended_cover:
            refs.add(self.recommended_cover)
        unknown = refs - ids
        if unknown:
            raise ValueError(f"unknown media ids: {', '.join(sorted(unknown))}")
        return self


class Confirmation(StrictModel):
    path: str
    question: str
    value: Any = None
    proof: str | None = None
    confirmed: bool = False


class Assumption(StrictModel):
    path: str
    value: Any
    basis: str


class BambooContentPack(StrictModel):
    schema_version: Literal["bamboo-content-pack/1.0"]
    request_id: str
    language: str = "ru-RU"
    product: ProductPack = Field(default_factory=ProductPack)
    visual: Visual = Field(default_factory=Visual)
    content: Content = Field(default_factory=Content)
    channels: Channels = Field(default_factory=Channels)
    media: Media = Field(default_factory=Media)
    needs_confirmation: list[Confirmation] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)


EDITORIAL_GUIDE = """Правила подготовки контента:
1. Считай известные данные пользователя источником истины. По вложенным медиа описывай только то, что действительно видно или слышно.
2. Никогда не придумывай цену, материал, размеры, объём, массу, состав глазури, режим обжига, food-safe, ПММ, СВЧ, наличие, сроки, скидки, ссылки или условия доставки. Неизвестное оставляй null/пустым и добавляй короткий вопрос в needs_confirmation.
3. Визуальные наблюдения можно записывать в visual. Любое предположение, которое нельзя считать установленным фактом, перечисляй в assumptions и не подавай его как факт в рекламном тексте.
4. Сформируй общий content и отдельный, реально адаптированный текст для каждой запрошенной площадки. Не копируй один и тот же текст во все каналы.
5. Тон Bamboo Pottery: спокойный, тёплый, человеческий, предметный. Без канцелярита, навязчивых продаж и клише вроде «уникальный», «идеальный», «премиальный», «успей купить», если это не подтверждённая часть исходных данных.
6. Сохраняй естественный русский язык, короткие абзацы и конкретику. Не добавляй Markdown вокруг ответа.
7. В hashtags записывай готовые хэштеги с символом #. В keywords и tags записывай слова/фразы без #.
8. Не выдумывай URL. button_url и destination_url заполняй только если ссылка дана во входных данных; иначе оставляй пустую строку.
9. Параметры публикации и согласия, которые должен выбрать человек, не угадывай. В частности, channels.tiktok.privacy оставляй null.
10. Для media используй только переданные идентификаторы image_1...N; не создавай несуществующие ссылки. alt_text должен кратко и фактически описывать медиа для доступности.
11. Поля needs_confirmation[].value/proof/confirmed служебные: никогда не заполняй value/proof и всегда оставляй confirmed=false. Их добавляет Bamboo Content Hub после проверки ответа."""


CHANNEL_GUIDE = {
    "instagram": "Instagram — caption: живой текст о предмете/процессе с удобными абзацами; hashtags: небольшой набор точных тематических хэштегов без спама.",
    "vk": "VK — text: более информативная версия с понятным описанием изделия, деталей и уместным призывом; hashtags: только релевантные.",
    "telegram": "Telegram — text: коротко и по делу, как сообщение мастерской подписчикам; button_text/button_url только при наличии реальной ссылки.",
    "pinterest": "Pinterest — title и description: поисково-понятные и конкретные; keywords без #; board_suggestion только как рекомендация; destination_url только из известных данных.",
    "facebook": "Facebook — text: естественный самостоятельный пост, допускающий небольшую историю изделия или процесса без дублирования Instagram слово в слово.",
    "tiktok": "TikTok — caption: короткая подпись с ясным первым смысловым акцентом; hashtags: несколько точных; privacy всегда null — видимость и коммерческие декларации выбирает человек перед публикацией.",
    "youtube": "YouTube — title: конкретный заголовок; description: фактическое описание изделия/процесса; tags без #. Не утверждай, что в видео показано то, чего нельзя подтвердить по переданному медиа.",
    "livemaster": "Ярмарка мастеров — title, short_description и description: полноценная карточка изделия на основе подтверждённых фактов; keywords без #; category_suggestion только как рекомендация.",
}

CRITICAL_CONFIRMATION_FIELDS: dict[str, str] = {
    "price.amount": "цену",
    "materials": "материалы",
    "glaze": "глазурь",
    "firing": "режим обжига",
    "dimensions.height_mm": "высоту",
    "dimensions.diameter_mm": "диаметр",
    "dimensions.volume_ml": "объём",
    "dimensions.weight_g": "массу",
    "care.dishwasher": "возможность мыть в посудомоечной машине",
    "care.microwave": "возможность использовать в микроволновой печи",
    "care.food_safe": "безопасность контакта с пищей",
    "availability": "наличие",
}


def extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        raise ValueError("JSON object not found")
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise ValueError("root JSON value must be an object")
    return obj


def _nested_get(data: dict, path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _product_path_set(product: ProductPack, path: str, value: Any) -> None:
    current: Any = product
    parts = path.split(".")
    for part in parts[:-1]:
        current = getattr(current, part)
    setattr(current, parts[-1], value)


def _empty_value(value: Any) -> Any:
    return [] if isinstance(value, list) else None


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _display_confirmation_value(value: Any) -> str:
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _confirmation_proof(request_id: str, path: str, value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = f"{request_id}\n{path}\n{canonical}".encode()
    return hmac.new(get_settings().secret_key.encode(), payload, hashlib.sha256).hexdigest()


def _protect_critical_confirmations(pack: BambooContentPack) -> BambooContentPack:
    incoming = pack.product.model_dump()
    by_path = {item.path: item for item in pack.needs_confirmation}
    for relative_path, label in CRITICAL_CONFIRMATION_FIELDS.items():
        path = f"product.{relative_path}"
        model_value = _nested_get(incoming, relative_path)
        item = by_path.get(path)

        # A value returned from a previous preview is accepted only with the server proof.
        if item and item.proof and _has_value(item.value):
            expected = _confirmation_proof(pack.request_id, path, item.value)
            if hmac.compare_digest(item.proof, expected):
                if item.confirmed:
                    _product_path_set(pack.product, relative_path, item.value)
                else:
                    _product_path_set(pack.product, relative_path, _empty_value(item.value))
                continue

        if not _has_value(model_value):
            continue

        proof = _confirmation_proof(pack.request_id, path, model_value)
        question = f"Подтвердите {label}: {_display_confirmation_value(model_value)}"
        if item:
            item.question = question
            item.value = model_value
            item.proof = proof
            item.confirmed = False
        else:
            item = Confirmation(
                path=path,
                question=question,
                value=model_value,
                proof=proof,
                confirmed=False,
            )
            pack.needs_confirmation.append(item)
            by_path[path] = item
        _product_path_set(pack.product, relative_path, _empty_value(model_value))
    return pack


def parse_pack(text: str, expected_request_id: str | None = None) -> BambooContentPack:
    pack = BambooContentPack.model_validate(extract_json(text))
    if expected_request_id and pack.request_id != expected_request_id:
        raise ValueError("request_id does not match this product draft")
    return _protect_critical_confirmations(pack)


def deep_fill(existing: Any, incoming: Any) -> Any:
    """Human/current data wins; AI only fills empty values recursively."""
    if isinstance(existing, dict) and isinstance(incoming, dict):
        keys = set(existing) | set(incoming)
        return {key: deep_fill(existing.get(key), incoming.get(key)) for key in keys}
    if existing not in (None, "", [], {}):
        return existing
    return incoming


def build_prompt(request_id: str, image_count: int, known: dict, channels: list[str]) -> str:
    image_names = ", ".join(f"image_{i}" for i in range(1, image_count + 1)) or "нет медиа"
    schema = json.dumps(BambooContentPack.model_json_schema(), ensure_ascii=False, indent=2)
    known_json = json.dumps(known, ensure_ascii=False, indent=2)
    channel_text = ", ".join(channels)
    channel_rules = "\n".join(
        f"- {CHANNEL_GUIDE.get(channel, f'{channel} — подготовь отдельный вариант по назначению площадки.')}"
        for channel in channels
    )
    return f"""Ты — контент-редактор гончарной мастерской Bamboo Pottery.

Верни ТОЛЬКО один валидный JSON без Markdown и пояснений.
Используй schema_version bamboo-content-pack/1.0 и request_id {request_id}.
Медиа идут в порядке прикрепления и внутри схемы называются: {image_names}.
Подготовь отдельный вариант контента для площадок: {channel_text}.

{EDITORIAL_GUIDE}

Требования по площадкам:
{channel_rules}

Известные данные пользователя:
{known_json}

JSON Schema:
{schema}
"""
