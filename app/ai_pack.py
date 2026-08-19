from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


def parse_pack(text: str, expected_request_id: str | None = None) -> BambooContentPack:
    pack = BambooContentPack.model_validate(extract_json(text))
    if expected_request_id and pack.request_id != expected_request_id:
        raise ValueError("request_id does not match this product draft")
    return pack


def deep_fill(existing: Any, incoming: Any) -> Any:
    """Human/current data wins; AI only fills empty values recursively."""
    if isinstance(existing, dict) and isinstance(incoming, dict):
        keys = set(existing) | set(incoming)
        return {key: deep_fill(existing.get(key), incoming.get(key)) for key in keys}
    if existing not in (None, "", [], {}):
        return existing
    return incoming


def build_prompt(request_id: str, image_count: int, known: dict, channels: list[str]) -> str:
    image_names = ", ".join(f"image_{i}" for i in range(1, image_count + 1)) or "нет изображений"
    schema = json.dumps(BambooContentPack.model_json_schema(), ensure_ascii=False, indent=2)
    known_json = json.dumps(known, ensure_ascii=False, indent=2)
    channel_text = ", ".join(channels)
    return f"""Ты — контент-редактор гончарной мастерской Bamboo Pottery.\n\nВерни ТОЛЬКО один валидный JSON без Markdown и пояснений.\nИспользуй schema_version bamboo-content-pack/1.0 и request_id {request_id}.\nФотографии идут в порядке прикрепления и называются: {image_names}.\nПодготовь отдельный вариант контента для площадок: {channel_text}.\n\nНикогда не придумывай цену, материал, размеры, объём, массу, состав глазури, режим обжига, food-safe, ПММ, СВЧ или наличие. Если факта нет — оставь null/пустое значение и добавь короткий вопрос в needs_confirmation. Визуальные признаки можно описывать как наблюдение; предположения перечисляй в assumptions. Тексты должны быть спокойными, естественными и без рекламных клише.\n\nИзвестные данные пользователя:\n{known_json}\n\nJSON Schema:\n{schema}\n"""
