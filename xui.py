import base64
import json
import httpx
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from config import XUI_BASE_URL, XUI_API_TOKEN, XUI_VERIFY_SSL, DEFAULT_INBOUND_ID


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=XUI_BASE_URL,
        headers={"Authorization": f"Bearer {XUI_API_TOKEN}"},
        verify=XUI_VERIFY_SSL,
        timeout=10,
    )


def get_inbound(inbound_id: int = DEFAULT_INBOUND_ID) -> dict:
    with _client() as c:
        r = c.get(f"/panel/api/inbounds/get/{inbound_id}")
        r.raise_for_status()
        data = r.json()
    if not data.get("success"):
        raise RuntimeError(data.get("msg", "3x-ui error"))
    ib = data["obj"]
    if isinstance(ib.get("settings"), str):
        ib["settings"] = json.loads(ib["settings"])
    return ib


def _inbound_payload(ib: dict) -> dict:
    return {
        "enable":         ib.get("enable", True),
        "remark":         ib.get("remark", ""),
        "listen":         ib.get("listen", ""),
        "port":           ib["port"],
        "protocol":       ib["protocol"],
        "expiryTime":     ib.get("expiryTime", 0),
        "total":          ib.get("total", 0),
        "settings":       ib["settings"],
        "streamSettings": ib.get("streamSettings") or {},
        "sniffing":       ib.get("sniffing") or {},
    }


def _update_inbound(ib: dict, inbound_id: int = DEFAULT_INBOUND_ID) -> None:
    with _client() as c:
        r = c.post(f"/panel/api/inbounds/update/{inbound_id}", json=_inbound_payload(ib))
        r.raise_for_status()
        data = r.json()
    if not data.get("success"):
        raise RuntimeError(data.get("msg", "3x-ui update error"))


def _parse_names(ib: dict) -> list[str]:
    return [n.strip() for n in ib.get("remark", "").split(",") if n.strip()]


def list_clients(inbound_id: int = DEFAULT_INBOUND_ID) -> list[dict]:
    ib = get_inbound(inbound_id)
    names = _parse_names(ib)
    peers = ib["settings"].get("peers", [])
    result = []
    for i, peer in enumerate(peers):
        ip = peer.get("allowedIPs", ["?"])[0].split("/")[0]
        result.append({
            "index": i,  # 0-based
            "name": names[i] if i < len(names) else f"peer{i+1}",
            "ip": ip,
        })
    return result


def get_peer(index: int, inbound_id: int = DEFAULT_INBOUND_ID) -> dict:
    ib = get_inbound(inbound_id)
    peers = ib["settings"].get("peers", [])
    names = _parse_names(ib)
    if index >= len(peers):
        raise IndexError(f"Peer index {index} out of range")
    peer = peers[index]
    ip = peer.get("allowedIPs", ["?"])[0].split("/")[0]
    return {
        "index": index,
        "name": names[index] if index < len(names) else f"peer{index+1}",
        "ip": ip,
        "private_key": peer.get("privateKey", ""),
        "public_key":  peer.get("publicKey", ""),
    }


def _generate_wg_keypair() -> tuple[str, str]:
    priv = X25519PrivateKey.generate()
    private_b64 = base64.b64encode(priv.private_bytes_raw()).decode()
    public_b64  = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    return private_b64, public_b64


def _next_free_ip(peers: list[dict]) -> str:
    octets = []
    for peer in peers:
        for ip_cidr in peer.get("allowedIPs", []):
            try:
                last = int(ip_cidr.split("/")[0].split(".")[-1])
                octets.append(last)
            except ValueError:
                pass
    next_octet = max(octets, default=1) + 1
    if next_octet > 254:
        raise RuntimeError("IP-пул исчерпан (максимум 253 клиента)")
    return f"10.0.0.{next_octet}"


def add_peer(name: str, inbound_id: int = DEFAULT_INBOUND_ID) -> dict:
    ib = get_inbound(inbound_id)
    peers = ib["settings"].get("peers", [])

    private_key, public_key = _generate_wg_keypair()
    ip = _next_free_ip(peers)

    peers.append({
        "privateKey": private_key,
        "publicKey":  public_key,
        "allowedIPs": [f"{ip}/32"],
        "keepAlive":  0,
    })
    ib["settings"]["peers"] = peers

    index = len(peers)
    prefixed_name = f"{index}-{name}"
    remark = ib.get("remark", "")
    ib["remark"] = f"{remark},{prefixed_name}" if remark else prefixed_name

    _update_inbound(ib, inbound_id)
    return {"private_key": private_key, "public_key": public_key, "ip": ip}


def delete_peer(index: int, inbound_id: int = DEFAULT_INBOUND_ID) -> str:
    """Delete peer at 0-based index. Returns the deleted peer's name."""
    ib = get_inbound(inbound_id)
    peers = ib["settings"].get("peers", [])
    names = _parse_names(ib)

    if index >= len(peers):
        raise IndexError(f"Peer index {index} out of range")

    deleted_name = names[index] if index < len(names) else f"peer{index+1}"
    peers.pop(index)
    if index < len(names):
        names.pop(index)

    ib["settings"]["peers"] = peers
    ib["remark"] = ",".join(names)

    _update_inbound(ib, inbound_id)
    return deleted_name
