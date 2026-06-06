"""Smart-home tools — Home Assistant control via its REST API. Stdlib-only.

Off until configured. Add a ``smart_home`` block to ``friday/config.yaml``::

    smart_home:
      url: http://homeassistant.local:8123
      token_env: HASS_TOKEN          # long-lived token lives in .env
      aliases:
        bedroom lights: light.bedroom_main
        ac: climate.living_room_ac

The model passes a friendly name or a raw ``domain.entity`` id; aliases are
resolved here. State reads are free; the three mutating tools are
``destructive=True`` → approval-gated (they change physical devices).
"""
from __future__ import annotations

import json
import os
import urllib.request

from friday.config import load_config
from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult


def _cfg() -> dict:
    try:
        return (load_config() or {}).get("smart_home") or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("[smart_home] config load failed: %s", exc)
        return {}


def _client() -> tuple[str, str, dict, str]:
    """Return (base_url, token, aliases, error)."""
    cfg = _cfg()
    url = (cfg.get("url") or "").strip().rstrip("/")
    token = os.environ.get(cfg.get("token_env") or "HASS_TOKEN", "") or (cfg.get("token") or "")
    aliases = {str(k).lower(): v for k, v in (cfg.get("aliases") or {}).items()}
    if not url or not token:
        return "", "", {}, "Home Assistant is not configured — set smart_home.url + token in config.yaml"
    return url, token, aliases, ""


def _resolve(entity: str, aliases: dict) -> str:
    entity = (entity or "").strip()
    return aliases.get(entity.lower(), entity)


def _request(base: str, token: str, method: str, path: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        f"{base}/api/{path.lstrip('/')}", data=body, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw else {}


def _entity_arg(args: dict) -> str:
    return (args.get("entity") or args.get("entity_id") or args.get("name") or "").strip()


def _call(method: str, path: str, data: dict | None = None) -> ToolResult:
    base, token, _, err = _client()
    if err:
        return ToolResult(ok=False, content="", error=err)
    try:
        result = _request(base, token, method, path, data)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"Home Assistant request failed: {exc}")
    return ToolResult(ok=True, content="", data=result)


def _service(domain: str, service: str, entity: str, extra: dict | None = None) -> ToolResult:
    res = _call("POST", f"services/{domain}/{service}", {"entity_id": entity, **(extra or {})})
    if not res.ok:
        return res
    return ToolResult(ok=True, content=f"Called {domain}.{service} on {entity}.", data=res.data)


def _turn_on(args: dict) -> ToolResult:
    _, _, aliases, err = _client()
    if err:
        return ToolResult(ok=False, content="", error=err)
    entity = _resolve(_entity_arg(args), aliases)
    if "." not in entity:
        return ToolResult(ok=False, content="", error=f"unknown entity/alias: {entity!r}")
    return _service(entity.split(".")[0], "turn_on", entity)


def _turn_off(args: dict) -> ToolResult:
    _, _, aliases, err = _client()
    if err:
        return ToolResult(ok=False, content="", error=err)
    entity = _resolve(_entity_arg(args), aliases)
    if "." not in entity:
        return ToolResult(ok=False, content="", error=f"unknown entity/alias: {entity!r}")
    return _service(entity.split(".")[0], "turn_off", entity)


def _get_state(args: dict) -> ToolResult:
    _, _, aliases, err = _client()
    if err:
        return ToolResult(ok=False, content="", error=err)
    entity = _resolve(_entity_arg(args), aliases)
    res = _call("GET", f"states/{entity}")
    if not res.ok:
        return res
    state = (res.data or {}).get("state", "unknown")
    return ToolResult(ok=True, content=f"{entity} is {state}", data=res.data)


def _set_temperature(args: dict) -> ToolResult:
    _, _, aliases, err = _client()
    if err:
        return ToolResult(ok=False, content="", error=err)
    entity = _resolve(_entity_arg(args), aliases)
    try:
        temp = float(args.get("temperature"))
    except (TypeError, ValueError):
        return ToolResult(ok=False, content="", error="a numeric temperature is required")
    res = _service("climate", "set_temperature", entity, {"temperature": temp})
    if res.ok:
        return ToolResult(ok=True, content=f"Set {entity} to {temp}°.", data=res.data)
    return res


_ENTITY_PROP = {"entity": {"type": "string", "description": "friendly alias or domain.entity_id"}}


def register(registry: ToolRegistry) -> None:
    registry.register("ha_turn_on", "Turn on a Home Assistant device/scene.", {
        "type": "object", "properties": _ENTITY_PROP, "required": ["entity"],
    }, _turn_on, destructive=True)

    registry.register("ha_turn_off", "Turn off a Home Assistant device.", {
        "type": "object", "properties": _ENTITY_PROP, "required": ["entity"],
    }, _turn_off, destructive=True)

    registry.register("ha_get_state", "Read the current state of a Home Assistant entity.", {
        "type": "object", "properties": _ENTITY_PROP, "required": ["entity"],
    }, _get_state)

    registry.register("ha_set_temperature", "Set a Home Assistant climate device's target temperature.", {
        "type": "object",
        "properties": {**_ENTITY_PROP, "temperature": {"type": "number", "description": "target temperature"}},
        "required": ["entity", "temperature"],
    }, _set_temperature, destructive=True)
