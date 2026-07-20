# vkturntgbot — Документация проекта

## Назначение

Telegram-бот для управления клиентами VPN. Работает в двух независимых режимах,
выбираемых в UI кнопками «🍏 Apple» / «📡 WDTT» на экранах создания и списка клиентов:

- **Apple** — WireGuard-клиенты через панель 3x-ui (`xui.py`). Создаёт пиров в
  инбаунде, генерирует ссылки `vkturnproxy://` для приложения vkturnproxy.
- **WDTT** — клиенты сервиса `wdtt.service` на хосте (`wdtt.py`). Пишет
  напрямую в `/etc/wdtt/passwords.json` (смонтирован в контейнер), вокруг
  каждой записи/удаления останавливает и поднимает сервис по SSH. Генерирует
  ссылки `wdtt://`.

## Запуск

```bash
docker compose up -d --build   # сборка и запуск
docker compose restart         # перезапуск без пересборки
docker logs vkturntgbot        # логи
```

## Структура файлов

| Файл | Назначение |
|---|---|
| `bot.py` | Telegram-бот: хендлеры команд, колбэков, FSM-диалоги (Apple + WDTT) |
| `xui.py` | Клиент 3x-ui API: получение/обновление инбаунда, CRUD пиров (Apple) |
| `wdtt.py` | Прямая работа с `/etc/wdtt/passwords.json` + SSH-управление `wdtt.service` (WDTT) |
| `config.py` | Конфиг из переменных окружения |
| `link.py` | `build_link(settings)` — сборка `vkturnproxy://import?data=...` (Apple) |
| `.env` | Секреты и настройки (не в git) |
| `docker-compose.yml` | Сервис `vkturntgbot`: монтирует `.` в `/app` и `/etc/wdtt` в `/etc/wdtt` |
| `secrets/wdtt_ssh_key` | Приватный ключ для forced-command SSH к хосту (не в git) |
| `backups/wdtt/` | Бэкапы `passwords.json` перед каждой записью (не в git) |
| `scripts/setup-wdtt-ssh.sh` | Провижининг SSH-доступа к `wdtt.service` при разворачивании на новом сервере: создаёт пользователя `wdtt-ctl`, ключ, forced-command и sudo-правило. Запускать от root на хосте один раз, идемпотентен |
| `scripts/wdtt-ctl.sh` | Forced-command скрипт, на который указывает ключ из `setup-wdtt-ssh.sh`; разбирает `start`/`stop`/`status` и вызывает `systemctl` через `sudo` |

## Переменные окружения (.env)

| Переменная | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота |
| `ALLOWED_USERS` | Telegram user_id через запятую |
| `XUI_BASE_URL` | URL панели 3x-ui (`https://46.32.185.135:48151`) |
| `XUI_API_TOKEN` | Bearer-токен для 3x-ui API |
| `DEFAULT_INBOUND_ID` | ID WireGuard-инбаунда (сейчас `3`) |
| `XUI_VERIFY_SSL` | `false` — отключить проверку self-signed TLS |
| `WG_SERVER_PUBLIC_KEY` | Публичный ключ WireGuard-сервера (для клиентской ссылки) |
| `WG_PEER_ADDRESS` | Адрес vkturnproxy-сервера (`46.32.185.135:56011`) |
| `WDTT_CONFIG_DIR` | Путь к конфигу wdtt в контейнере (`/etc/wdtt`) |
| `WDTT_PUBLIC_IP` | Публичный IP для ссылок `wdtt://` |
| `WDTT_SERVICE_NAME` | Имя systemd-юнита (`wdtt`) |
| `WDTT_SSH_HOST` / `WDTT_SSH_USER` / `WDTT_SSH_KEY_PATH` | SSH-доступ к хосту для start/stop/status сервиса. `WDTT_SSH_USER` — непривилегированный пользователь `wdtt-ctl`, создаётся `scripts/setup-wdtt-ssh.sh` |

## Инбаунд WireGuard (id=3)

- Протокол `wireguard`, порт `51820`
- `settings.peers[]` — массив пиров, каждый: `privateKey`, `publicKey`, `allowedIPs`, `keepAlive`
- `remark` — имена клиентов через запятую, порядок = порядок peers
  - Формат имени: `{N}-{name}`, например `9-ivan`
- IP-пул: `10.0.0.2–10.0.0.254` (следующий берётся как max + 1)

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Главное меню с инлайн-кнопками |
| `/cancel` | Отменить текущий FSM-диалог |

Основное взаимодействие — через инлайн-кнопки. И «Создать клиента», и «Список
клиентов» сначала показывают экран выбора типа (🍏 Apple / 📡 WDTT), дальше — два
независимых флоу:

