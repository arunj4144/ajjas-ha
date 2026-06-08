import asyncio
import json
import logging
import socket
import urllib.parse
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, WS_URL, WS_PARAMS, WS_HEADERS, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class AjjasCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, cookie: str, vehicle_id: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.cookie = cookie
        self.vehicle_id = vehicle_id
        self._session: aiohttp.ClientSession | None = None
        self.data: dict = {}

    def _ws_url(self) -> str:
        encoded = urllib.parse.quote(self.cookie)
        params = {**WS_PARAMS, "cookie": encoded}
        return WS_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())

    def _ws_headers(self) -> dict:
        return {
            **WS_HEADERS,
            "Cookie": f"connect.sid={self.cookie}",
            "origin": "https://api.ajjas.com/",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
        }

    async def _async_update_data(self) -> dict:
        try:
            return await self._fetch()
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Ajjas update failed: {err}") from err

    async def _fetch(self) -> dict:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(family=socket.AF_INET)
            self._session = aiohttp.ClientSession(connector=connector)

        result = dict(self.data)

        try:
            async with self._session.ws_connect(
                self._ws_url(),
                headers=self._ws_headers(),
                ssl=True,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as ws:
                await ws.send_str(json.dumps({"a": "getDynamicData"}))
                await ws.send_str(json.dumps({"a": "subVeh", "d": {"veh": [self.vehicle_id]}}))
                await ws.send_str(json.dumps({"a": "fetchData"}))
                await ws.send_str(json.dumps({
                    "a": "exapireq",
                    "d": {"req": {"url": "/gl/users/rides/getridesforalluservehicle", "method": "POST",
                                  "jsonBody": json.dumps({"vidMap": {str(self.vehicle_id): 0}, "oldestRidWithRunningTime": True})}},
                    "r": 10,
                }))
                await ws.send_str(json.dumps({
                    "a": "exapireq",
                    "d": {"req": {"url": f"/gl/users/overspeed/getzone?vid={self.vehicle_id}", "method": "GET"}},
                    "r": 11,
                }))
                await ws.send_str(json.dumps({
                    "a": "exapireq",
                    "d": {"req": {"url": f"/gl/users/geofence/getGeofences?vid={self.vehicle_id}", "method": "GET"}},
                    "r": 12,
                }))

                received = set()
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    try:
                        payload = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    action = payload.get("a")

                    if action == "sData":
                        bikes = payload.get("d", {}).get("bikes", [])
                        for bike in bikes:
                            if bike.get("idx") == self.vehicle_id:
                                result.update({
                                    "registration": bike.get("reg"),
                                    "make": bike.get("vmk"),
                                    "model": bike.get("mo"),
                                    "tank_capacity": bike.get("tcap"),
                                    "mileage": bike.get("mlg"),
                                    "relay_enabled": bike.get("rly", False),
                                    "imei": bike.get("dev", {}).get("imei"),
                                })
                                received.add("sdata")

                    elif action == "dynamicData":
                        for v in payload.get("d", {}).get("wirelessLastSeen", []):
                            if v.get("vid") == self.vehicle_id:
                                result.update(self._parse_live(v))
                                received.add("live")

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

                    elif action == "exapires":
                        r_id = payload.get("r")
                        body = payload.get("d", {})
                        if isinstance(body, str):
                            try:
                                body = json.loads(body)
                            except Exception:
                                body = {}
                        data = body.get("data", {})

                        if r_id == 10:
                            result["rides"] = data.get("rides", [])
                            result["fuel_logs"] = data.get("fuelLog", [])
                            received.add("rides")
                        elif r_id == 11:
                            result["overspeed_zones"] = data if isinstance(data, list) else data.get("zones", [])
                            received.add("overspeed")
                        elif r_id == 12:
                            result["geofences"] = data if isinstance(data, list) else data.get("geofences", [])
                            received.add("geofences")

                    if received >= {"live", "rides", "sdata"}:
                        break

        except asyncio.TimeoutError as err:
            raise UpdateFailed("Ajjas WebSocket timeout") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Ajjas connection error: {err}") from err

        return result

    def _parse_live(self, v: dict) -> dict:
        hbt = v.get("hbt", {})
        dst = hbt.get("dstInfo", {})
        return {
            "latitude": v.get("lat"),
            "longitude": v.get("lng"),
            "speed": v.get("spd", 0),
            "bearing": v.get("brg"),
            "ignition": v.get("ignition", False),
            "last_seen": v.get("ts"),
            "battery_voltage": hbt.get("externalVolt"),
            "voltage_level": hbt.get("voltLvl"),
            "main_power": hbt.get("mainPower", False),
            "odometer": round(dst.get("overall", 0) / 1000, 2),
            "today_distance": round(dst.get("curr", 0) / 1000, 2),
            "yesterday_distance": round(dst.get("prev", 0) / 1000, 2),
        }

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
