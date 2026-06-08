import json
import logging
import re
import urllib.parse
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, VERIF_URL, LOGIN_URL, WS_URL, WS_PARAMS, WS_HEADERS

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required("mobile", description={"suggested_value": "+91"}): str,
    vol.Required("password"): str,
})

STEP_COOKIE_SCHEMA = vol.Schema({
    vol.Required("cookie"): str,
    vol.Required("vehicle_id"): vol.Coerce(int),
})


class AjjasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            mobile = user_input["mobile"].strip()
            if not mobile.startswith("+"):
                mobile = "+91" + mobile.lstrip("0")
            try:
                cookie = await self._do_login(mobile, user_input["password"])
                vehicle_id = await self._get_vehicle_id(cookie)
                return self.async_create_entry(
                    title=f"Ajjas ({mobile})",
                    data={"mobile": mobile, "cookie": cookie, "vehicle_id": vehicle_id},
                )
            except ValueError:
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.error("Ajjas setup error: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            cookie = user_input["cookie"].strip()
            vehicle_id = int(user_input["vehicle_id"])
            if await self._test_ws(cookie):
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

    async def _do_login(self, mobile: str, password: str) -> str:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                LOGIN_URL,
                json={"cmob": mobile, "pwd": password, "alang": 1},
                headers={**WS_HEADERS, "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            )
            if resp.status != 200:
                raise ValueError(f"Login failed: HTTP {resp.status}")

            # Keep cookie URL-encoded as-is from Set-Cookie header (s%3A...)
            cookie = None
            for set_cookie in resp.headers.getall("Set-Cookie", []):
                m = re.search(r"connect\.sid=([^;]+)", set_cookie)
                if m:
                    cookie = m.group(1)
                    break

            if not cookie:
                raise ValueError("No session cookie in login response")
            return cookie

    async def _get_vehicle_id(self, cookie: str) -> int:
        encoded = urllib.parse.quote(cookie)
        params = {**WS_PARAMS, "cookie": encoded}
        url = WS_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                url,
                headers={"Cookie": f"connect.sid={cookie}"},
                ssl=True,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as ws:
                await ws.send_str(json.dumps({"a": "getDynamicData"}))
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        payload = json.loads(msg.data)
                        if payload.get("a") == "dynamicData":
                            vehicles = payload.get("d", {}).get("wirelessLastSeen", [])
                            if vehicles:
                                return int(vehicles[0]["vid"])
        raise ValueError("No vehicles found")

    async def _test_ws(self, cookie: str) -> bool:
        encoded = urllib.parse.quote(cookie)
        params = {**WS_PARAMS, "cookie": encoded}
        url = WS_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, ssl=True, timeout=aiohttp.ClientTimeout(total=10)) as ws:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            if json.loads(msg.data).get("a") == "ready":
                                return True
        except Exception:
            pass
        return False
