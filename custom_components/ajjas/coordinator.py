"""Ajjas DataUpdateCoordinator with live WebSocket streaming during rides."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import socket
import urllib.parse
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    SCAN_INTERVAL,
    WAYPOINT_BUFFER_SIZE,
    WS_HEADERS,
    WS_PARAMS,
    WS_URL,
)

_LOGGER = logging.getLogger(__name__)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class AjjasCoordinator(DataUpdateCoordinator):
    """Manages polling and live WebSocket streaming for Ajjas."""

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

        # Ride state
        self._riding: bool = False
        self._waypoints: list[list[float]] = []
        self._last_ride_waypoints: list[list[float]] = []
        self._ride_distance: float = 0.0
        self._ride_start_ts: Any = None
        self._stream_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            resolver = aiohttp.ThreadedResolver()
            connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=resolver)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def _reset_session(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

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

    # ------------------------------------------------------------------
    # DataUpdateCoordinator hook
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        if self._stream_task is not None and not self._stream_task.done():
            return dict(self.data) if self.data else {}
        result = await self._fetch()
        self._on_data_fetched(result)
        return result

    # ------------------------------------------------------------------
    # Ride state machine
    # ------------------------------------------------------------------

    def _on_data_fetched(self, result: dict) -> None:
        ignition = bool(result.get("ignition"))

        if ignition and not self._riding:
            _LOGGER.debug("Ajjas: ride started")
            self._waypoints = []
            self._ride_distance = 0.0
            self._ride_start_ts = result.get("last_seen")
            self._riding = True
            self._append_waypoint(result)
            self._start_stream()
        elif not ignition and self._riding:
            _LOGGER.debug("Ajjas: ride ended (via poll)")
            self._last_ride_waypoints = list(self._waypoints)
            self._riding = False
        elif ignition and self._riding:
            self._append_waypoint(result)
            if self._stream_task is None or self._stream_task.done():
                self._start_stream()

        result["ride_waypoints"] = list(self._waypoints)
        result["last_ride_waypoints"] = list(self._last_ride_waypoints)
        result["is_riding"] = self._riding
        result["ride_distance_km"] = round(self._ride_distance, 3)
        result["ride_start_ts"] = self._ride_start_ts

    # ------------------------------------------------------------------
    # Waypoint helpers
    # ------------------------------------------------------------------

    def _append_waypoint(self, data: dict) -> None:
        lat = data.get("lat")
        lon = data.get("lon")
        spd = float(data.get("speed") or 0.0)
        if lat is None or lon is None:
            return
        self._add_to_waypoints(float(lat), float(lon), spd)

    def _add_to_waypoints(self, lat: float, lon: float, spd: float) -> None:
        if self._waypoints:
            prev = self._waypoints[-1]
            self._ride_distance += _haversine_km(prev[0], prev[1], lat, lon)
        self._waypoints.append([round(lat, 6), round(lon, 6), round(spd, 1)])
        if len(self._waypoints) > WAYPOINT_BUFFER_SIZE:
            self._waypoints = self._waypoints[-WAYPOINT_BUFFER_SIZE:]

    # ------------------------------------------------------------------
    # Streaming WebSocket (live during rides)
    # ------------------------------------------------------------------

    def _start_stream(self) -> None:
        if self._stream_task is not None and not self._stream_task.done():
            return
        _LOGGER.debug("Ajjas: starting WS stream task")
        self.update_interval = None
        try:
            self._stream_task = self.hass.async_create_background_task(
                self._stream_ws(),
                name="ajjas_ws_stream",
            )
        except AttributeError:
            self._stream_task = asyncio.ensure_future(self._stream_ws())

    async def _stream_ws(self) -> None:
        _LOGGER.info("Ajjas: WS stream starting")
        try:
            while self._riding:
                try:
                    await self._stream_ws_once()
                except asyncio.CancelledError:
                    return
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning("Ajjas: stream error, retrying in 5 s: %s", exc)
                    await self._reset_session()
                    await asyncio.sleep(5)
        finally:
            _LOGGER.info("Ajjas: WS stream ended — restoring polling interval")
            if self._waypoints:
                self._last_ride_waypoints = list(self._waypoints)
            self._riding = False
            self._waypoints = []
            self._ride_distance = 0.0
            self.update_interval = timedelta(seconds=SCAN_INTERVAL)
            with contextlib.suppress(Exception):
                self._schedule_refresh()

    async def _stream_ws_once(self) -> None:
        """One WS connection in the streaming loop."""
        session = self._get_session()
        requests_sent = False

        async with session.ws_connect(
            self._ws_url(),
            headers=self._ws_headers(),
            ssl=True,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as ws:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break

                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                action = payload.get("a")

                if action == "msync" and not requests_sent:
                    requests_sent = True
                    await ws.send_str(json.dumps({"a": "getDynamicData"}))
                    if self.vehicle_id:
                        await ws.send_str(json.dumps({
                            "a": "subVeh",
                            "d": {"veh": [self.vehicle_id]},
                        }))

                elif action == "locUpd":
                    d = payload.get("d", {})
                    vid = d.get("vid")
                    if self.vehicle_id and vid and int(vid) != int(self.vehicle_id):
                        continue

                    lat = d.get("lat")
                    lng = d.get("lng")
                    spd = float(d.get("spd") or 0)
                    brg = d.get("brg")
                    ign = d.get("ign")

                    new_data = dict(self.data) if self.data else {}
                    if lat is not None:
                        new_data["lat"] = lat
                    if lng is not None:
                        new_data["lon"] = lng
                    new_data["speed"] = spd
                    if brg is not None:
                        new_data["bearing"] = brg
                    if ign is not None:
                        new_data["ignition"] = bool(ign)

                    if lat is not None and lng is not None:
                        self._add_to_waypoints(float(lat), float(lng), spd)

                    new_data["ride_waypoints"] = list(self._waypoints)
                    new_data["last_ride_waypoints"] = list(self._last_ride_waypoints)
                    new_data["is_riding"] = self._riding
                    new_data["ride_distance_km"] = round(self._ride_distance, 3)
                    new_data["ride_start_ts"] = self._ride_start_ts

                    self.async_set_updated_data(new_data)

                    if ign is not None and not bool(ign):
                        _LOGGER.info("Ajjas: ignition off (locUpd) — stopping stream")
                        self._last_ride_waypoints = list(self._waypoints)
                        self._riding = False
                        return

                elif action == "dynamicData":
                    vehicles = payload.get("d", {}).get("wirelessLastSeen", [])
                    for v in vehicles:
                        if v.get("vid") == self.vehicle_id:
                            new_data = dict(self.data) if self.data else {}
                            new_data.update(self._parse_live(v))
                            self.async_set_updated_data(new_data)
                            if not new_data.get("ignition"):
                                _LOGGER.info("Ajjas: ignition off (dynamicData) — stopping stream")
                                self._last_ride_waypoints = list(self._waypoints)
                                self._riding = False
                                return
                            break

                elif action == "kick":
                    _LOGGER.warning("Ajjas: kicked by server during stream")
                    return

    # ------------------------------------------------------------------
    # Polling fetch
    # ------------------------------------------------------------------

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
        session = self._get_session()
        result = dict(self.data) if self.data else {}

        try:
            async with session.ws_connect(
                self._ws_url(),
                headers=self._ws_headers(),
                ssl=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as ws:
                received: set[str] = set()
                requests_sent = False

                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    try:
                        payload = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    action = payload.get("a")

                    if action == "msync" and not requests_sent:
                        requests_sent = True
                        await ws.send_str(json.dumps({"a": "getDynamicData"}))
                        await ws.send_str(json.dumps({"a": "fetchData"}))
                        if self.vehicle_id:
                            await ws.send_str(json.dumps({
                                "a": "subVeh",
                                "d": {"veh": [self.vehicle_id]},
                            }))
                            await self._send_data_requests(ws)

                    elif action == "dynamicData":
                        vehicles = payload.get("d", {}).get("wirelessLastSeen", [])
                        if vehicles and not self.vehicle_id:
                            self.vehicle_id = int(vehicles[0]["vid"])
                            _LOGGER.info("Ajjas: discovered vehicle_id=%s", self.vehicle_id)
                            await ws.send_str(json.dumps({
                                "a": "subVeh",
                                "d": {"veh": [self.vehicle_id]},
                            }))
                            await self._send_data_requests(ws)
                        for v in vehicles:
                            if v.get("vid") == self.vehicle_id:
                                result.update(self._parse_live(v))
                                received.add("live")

                    elif action == "sData":
                        bikes = payload.get("d", {}).get("bikes", [])
                        if not self.vehicle_id and bikes:
                            self.vehicle_id = int(bikes[0]["idx"])
                            _LOGGER.info("Ajjas: discovered vehicle_id=%s from sData", self.vehicle_id)
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
                                "lat": d.get("lat"),
                                "lon": d.get("lng"),
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
                            result["overspeed_zones"] = (
                                data if isinstance(data, list)
                                else (data.get("zones", []) if isinstance(data, dict) else [])
                            )
                            received.add("overspeed")
                        elif r_id == 12:
                            result["geofences"] = (
                                data if isinstance(data, list)
                                else (data.get("geofences", []) if isinstance(data, dict) else [])
                            )
                            received.add("geofences")

                    elif action == "ver_upd":
                        pass

                    elif action == "kick":
                        _LOGGER.warning("Ajjas: session kicked by server")
                        raise UpdateFailed("Ajjas session kicked — re-add the integration")

                    if received >= {"live", "rides", "sdata"}:
                        break

        except asyncio.TimeoutError as err:
            await self._reset_session()
            raise UpdateFailed("Ajjas WebSocket timeout") from err
        except aiohttp.ClientError as err:
            await self._reset_session()
            raise UpdateFailed(f"Ajjas connection error: {err}") from err

        return result

    async def _send_data_requests(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        vid = self.vehicle_id
        await ws.send_str(json.dumps({
            "a": "exapireq",
            "d": {"req": {
                "url": "/gl/users/rides/getridesforalluservehicle",
                "method": "POST",
                "jsonBody": json.dumps({"vidMap": {str(vid): 0}, "oldestRidWithRunningTime": True}),
            }},
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
            "lat": v.get("lat"),
            "lon": v.get("lng"),
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

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def async_shutdown(self) -> None:
        if self._stream_task is not None and not self._stream_task.done():
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
        await self._reset_session()
