# wdtt-telegram-bot

Telegram-бот для управления клиентами сервиса `wdtt.service` (сервер —
[proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android))
— генерирует пароли/ссылки для подключения через VK-звонки (обход
блокировок), умеет создавать, редактировать, деактивировать и удалять
клиентов прямо из Telegram, без ручной правки конфигов на сервере.

На каждого клиента бот выдаёт `wdtt://...`-ссылку на подключение к
`wdtt.service` (Android/WDTT-клиент; тот же формат понимает и iOS-приложение).

## Возможности

- Создание клиента: имя → VK-хеш/ссылка на звонок → срок действия в днях;
- список клиентов с карточкой (статус, срок, оставшиеся дни, устройство);
- редактирование клиента: переименовать, сменить VK-хеш, продлить срок,
  активировать/деактивировать;
- удаление клиента;
- QR-код для ссылки;
- смена публичного домена/IP для ссылок прямо из бота;
- автоматический бэкап конфигов в Telegram при каждом изменении клиента.

## Требования

- Уже установленный и настроенный **`wdtt.service`** на хосте (Docker-контейнер
  бота в само́м сервисе не нуждается — только читает/пишет его конфиг и
  управляет им по SSH). Сам сервис — сервер из проекта
  [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android),
  устанавливается отдельно. Проверьте, что сервис работает: `systemctl status wdtt`.
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

### 3. Запустить

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

## Структура проекта

| Файл | Назначение |
|---|---|
| `bot.py` | Telegram-бот: хендлеры команд, колбэков, FSM-диалоги |
| `wdtt.py` | Прямая работа с `/etc/wdtt/passwords.json` + SSH-управление `wdtt.service` |
| `config.py` | Конфиг из переменных окружения |
| `.env` | Секреты и настройки (создаётся из `.env.example`, не в git) |
| `docker-compose.yml` | Сервис `wdtt-telegram-bot`: монтирует `.` в `/app` и `/etc/wdtt` в `/etc/wdtt` |
| `settings.json` | Переопределённый через бота домен/IP (создаётся автоматически, не в git) |
| `secrets/wdtt_ssh_key` | Приватный SSH-ключ для управления `wdtt.service` (не в git) |
| `backups/wdtt/` | Локальные бэкапы `passwords.json` перед каждой записью (не в git) |
| `scripts/setup-wdtt-ssh.sh` | Провижининг SSH-доступа (см. шаг 2 выше) |
| `scripts/wdtt-ctl.sh` | Forced-command скрипт на стороне хоста, вызывается по SSH |

Подробное описание команд бота, FSM-состояний и внутреннего API `wdtt.py` —
в [`CLAUDE.md`](CLAUDE.md).

## Известные ограничения

- Лимит на число клиентов ограничен количеством доступных IP-адресов WireGuard;
- порты и путь конфига настраиваются только через `.env`, диалогом бота — нет;
- бот рассчитан на одиночный `wdtt.service` на том же хосте, где запущен
  контейнер (управление по SSH на `host.docker.internal`).
