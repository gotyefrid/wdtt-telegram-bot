import json
import base64


def build_link(settings: dict):
    payload = {
        "version": 1,
        "type": "connection",
        "settings": settings,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    # url-safe base64 without padding
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"vkturnproxy://import?data={b64}"


def main():
    print("Введите приватный ключ:")
    private_key = input("> ").strip() or ''

    print("Введите IP адрес:")
    ip_address = input("> ").strip() or ''

    print("Введите ссылку на звонок:")
    call_link = input("> ").strip() or ''

    settings = {
        "privateKey": private_key,
        "peerPublicKey": "XHPFELJys6G/+qsYBj+92zqP6TqW28QGJbJJFzoj4UA=",
        "tunnelAddress": ip_address,
        "allowedIPs": "0.0.0.0/0",
        "vkLink": call_link,
        "peerAddress": "46.32.185.135:56011",
        "dnsServers": "1.1.1.1",
        "numConnections": 30,
        "useDTLS": True,
        "useWrap": False,
        "wrapKeyHex": "",
        "useSrtp": True,
        "useUDP": False,
    }

    result = build_link(settings)

    print("\nСформированная конфигурация:")
    print(result)


if __name__ == "__main__":
    main()
