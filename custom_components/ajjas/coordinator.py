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
        last_err: Exception | None = None
        for attempt in range(3):
            if attempt > 0:
                await self._reset_session()
                await asyncio.sleep(2)
            try:
                return await self._fetch_once()
            except UpdateFailed as err:
                last_err = err
        raise last_err  # type: ignore[misc]

    async def _fetch_once(self) -> dict:
        if self._session is None or self._session.closed:
            # Use ThreadedResolver to avoid aiodns/c-ares DNS failures in Docker containers
            resolver = aiohttp.ThreadedResolver()
            connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=resolver)
            self._session = aiohttp.ClientSession(connector=connector)

        result = dict(self.data)

        try:
            async with self._session.ws_connect(
                self._ws_url(),
                headers=self._ws_headers(),
                ssl=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as ws:
                received = set()
                requests_sent = False

                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    try:
                        payload = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    action = payload.get("a")

                    # Server sends ready → msync before processing any client requests.
                    # Only send our requests after msync is received.
                    if action == "msync" and not requests_sent:
                        requests_sent = True
                        await ws.send_str(json.dumps({"a": "getDynamicData"}))
                        await ws.send_str(json.dumps({"a": "fetchData"}))
                        if self.vehicle_id:
                            await ws.send_str(json.dumps({"a": "subVeh", "d": {"veh": [self.vehicle_id]}}))
                            await self._send_data_requests(ws)

                    elif action == "ver_upd":
                        _LOGGER.debug("Ajjas: app version update available (version %s)", payload.get("d", {}).get("version"))

                    elif action == "kick":
                        _LOGGER.warning("Ajjas: session kicked by server (another login detected)")
                        raise UpdateFailed("Ajjas session kicked — re-add the integration to get a fresh session")

                    elif action == "dynamicData":
                        vehicles = payload.get("d", {}).get("wirelessLastSeen", [])
                        if vehicles and not self.vehicle_id:
                            self.vehicle_id = int(vehicles[0]["vid"])
                            _LOGGER.info("Ajjas: discovered vehicle ID %s", self.vehicle_id)
                            await ws.send_str(json.dumps({"a": "subVeh", "d": {"veh": [self.vehicle_id]}}))
                            await self._send_data_requests(ws)

                        for v in vehicles:
                            if v.get("vid") == self.vehicle_id:
                                result.update(self._parse_live(v))
                                received.add("live")

                    elif action == "sData":
                        bikes = payload.get("d", {}).get("bikes", [])
                        # If vehicle_id still unknown, pick the first non-admin bike
                        if not self.vehicle_id and bikes:
                            self.vehicle_id = int(bikes[0]["idx"])
                            _LOGGER.info("Ajjas: discovered vehicle ID %s from sData", self.vehicle_id)
                            await self._send_data_requests(ws)
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
                            result["rides"] = data.get("rides", []) if isinstance(data, dict) else []
                            result["fuel_logs"] = data.get("fuelLog", []) if isinstance(data, dict) else []
                            received.add("rides")
                        elif r_id == 11:
                            result["overspeed_zones"] = data if isinstance(data, list) else (data.get("zones", []) if isinstance(data, dict) else [])
                            received.add("overspeed")
                        elif r_id == 12:
                            result["geofences"] = data if isinstance(data, list) else (data.get("geofences", []) if isinstance(data, dict) else [])
                            received.add("geofences")

                    if received >= {"live", "rides", "sdata"}:
                        break

        except asyncio.TimeoutError as err:
            await self._reset_session()
            raise UpdateFailed("Ajjas WebSocket timeout") from err
        except aiohttp.ClientError as err:
            await self._reset_session()
            raise UpdateFailed(f"Ajjas connection error: {err}") from err

        return result

    async def _send_data_requests(self, ws) -> None:
        vid = self.vehicle_id
        await ws.send_str(json.dumps({
            "a": "exapireq",
            "d": {"req": {"url": "/gl/users/rides/getridesforalluservehicle", "method": "POST",
                          "jsonBody": json.dumps({"vidMap": {str(vid): 0}, "oldestRidWithRunningTime": True})}},
            "r": 10,
        }))
        await ws.send_str(json.dumps({
            "a": "exapireq",
            "d": {"req": {"url": f"/gl/users/overspeed/getzone?vid={vid}", "method": "GET"}},
            "r": 11,
        }))
        await ws.send_str(json.dumps({
            "a": "exapireq",
            "d": {"req": {"url": f"/gl/users/geofence/getGeofences?vid={vid}", "method": "GET"}},
            "r": 12,
        }))

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

    async def _reset_session(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def async_shutdown(self) -> None:
        await self._reset_session()
