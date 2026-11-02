# wdtt-telegram-bot

Telegram-бот — единая точка управления клиентами двух серверов, работающих через
VK-звонки (обход блокировок). Умеет создавать, редактировать, деактивировать и
удалять клиентов прямо из Telegram, без ручной правки конфигов на сервере.

| Тип клиента | Сервер | Что выдаёт бот |
|---|---|---|
| 🤖 **WDTT** | `wdtt.service` ([proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android)) | `wdtt://...`-ссылка (Android/WDTT-клиент; тот же формат понимает и iOS-приложение) |
| 📱 **iPhone** | [vk-turn-proxy](https://github.com/anton48/vk-turn-proxy) (SRTP) + WireGuard-вход в **3x-ui**, клиент — [vk-turn-proxy-ios](https://github.com/anton48/vk-turn-proxy-ios) | `vkturnproxy://`-ссылка для импорта в приложение одним нажатием |

Тип выбирается при создании клиента. Если у человека несколько устройств — создаётся
по клиенту каждого типа. Оба типа живут в одном списке и редактируются одинаково.

## Возможности

- Создание клиента: тип (WDTT / iPhone) → имя → VK-хеш/ссылка на звонок → срок действия в днях;
- общий список клиентов обоих типов с карточкой (статус, срок, оставшиеся дни,
  устройство у WDTT / IP в туннеле и трафик у iPhone);
- редактирование клиента: переименовать (только WDTT), сменить VK-хеш, продлить срок,
  активировать/деактивировать;
- удаление клиента;
- QR-код для WDTT-ссылки (для iPhone QR не строится: в ссылке приватный ключ WireGuard);
- если при создании iPhone-клиента такое имя уже занято в 3x-ui, к нему дописываются
  дата и время (`Test` → `Test_02112026_14_25`);
- смена публичного домена/IP для WDTT-ссылок прямо из бота;
- автоматический бэкап конфигов WDTT в Telegram при каждом изменении клиента.

## Требования

- Уже установленный и настроенный **`wdtt.service`** на хосте (Docker-контейнер
  бота в само́м сервисе не нуждается — только читает/пишет его конфиг и
  управляет им по SSH). Сам сервис — сервер из проекта
  [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android),
  устанавливается отдельно. Проверьте, что сервис работает: `systemctl status wdtt`.
- Для клиентов iPhone — **3x-ui** (панель с API-токеном) с WireGuard-входом и запущенный
  серверный `vk-turn-proxy` (подробности в разделе «Клиенты iPhone» ниже). Если iPhone
  не нужен, 3x-ui не требуется: оставьте `XUI_*` пустыми, и бот будет работать только с WDTT
  (в списке клиентов появится предупреждение об iPhone).
- Docker и Docker Compose на этом же хосте.
- Токен Telegram-бота от [@BotFather](https://t.me/BotFather).
- Свой Telegram user_id (например, от [@userinfobot](https://t.me/userinfobot)).

## Быстрый старт

Все команды — от `root` на хосте, где уже крутится `wdtt.service`.

```bash
git clone https://github.com/gotyefrid/wdtt-telegram-bot.git /root/wdtt-telegram-bot
cd /root/wdtt-telegram-bot
```

### 1. Настроить `.env`

```bash
cp .env.example .env
```

Заполните `.env`:

| Переменная | Что указать |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather |
| `ALLOWED_USERS` | Ваш Telegram user_id (через запятую, если админов несколько) |
| `WDTT_CONFIG_DIR` | Обычно не меняется, `/etc/wdtt` |
| `WDTT_PUBLIC_IP` | Публичный IP/домен сервера, на котором запускается бот |
| `WDTT_SERVICE_NAME` | Имя systemd-юнита `wdtt.service`, обычно `wdtt` |
| `WDTT_PORTS` | Три порта `wdtt.service` через запятую, обычно не меняются (`56000,56001,9000`) |
| `WDTT_SSH_HOST` / `WDTT_SSH_USER` / `WDTT_SSH_KEY_PATH` | Не трогать — настраиваются автоматически следующим шагом |
| `XUI_BASE_URL` | Адрес панели 3x-ui вместе с base path: `https://домен:2053/<path>` |
| `XUI_TOKEN` | API-токен 3x-ui (см. ниже) |
| `XUI_INBOUND_ID` | ID WireGuard-входа в 3x-ui (по умолчанию `3`) |
| `XUI_VERIFY_TLS` | `0` — не проверять сертификат панели (по умолчанию проверяется) |
| `IOS_PEER_ADDRESS` | Адрес серверного `vk-turn-proxy` для ссылок iPhone: `домен:56100` |
| `IOS_DNS` / `IOS_NUM_CONNECTIONS` | DNS и число соединений в ссылке iPhone (`1.1.1.1`, `30`) |

### 2. Дать боту доступ к управлению `wdtt.service`

Контейнер без привилегий и не может напрямую дёргать systemd хоста, поэтому
старт/стоп сервиса при записи конфига идёт по SSH с максимально урезанными
правами (forced command, без шелла и sudo-доступа к чему-либо кроме этого
одного сервиса). Настраивается одной командой:

```bash
sudo ./scripts/setup-wdtt-ssh.sh
```

Скрипт идемпотентен (можно запускать повторно) и создаёт:
- системного пользователя `wdtt-ctl`;
- SSH-ключ в `secrets/wdtt_ssh_key` (примонтируется в контейнер);
- forced-command в `authorized_keys`, разрешающий **только** `start`/`stop`/`status`
  для `wdtt.service`;
- sudo-правило, ограниченное теми же тремя командами.

### 3. Клиенты iPhone (3x-ui + vk-turn-proxy)

Нужно один раз подготовить сервер; дальше клиентов создаёт и правит бот.

1. **WireGuard-вход в 3x-ui.** Протокол `wireguard`, listen `127.0.0.1`, порт например
   `51820`, MTU около `1280`. Его ID укажите в `XUI_INBOUND_ID`. Клиентов (пиров) бот
   добавляет сам: ключи и IP в туннеле выдаёт панель, xray при этом не перезапускается.
2. **Серверный `vk-turn-proxy`** (бинарник `server-linux-amd64` из
   [релизов](https://github.com/anton48/vk-turn-proxy/releases)), запущенный сервисом,
   в режиме SRTP, на свободном UDP-порту (не на портах `wdtt.service`):

   ```bash
   ./server-linux-amd64 -listen 0.0.0.0:56100 -connect 127.0.0.1:51820 -srtp
   ```

   Адрес `домен:56100` пропишите в `IOS_PEER_ADDRESS`.
3. **API-токен 3x-ui:** `docker exec <контейнер> /app/x-ui setting -getApiToken` —
   **эта команда сбрасывает прежний токен**, если он уже где-то используется.
   Сам токен — секрет: хранится только в `.env`, не в git.

### 4. Запустить

```bash
docker compose up -d --build
```

Проверить, что бот поднялся:

```bash
docker logs -f wdtt-telegram-bot
```

Дальше — всё через Telegram: `/start` открывает главное меню.

## Обновление

```bash
git pull
docker compose up -d --build
```

После правки `.env` перезапускайте бота через `docker compose up -d`: обычный
`docker compose restart` новые переменные окружения **не подхватывает**.

## Структура проекта

| Файл | Назначение |
|---|---|
| `bot.py` | Telegram-бот: хендлеры команд, колбэков, FSM-диалоги |
| `clients.py` | Общий слой над типами клиентов: WDTT и iPhone адресуются единообразно |
| `wdtt.py` | Прямая работа с `/etc/wdtt/passwords.json` + SSH-управление `wdtt.service` |
| `xui.py` | Клиенты iPhone: API 3x-ui (создание/правка/удаление пира WireGuard), сборка `vkturnproxy://`-ссылки |
| `config.py` | Конфиг из переменных окружения |
| `.env` | Секреты и настройки (создаётся из `.env.example`, не в git) |
| `docker-compose.yml` | Сервис `wdtt-telegram-bot`: монтирует `.` в `/app` и `/etc/wdtt` в `/etc/wdtt` |
| `settings.json` | Переопределённый через бота домен/IP (создаётся автоматически, не в git) |
| `secrets/wdtt_ssh_key` | Приватный SSH-ключ для управления `wdtt.service` (не в git) |
| `backups/wdtt/` | Локальные бэкапы `passwords.json` перед каждой записью (не в git); iPhone-клиенты хранятся в БД 3x-ui и в этих бэкапах не участвуют |
| `scripts/setup-wdtt-ssh.sh` | Провижининг SSH-доступа (см. шаг 2 выше) |
| `scripts/wdtt-ctl.sh` | Forced-command скрипт на стороне хоста, вызывается по SSH |

Подробное описание команд бота, FSM-состояний и внутреннего API `wdtt.py` / `xui.py` —
в [`CLAUDE.md`](CLAUDE.md).

## Известные ограничения

- Лимит на число клиентов ограничен количеством доступных IP-адресов WireGuard;
- порты и путь конфига настраиваются только через `.env`, диалогом бота — нет;
- iPhone-клиента нельзя переименовать (имя — это его email в 3x-ui, длиной до 32 символов,
  уникальный во всей панели);
- бот рассчитан на одиночный `wdtt.service` на том же хосте, где запущен
  контейнер (управление по SSH на `host.docker.internal`).
