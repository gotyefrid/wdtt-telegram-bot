# vkturnbot — Техническое задание

## Назначение

Telegram-бот для автоматизации создания новых WireGuard-клиентов через 3x-ui API и генерации готовой ссылки `vkturnproxy://` для приложения vkturnproxy.

---

## Стек

- Python 3.x
- `python-telegram-bot` (или `aiogram`)
- `httpx` для работы с 3x-ui API
- `cryptography` или `PyNaCl` для генерации WireGuard-ключей (Curve25519)
- `link.py` — готовая функция `build_link(settings)` для сборки ссылки

---

## Конфигурация (`.env`)

| Параметр | Описание | Пример |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота | `123456:ABC-DEF...` |
| `ALLOWED_USERS` | Список Telegram user_id через запятую | `123456789,987654321` |
| `XUI_BASE_URL` | Базовый URL панели 3x-ui | `https://46.32.185.135:48151` |
| `XUI_API_TOKEN` | API-токен 3x-ui | `Co6Bf05y...` |
| `XUI_VERIFY_SSL` | Проверять TLS (false для self-signed) | `false` |
| `DEFAULT_INBOUND_ID` | ID WireGuard-инбаунда | `3` |
| `WG_PEER_ADDRESS` | Адрес vkturnproxy-сервера для клиентской ссылки | `46.32.185.135:56011` |
| `WG_SERVER_PUBLIC_KEY` | Публичный ключ сервера WireGuard | `XHPFELJys6G/+...` |

---

## Структура инбаунда (id=3)

- Протокол: **WireGuard**, порт 51820
- `settings.peers[]` — массив объектов пиров
- `remark` — строка с именами клиентов через запятую, порядок соответствует индексам в `peers[]`
  - Пример: `alice,bob,charlie` → `peers[0]`=alice, `peers[1]`=bob, `peers[2]`=charlie
- IP-пул: `10.0.0.0/24`; текущие пиры занимают `10.0.0.2–10.0.0.9`, следующий — `10.0.0.10`

---

## Сценарий использования (Happy Path)

```
Пользователь: /newclient
Бот: Введите имя нового клиента:
Пользователь: ivan
Бот: Введите ссылку на VK-звонок:
Пользователь: https://vk.com/call/...
Бот: ⏳ Создаю клиента...
Бот: ✅ Клиент "ivan" создан.
     Ссылка для подключения:
     vkturnproxy://import?data=...
```

---

## Алгоритм создания клиента

### 1. Получить текущий инбаунд

```
GET /panel/api/inbounds/get/{inbound_id}
```

Извлечь из ответа:
- `obj.settings` (уже объект или JSON-строка) → `settings.peers[]`
- `obj.remark` — строка с именами

Определить следующий свободный IP: взять максимальный последний октет из всех `allowedIPs` в `peers[]`, прибавить 1.

### 2. Сгенерировать WireGuard-ключи

```python
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
import base64

private_key_obj = X25519PrivateKey.generate()
private_bytes = private_key_obj.private_bytes_raw()
public_bytes  = private_key_obj.public_key().public_bytes_raw()

private_key_b64 = base64.b64encode(private_bytes).decode()
public_key_b64  = base64.b64encode(public_bytes).decode()
```

### 3. Собрать новый peer

```python
new_peer = {
    "privateKey": private_key_b64,
    "publicKey":  public_key_b64,
    "allowedIPs": [f"10.0.0.{next_ip}/32"],
    "keepAlive": 0,
}
```

### 4. Обновить инбаунд

```
POST /panel/api/inbounds/update/{inbound_id}
```

Тело — полный объект инбаунда с изменениями:
- `settings.peers[]` — добавить `new_peer` в конец массива
- `remark` — добавить `,{client_name}` в конец строки

`settings` должен передаваться как **вложенный JSON-объект** (не строка).

### 5. Сформировать ссылку vkturnproxy

Использовать `build_link()` из `link.py`:

```python
from link import build_link

settings = {
    "privateKey":      private_key_b64,          # приватный ключ нового пира
    "peerPublicKey":   WG_SERVER_PUBLIC_KEY,      # публичный ключ сервера (из конфига)
    "tunnelAddress":   f"10.0.0.{next_ip}/32",   # IP нового пира
    "allowedIPs":      "0.0.0.0/0",
    "vkLink":          vk_call_link,             # ссылка на звонок от пользователя
    "peerAddress":     WG_PEER_ADDRESS,           # адрес vkturnproxy (из конфига)
    "dnsServers":      "1.1.1.1",
    "numConnections":  30,
    "useDTLS":         True,
    "useWrap":         False,
    "wrapKeyHex":      "",
    "useSrtp":         True,
    "useUDP":          False,
}

link = build_link(settings)
```

Отправить `link` пользователю в Telegram.

**Приватный ключ не хранится нигде** — он содержится внутри ссылки и нигде отдельно не сохраняется.

---

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и список команд |
| `/newclient` | Создать нового клиента (диалог: имя → VK-ссылка → готово) |
| `/list` | Показать список клиентов (имена из `remark` с нумерацией) |

---

## Безопасность

- Бот отвечает только пользователям из `ALLOWED_USERS`
- Все секреты — только в `.env`, не в коде
- `XUI_VERIFY_SSL=false` допустим для self-signed сертификата 3x-ui

---

## Открытые вопросы

- [ ] Нужен ли `/deleteclient`?
- [ ] Нужно ли уведомлять в Telegram при ошибке обновления инбаунда?
