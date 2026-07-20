# vkturntgbot — Документация проекта

## Назначение

Telegram-бот для управления клиентами сервиса `wdtt.service` (`wdtt.py`). Пишет
напрямую в `/etc/wdtt/passwords.json` (смонтирован в контейнер), вокруг каждой
записи/удаления останавливает и поднимает сервис по SSH. Генерирует ссылки
`wdtt://`.

## Запуск

```bash
docker compose up -d --build   # сборка и запуск
docker compose restart         # перезапуск без пересборки
docker logs vkturntgbot        # логи
```

## Структура файлов

| Файл | Назначение |
|---|---|
| `bot.py` | Telegram-бот: хендлеры команд, колбэков, FSM-диалоги |
| `wdtt.py` | Прямая работа с `/etc/wdtt/passwords.json` + SSH-управление `wdtt.service` |
| `config.py` | Конфиг из переменных окружения |
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
| `WDTT_CONFIG_DIR` | Путь к конфигу wdtt в контейнере (`/etc/wdtt`) |
| `WDTT_PUBLIC_IP` | Публичный IP для ссылок `wdtt://` |
| `WDTT_SERVICE_NAME` | Имя systemd-юнита (`wdtt`) |
| `WDTT_SSH_HOST` / `WDTT_SSH_USER` / `WDTT_SSH_KEY_PATH` | SSH-доступ к хосту для start/stop/status сервиса. `WDTT_SSH_USER` — непривилегированный пользователь `wdtt-ctl`, создаётся `scripts/setup-wdtt-ssh.sh` |

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Главное меню с инлайн-кнопками |
| `/cancel` | Отменить текущий FSM-диалог |

Основное взаимодействие — через инлайн-кнопки:

- **Создать клиента** → диалог: имя → VK-хеш/ссылка → срок в днях → создаёт запись, возвращает `wdtt://`-ссылку
- **Список клиентов** → кнопки по 2 в ряд (имя или `AAAA...ZZZZ`, если имя не задано) → карточка клиента
- **Получить ссылку** → без диалога, если VK-хеш уже сохранён; иначе один раз спрашивает и сохраняет
- **Удалить** → подтверждение → удаление записи + связанного устройства

## FSM-состояния

| Состояние | Что ждёт |
|---|---|
| `NewClient.waiting_name` → `.waiting_vk_hash` → `.waiting_days` | Имя → VK-хеш/ссылка → срок в днях (1–365) для нового клиента |
| `GetLink.waiting_vk_hash` | VK-хеш для клиента, если он ещё не задан |

## Валидация

- **Имя**: `re.sub(r"[^a-zA-Z0-9_-]", "", raw)` — всё лишнее удаляется; если результат пустой — ошибка
- **VK-хеш/ссылка**: не валидируется строго, принимается любая непустая строка

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

- Лимита на число клиентов нет (в отличие от `maxGeneratedPasswords=10` у встроенного self-service бота оригинального сервера — он на нашу логику не распространяется)
- Активация/деактивация клиента не реализована — только создание/удаление/ссылка
- Порты и путь конфига фиксированы через `.env`, диалогом не настраиваются
