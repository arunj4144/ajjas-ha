DOMAIN = "ajjas"

WS_URL = "wss://api.ajjas.com/wss"
WS_SHARING_URL = "wss://api.ajjas.com/wssSharing"
API_BASE = "https://api.ajjas.com"
CRM_BASE = "https://crmapi.ajjas.com"

VERIF_URL = f"{CRM_BASE}/crm/users/users/verifwithmob"
LOGIN_URL = f"{CRM_BASE}/crm/users/login/"
LOGOUT_URL = f"{CRM_BASE}/crm/users/logout"

RIDES_URL = "/gl/users/rides/getridesforalluservehicle"
RIDE_STATS_URL = "/gl/users/timeline/getstatsbytime"
LOC_EVENTS_URL = "/gl/users/location/getLocEvents"
SOS_URL = "/gl/users/sos/getCountDownTime"
FUEL_PRICE_URL = "/gl/users/fuelLogv2/getFuelPrice"

CONF_MOBILE = "mobile"
CONF_COOKIE = "cookie"
CONF_VID = "vehicle_id"

WS_HEADERS = {
    "reqver": "294",
    "reqsrc": "android",
    "prodid": "1",
    "jsver": "244",
    "User-Agent": "okhttp/4.9.2",
}

WS_PARAMS = {
    "reqver": "294",
    "reqsrc": "ha",
    "prodId": "1",
    "theme": "dark",
}

SCAN_INTERVAL = 30