Apple:
- **Создать клиента** → диалог: имя → VK-ссылка → создаёт пира, возвращает ссылку
- **Список клиентов** → кнопки по 2 в ряд → действия с клиентом
- **Получить ссылку** → запрашивает VK-ссылку, генерирует `vkturnproxy://` из сохранённого ключа
- **Удалить** → подтверждение → удаление пира из инбаунда

WDTT:
- **Создать клиента** → диалог: имя → VK-хеш/ссылка → срок в днях → создаёт запись, возвращает `wdtt://`-ссылку
- **Список клиентов** → кнопки по 2 в ряд (имя или `AAAA...ZZZZ`, если имя не задано) → карточка клиента
- **Получить ссылку** → без диалога, если VK-хеш уже сохранён; иначе один раз спрашивает и сохраняет
- **Удалить** → подтверждение → удаление записи + связанного устройства

## FSM-состояния

| Состояние | Что ждёт |
|---|---|
| `NewClient.waiting_name` | Имя нового Apple-клиента (латиница, цифры, `-`, `_`) |
| `NewClient.waiting_vk_link` | VK-ссылка для нового Apple-клиента |
| `GetLink.waiting_vk_link` | VK-ссылка для существующего Apple-клиента |
| `NewClientWdtt.waiting_name` → `.waiting_vk_hash` → `.waiting_days` | Имя → VK-хеш/ссылка → срок в днях (1–365) для нового WDTT-клиента |
| `GetLinkWdtt.waiting_vk_hash` | VK-хеш для WDTT-клиента, если он ещё не задан |

## Валидация

- **Имя**: `re.sub(r"[^a-zA-Z0-9_-]", "", raw)` — всё лишнее удаляется; если результат пустой — ошибка
- **VK-ссылка**: должна начинаться с `https://vk.com/call/join/`; проверяется функцией `_valid_vk_link()`

## xui.py — ключевые функции

```python
list_clients()              # список {index, name, ip} для всех пиров
get_peer(index)             # один пир {index, name, ip, private_key, public_key}
add_peer(name)              # создать пира, вернуть {private_key, public_key, ip}
delete_peer(index)          # удалить пира по 0-based индексу, вернуть имя
```

Все функции бросают `RuntimeError` при ошибке API — бот ловит их и показывает пользователю.

## wdtt.py — ключевые функции

```python
list_clients()                             # [{password, name, vk_hash, expires_at, is_deactivated, device_id, ip}, ...]
get_client(password)                       # детальная запись одного клиента
add_client(name, vk_hash, expires_days)    # создаёт запись, возвращает {password, vk_hash}
delete_client(password)                    # удаляет запись (+ связанное устройство), возвращает name
set_vk_hash(password, vk_hash)             # задаёт VK-хеш, если он был пуст
set_name(password, name)                   # ручной бэкфилл имени для старых клиентов
build_wdtt_link(password, vk_hash)         # wdtt://ip:56000:56001:9000:password:vk_hash
short_password(password)                   # "AAAA...ZZZZ" — заглушка вместо имени в списке
```

Мутирующие функции (`add_client`, `delete_client`, `set_vk_hash`) оборачивают
изменение `passwords.json` в процедуру backup → SSH `stop` → запись файла →
SSH `start` → SSH `status`, т.к. сам сервис периодически перезаписывает файл
и может затереть параллельную правку. **Имена клиентов хранятся отдельно** —
в `/etc/wdtt/names.json`, а не в `passwords.json`: у Go-сервера в структуре
`PasswordEntry` нет поля `name`, и он стирает незнакомые поля при каждом
собственном сохранении (срабатывает при подключении клиента). `names.json`
сервис не трогает, поэтому `set_name`/`get_client` читают и пишут его
напрямую, без stop/start.

## Известные ограничения

Apple:
- Максимум **198 клиентов** (лимит Telegram: 100 кнопок, по 2 в ряд, минус кнопка меню)
- Максимум **253 пира** по IP-пулу (`10.0.0.2–10.0.0.254`)
- Приватный ключ клиента нигде не хранится отдельно — он внутри `vkturnproxy://` ссылки и в `settings.peers[]` в 3x-ui

WDTT:
- Лимита на число клиентов нет (в отличие от `maxGeneratedPasswords=10` у встроенного self-service бота оригинального сервера — он на нашу логику не распространяется)
- Активация/деактивация клиента не реализована — только создание/удаление/ссылка
- Порты и путь конфига фиксированы через `.env`, диалогом не настраиваются
