import asyncio
import json
import logging
import urllib.parse
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, WS_BASE, WS_PARAMS, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class AjjasCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, cookie: str, vehicle_id: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.cookie = cookie
        self.vehicle_id = vehicle_id
        self._ws = None
        self._session = None
        self.data = {}

    def _build_ws_url(self) -> str:
        encoded_cookie = urllib.parse.quote(urllib.parse.quote(self.cookie))
        params = {**WS_PARAMS, "cookie": encoded_cookie}
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{WS_BASE}?{query}"

    async def _async_update_data(self):
        try:
            return await self._fetch_vehicle_data()
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Ajjas: {err}") from err

    async def _fetch_vehicle_data(self) -> dict:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

        url = self._build_ws_url()
        result = {}

        try:
            async with self._session.ws_connect(
                url,
                headers={"Cookie": f"connect.sid={self.cookie}"},
                ssl=True,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as ws:
                await ws.send_str(json.dumps({"a": "getDynamicData"}))
                await ws.send_str(json.dumps({"a": "subVeh", "d": {"veh": [self.vehicle_id]}}))

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            payload = json.loads(msg.data)
                        except json.JSONDecodeError:
                            continue

                        action = payload.get("a")

                        if action == "dynamicData":
                            vehicles = payload.get("d", {}).get("wirelessLastSeen", [])
                            for v in vehicles:
                                if v.get("vid") == self.vehicle_id:
                                    result = self._parse_vehicle(v)
                                    return result

                        elif action == "locUpd":
                            d = payload.get("d", {})
                            if d.get("vid") == self.vehicle_id:
                                result.update({
                                    "latitude": d.get("lat"),
                                    "longitude": d.get("lng"),
                                    "speed": d.get("spd"),
                                    "bearing": d.get("brg"),
                                    "ignition": d.get("ign"),
                                })

                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break

        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout connecting to Ajjas WebSocket") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"WebSocket error: {err}") from err

        return result or self.data

    def _parse_vehicle(self, v: dict) -> dict:
        hbt = v.get("hbt", {})
        dst = hbt.get("dstInfo", {})
        return {
            "latitude": v.get("lat"),
            "longitude": v.get("lng"),
            "speed": v.get("spd"),
            "bearing": v.get("brg"),
            "ignition": v.get("ignition"),
            "last_seen": v.get("ts"),
            "battery_voltage": hbt.get("externalVolt"),
            "voltage_level": hbt.get("voltLvl"),
            "main_power": hbt.get("mainPower"),
            "odometer": round(dst.get("overall", 0) / 1000, 2),
            "today_distance": round(dst.get("curr", 0) / 1000, 2),
            "yesterday_distance": round(dst.get("prev", 0) / 1000, 2),
        }

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
