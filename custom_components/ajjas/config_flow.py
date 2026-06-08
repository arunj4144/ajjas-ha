import json
import logging
import urllib.parse
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, LOGIN_URL, WS_BASE, WS_PARAMS

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required("email"): str,
    vol.Required("password"): str,
})

STEP_COOKIE_SCHEMA = vol.Schema({
    vol.Required("cookie"): str,
    vol.Required("vehicle_id"): vol.Coerce(int),
})


class AjjasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                cookie, vehicle_id = await self._login(user_input["email"], user_input["password"])
                return self.async_create_entry(
                    title=f"Ajjas ({user_input['email']})",
                    data={"cookie": cookie, "vehicle_id": vehicle_id, "email": user_input["email"]},
                )
            except ValueError as e:
                _LOGGER.warning("Ajjas login failed: %s", e)
                errors["base"] = "invalid_auth"
            except Exception as e:
                _LOGGER.error("Ajjas login error: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"fallback_note": "Or use Manual Cookie entry below"},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            cookie = user_input["cookie"].strip()
            vehicle_id = user_input["vehicle_id"]
            ok = await self._test_ws(cookie, vehicle_id)
            if ok:
                return self.async_create_entry(
                    title=f"Ajjas (Vehicle {vehicle_id})",
                    data={"cookie": cookie, "vehicle_id": vehicle_id},
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_COOKIE_SCHEMA,
            errors=errors,
        )

    async def _login(self, email: str, password: str) -> tuple[str, int]:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                LOGIN_URL,
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            )
            if resp.status != 200:
                raise ValueError(f"Login returned {resp.status}")

            body = await resp.json()
            cookie = None
            for header_val in resp.headers.getall("Set-Cookie", []):
                for part in header_val.split(";"):
                    part = part.strip()
                    if part.startswith("connect.sid="):
                        cookie = part[len("connect.sid="):]
                        break

            if not cookie:
                # fallback: try body
                cookie = body.get("data", {}).get("cookie") or body.get("cookie")

            if not cookie:
                raise ValueError("No session cookie in login response")

            data = body.get("data", {})
            vehicles = data.get("vehicles") or data.get("veh") or []
            vehicle_id = vehicles[0].get("vid") if vehicles else 0
            if not vehicle_id:
                vehicle_id = data.get("vid") or 0

            return cookie, int(vehicle_id)

    async def _test_ws(self, cookie: str, vehicle_id: int) -> bool:
        encoded_cookie = urllib.parse.quote(urllib.parse.quote(cookie))
        params = {**WS_PARAMS, "cookie": encoded_cookie}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{WS_BASE}?{query}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, ssl=True, timeout=aiohttp.ClientTimeout(total=10)) as ws:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(msg.data)
                            if payload.get("a") == "ready":
                                return True
        except Exception:
            return False
        return False
