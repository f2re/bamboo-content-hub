from __future__ import annotations

import httpx

PINTEREST_API = "https://api.pinterest.com/v5"
META_GRAPH = "https://graph.facebook.com/v23.0"
VK_API = "https://api.vk.com/method"
VK_API_VERSION = "5.199"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def discover_target_choices(provider: str, config: dict) -> dict | None:
    """Return human-selectable publish targets when OAuth works but a target ID is missing."""
    token = str(config.get("access_token") or "")
    if not token:
        return None

    if provider == "pinterest" and not config.get("board_id"):
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.get(
                    f"{PINTEREST_API}/boards",
                    headers=_bearer(token),
                    params={"page_size": 100},
                )
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                return {
                    "ok": False,
                    "message": f"Не удалось получить доски Pinterest: {type(exc).__name__}",
                    "details": {},
                }
        items = body.get("items") if isinstance(body, dict) else []
        choices = [
            {
                "label": str(item.get("name") or item.get("id") or "Доска Pinterest"),
                "values": {"board_id": str(item.get("id"))},
            }
            for item in (items or [])
            if isinstance(item, dict) and item.get("id")
        ]
        return {
            "ok": True,
            "message": (
                "Pinterest подключён. Выберите доску — ID подставится автоматически."
                if choices
                else "Pinterest подключён, но досок не найдено. Создайте доску и повторите поиск."
            ),
            "details": {"choices": choices, "choice_kind": "Доска Pinterest"},
        }

    if provider == "meta" and not config.get("facebook_page_id"):
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.get(
                    f"{META_GRAPH}/me/accounts",
                    headers=_bearer(token),
                    params={"fields": "id,name,instagram_business_account"},
                )
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                return {
                    "ok": False,
                    "message": f"Не удалось получить страницы Meta: {type(exc).__name__}",
                    "details": {},
                }
        pages = body.get("data") if isinstance(body, dict) else []
        choices = []
        for page in pages or []:
            if not isinstance(page, dict) or not page.get("id"):
                continue
            instagram = page.get("instagram_business_account")
            instagram_id = instagram.get("id") if isinstance(instagram, dict) else ""
            label = str(page.get("name") or page["id"])
            if instagram_id:
                label += " · Instagram подключён"
            choices.append(
                {
                    "label": label,
                    "values": {
                        "facebook_page_id": str(page["id"]),
                        "instagram_user_id": str(instagram_id or ""),
                    },
                }
            )
        return {
            "ok": True,
            "message": (
                "Meta подключён. Выберите страницу — Page ID и Instagram ID заполнятся автоматически."
                if choices
                else "Meta подключён, но доступных Facebook Pages не найдено."
            ),
            "details": {"choices": choices, "choice_kind": "Страница Meta"},
        }

    if provider == "vk" and not config.get("owner_id"):
        choices: list[dict] = []
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(
                    f"{VK_API}/users.get",
                    data={"access_token": token, "v": VK_API_VERSION},
                )
                response.raise_for_status()
                body = response.json()
                users = body.get("response") if isinstance(body, dict) else []
                if isinstance(users, list) and users and isinstance(users[0], dict):
                    user = users[0]
                    user_id = user.get("id")
                    if user_id is not None:
                        name = " ".join(
                            part
                            for part in (str(user.get("first_name") or ""), str(user.get("last_name") or ""))
                            if part
                        ).strip()
                        choices.append(
                            {
                                "label": f"Моя страница{f' · {name}' if name else ''}",
                                "values": {"owner_id": str(user_id)},
                            }
                        )
            except (httpx.HTTPError, ValueError):
                pass

            try:
                response = await client.post(
                    f"{VK_API}/groups.get",
                    data={
                        "access_token": token,
                        "v": VK_API_VERSION,
                        "filter": "admin,editor,moder",
                        "extended": 1,
                        "count": 100,
                    },
                )
                response.raise_for_status()
                body = response.json()
                groups = body.get("response", {}).get("items") if isinstance(body, dict) else []
                for group in groups or []:
                    if not isinstance(group, dict) or group.get("id") is None:
                        continue
                    choices.append(
                        {
                            "label": f"Сообщество · {group.get('name') or group['id']}",
                            "values": {"owner_id": f"-{group['id']}"},
                        }
                    )
            except (httpx.HTTPError, ValueError, AttributeError):
                pass

        return {
            "ok": bool(choices),
            "message": (
                "VK подключён. Выберите стену — owner_id подставится автоматически."
                if choices
                else "VK подключён, но не удалось получить доступные стены. Проверьте права приложения."
            ),
            "details": {"choices": choices, "choice_kind": "Стена VK"},
        }

    return None
