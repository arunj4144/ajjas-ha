import asyncio
import json
import logging
import re
import socket
import urllib.parse
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, LOGIN_URL, WS_HEADERS

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required("mobile"): str,
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
                cookie, user_data = await asyncio.wait_for(
                    self._do_login(mobile, user_input["password"]),
                    timeout=15,
                )
                return self.async_create_entry(
                    title=f"Ajjas ({user_data.get('fn', mobile)})",
                    data={
                        "mobile": mobile,
                        "cookie": cookie,
                        "vehicle_id": 0,  # discovered on first coordinator refresh
                    },
                )
            except asyncio.TimeoutError:
                _LOGGER.error("Ajjas login timed out")
                errors["base"] = "cannot_connect"
            except PermissionError:
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
        if user_input is not None:
            return self.async_create_entry(
                title=f"Ajjas (Vehicle {user_input['vehicle_id']})",
                data={"cookie": user_input["cookie"].strip(), "vehicle_id": int(user_input["vehicle_id"])},
            )
        return self.async_show_form(step_id="manual", data_schema=STEP_COOKIE_SCHEMA, errors={})

    async def _do_login(self, mobile: str, password: str) -> tuple[str, dict]:
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            resp = await session.post(
                LOGIN_URL,
                json={"cmob": mobile, "pwd": password, "alang": 1},
                headers={**WS_HEADERS, "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
            )
            _LOGGER.debug("Ajjas login status: %s", resp.status)

            body = await resp.json(content_type=None)
            _LOGGER.debug("Ajjas login response: %s", body.get("message"))

            if resp.status != 200 or body.get("message") != "OK":
                raise PermissionError(f"Login failed: {resp.status} {body.get('message')}")

            # Extract cookie keeping URL-encoding as-is (s%3A...)
            cookie = None
            for set_cookie in resp.headers.getall("Set-Cookie", []):
                m = re.search(r"connect\.sid=([^;]+)", set_cookie)
                if m:
                    cookie = m.group(1)
                    break

            if not cookie:
                raise PermissionError("No session cookie in response")

            return cookie, body.get("data", {})
