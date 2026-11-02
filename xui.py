"""Клиенты iPhone: WireGuard-пиры в панели 3x-ui (вход XUI_INBOUND_ID), поверх
vk-turn-proxy-ios (SRTP). Всё через API панели по токену; ключи и IP клиента
панель генерирует сама. VK-хеш хранится в поле `comment` клиента."""
import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from config import (
    XUI_BASE_URL,
    XUI_TOKEN,
    XUI_INBOUND_ID,
    XUI_VERIFY_TLS,
    IOS_PEER_ADDRESS,
    IOS_DNS,
    IOS_NUM_CONNECTIONS,
)

VK_CALL_BASE = "https://vk.ru/call/join/"

# Суффикс к имени при дубликате email: Test -> Test_02112026_14_25 (время по Москве, UTC+3).
_SUFFIX_TZ = timezone(timedelta(hours=3))
MAX_NAME_LEN = 32

_ctx = ssl.create_default_context()
if not XUI_VERIFY_TLS:
    _ctx.check_hostname = False
    _ctx.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        XUI_BASE_URL.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {XUI_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=20) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"3x-ui: HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as e:
        raise RuntimeError(f"3x-ui недоступен: {e}") from e
    if not payload.get("success"):
        raise RuntimeError(f"3x-ui: {payload.get('msg') or 'неизвестная ошибка'}")
    return payload.get("obj")


def _inbound() -> dict:
    inbound = _call("GET", f"/panel/api/inbounds/get/{XUI_INBOUND_ID}")
    settings = inbound["settings"]
    inbound["settings"] = json.loads(settings) if isinstance(settings, str) else settings
    return inbound


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_vk_hash(raw: str) -> str:
    s = raw.strip()
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    if "?" in s:
        s = s.split("?", 1)[0]
    return s.strip()


def _x25519(k_int: int, u_int: int) -> int:
    """X25519 (RFC 7748) на чистом Python — публичный ключ входа из его секретного."""
    P = 2 ** 255 - 19
    x1 = u_int
    x2, z2, x3, z3, swap = 1, 0, u_int, 1, 0
    for t in reversed(range(255)):
        kt = (k_int >> t) & 1
        swap ^= kt
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = kt
        A = (x2 + z2) % P
        AA = A * A % P
        B = (x2 - z2) % P
        BB = B * B % P
        E = (AA - BB) % P
        C = (x3 + z3) % P
        D = (x3 - z3) % P
        DA = D * A % P
        CB = C * B % P
        x3 = (DA + CB) ** 2 % P
        z3 = x1 * (DA - CB) ** 2 % P
        x2 = AA * BB % P
        z2 = E * (AA + 121665 * E) % P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    return x2 * pow(z2, P - 2, P) % P


def server_public_key(secret_b64: str) -> str:
    priv = bytearray(base64.b64decode(secret_b64))
    priv[0] &= 248
    priv[31] &= 127
    priv[31] |= 64
    pub = _x25519(int.from_bytes(priv, "little"), 9).to_bytes(32, "little")
    return base64.b64encode(pub).decode()


def _to_dict(c: dict, traffic: dict) -> dict:
    email = c["email"]
    ips = c.get("allowedIPs") or []
    if isinstance(ips, str):
        ips = [ips]
    expiry_ms = c.get("expiryTime") or 0
    used = traffic.get(email, 0)
    return {
        "name": email,
        "vk_hash": c.get("comment") or "",
        "expires_at": int(expiry_ms / 1000) if expiry_ms else 0,
        "is_deactivated": not c.get("enable", True),
        "tunnel_ip": ips[0] if ips else "",
        "used_bytes": used,
    }


def _traffic_map(inbound: dict) -> dict:
    return {
        s["email"]: (s.get("up") or 0) + (s.get("down") or 0)
        for s in inbound.get("clientStats") or []
    }


# ---------------------------------------------------------------------------
# Public API (интерфейс, общий с wdtt: ключом клиента служит email)
# ---------------------------------------------------------------------------

def list_clients() -> list[dict]:
    inbound = _inbound()
    traffic = _traffic_map(inbound)
    return [_to_dict(c, traffic) for c in inbound["settings"].get("clients", [])]


