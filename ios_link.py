"""Сборка vkturnproxy:// ссылки для iOS-приложения в режиме SRTP-WRAP-A.

Урезанный вариант quick_link.py (anton48/vk-turn-proxy-ios) — только режим
WRAP-A. В этом режиме сервер сам провижинит WireGuard через GETCONF, поэтому
в ссылке нет WG-ключей — нужны только vkLink, адрес сервера и пароль.

В этом проекте WRAP-A обслуживает тот же wdtt.service (см. wdtt.ios_peer_address —
адрес совпадает с wdtt://, порт 56000), а wrapAPassword — это пароль конкретного
клиента (тот же, что в его wdtt://-ссылке), а не общий серверный секрет.
https://github.com/anton48/vk-turn-proxy-ios/blob/main/quick_link.py
"""

import base64
import json

SCHEMA_VERSION = 1


def build_ios_link(vk_link: str, peer_address: str, wrap_a_password: str) -> str:
    settings = {
        "useWrapA": True,
        "vkLink": vk_link,
        "peerAddress": peer_address,
        "wrapAPassword": wrap_a_password,
    }
    payload = {
        "version": SCHEMA_VERSION,
        "type": "connection",
        "settings": settings,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"vkturnproxy://import?data={b64}"


def main():
    print("Введите VK-ссылку (https://vk.me/join/... или VK-хеш):")
    vk_link = input("> ").strip()

    print("Введите адрес сервера WRAP-A (host:port):")
    peer_address = input("> ").strip()

    print("Введите wrapAPassword:")
    wrap_a_password = input("> ").strip()

    print("\nСформированная ссылка:")
    print(build_ios_link(vk_link, peer_address, wrap_a_password))


if __name__ == "__main__":
    main()