def get_client(email: str) -> dict:
    for c in list_clients():
        if c["name"] == email:
            return c
    raise RuntimeError(f"Клиент {email} не найден")


def _is_duplicate_email(err: RuntimeError) -> bool:
    msg = str(err).lower()
    # Панель говорит по-разному, в зависимости от того, где поймала дубль.
    return "duplicate email" in msg or "email already in use" in msg


def _with_timestamp(name: str) -> str:
    suffix = datetime.now(_SUFFIX_TZ).strftime("_%d%m%Y_%H_%M")
    return name[: MAX_NAME_LEN - len(suffix)] + suffix


def add_client(name: str, vk_hash: str, expires_days: int) -> dict:
    """Email клиента уникален во всей панели 3x-ui. Если такой уже есть, к имени
    дописывается дата и время (Test -> Test_02112026_14_25) и создание повторяется.
    Возвращает фактически использованное имя."""
    vk_hash = strip_vk_hash(vk_hash)
    expiry_ms = (int(time.time()) + expires_days * 86400) * 1000

    def create(email: str) -> None:
        _call("POST", "/panel/api/clients/add", {
            "client": {
                "email": email,
                "enable": True,
                "expiryTime": expiry_ms,
                "comment": vk_hash,
                "keepAlive": 25,
            },
            "inboundIds": [XUI_INBOUND_ID],
        })

    try:
        create(name)
    except RuntimeError as e:
        if not _is_duplicate_email(e):
            raise
        name = _with_timestamp(name)
        create(name)
    return {"name": name, "vk_hash": vk_hash}


def delete_client(email: str) -> str:
    _call("POST", f"/panel/api/clients/del/{quote(email, safe='')}")
    return email


def _update(email: str, **changes) -> None:
    """Правка клиента: берём полную запись и меняем только нужные поля."""
    obj = _call("GET", f"/panel/api/clients/get/{quote(email, safe='')}")
    client = obj["client"]
    # GET отдаёт `id` числом (строка в БД), а update ждёт строку-идентификатор клиента.
    client["id"] = client.get("uuid") or ""
    # allowedIPs: GET отдаёт строку, update ждёт список.
    ips = client.get("allowedIPs")
    if isinstance(ips, str):
        client["allowedIPs"] = [p.strip() for p in ips.split(",") if p.strip()]
    client.update(changes)
    _call("POST", f"/panel/api/clients/update/{quote(email, safe='')}", client)


def set_vk_hash(email: str, vk_hash: str) -> str:
    vk_hash = strip_vk_hash(vk_hash)
    _update(email, comment=vk_hash)
    return vk_hash


def set_deactivated(email: str, is_deactivated: bool) -> None:
    _update(email, enable=not is_deactivated)


def set_expires_days(email: str, expires_days: int) -> int:
    expires_at = int(time.time()) + expires_days * 86400
    _update(email, expiryTime=expires_at * 1000)
    return expires_at


def build_link(email: str, vk_hash: str) -> str:
    """vkturnproxy://import?data=… — формат тот же, что делает quick_link.py."""
    inbound = _inbound()
    client = next((c for c in inbound["settings"]["clients"] if c["email"] == email), None)
    if client is None:
        raise RuntimeError(f"Клиент {email} не найден")
    ips = client.get("allowedIPs") or []
    tunnel = ips[0] if isinstance(ips, list) else ips
    payload = {
        "settings": {
            "dnsServers": IOS_DNS,
            "numConnections": IOS_NUM_CONNECTIONS,
            "peerAddress": IOS_PEER_ADDRESS,
            "peerPublicKey": server_public_key(inbound["settings"]["secretKey"]),
            "privateKey": client["privateKey"],
            "tunnelAddress": tunnel,
            "useDTLS": True,
            "useSrtp": True,
            "useUDP": False,
            "useWrap": False,
            "useWrapA": False,
            "vkLink": VK_CALL_BASE + vk_hash,
        },
        "type": "connection",
        "version": 1,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return "vkturnproxy://import?data=" + base64.urlsafe_b64encode(raw).decode().rstrip("=")
