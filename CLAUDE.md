# vkturntgbot — Документация проекта

## Назначение

Telegram-бот для управления клиентами сервиса `wdtt.service` (`wdtt.py`). Пишет
напрямую в `/etc/wdtt/passwords.json` (смонтирован в контейнер), вокруг каждой
записи/удаления останавливает и поднимает сервис по SSH. На каждого клиента
генерирует сразу две ссылки на один и тот же `wdtt.service`: `wdtt://`
(Android/WDTT-клиент, `wdtt.py`) и `vkturnproxy://import?data=...` в режиме
SRTP-WRAP-A (iOS-приложение, `ios_link.py`) — обе используют пароль клиента и
один и тот же VK-хеш/ссылку, разница только в порте и формате.

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
| `ios_link.py` | `build_ios_link(vk_link, peer_address, wrap_a_password)` — сборка `vkturnproxy://` ссылки для iOS в режиме SRTP-WRAP-A (урезанный `quick_link.py` из anton48/vk-turn-proxy-ios, только этот режим). `peer_address` = `wdtt.ios_peer_address()` (адрес `wdtt.service`, порт 56000), `wrap_a_password` = пароль клиента |
| `config.py` | Конфиг из переменных окружения |
| `.env` | Секреты и настройки (не в git) |
| `docker-compose.yml` | Сервис `vkturntgbot`: монтирует `.` в `/app` и `/etc/wdtt` в `/etc/wdtt` |
| `settings.json` | Переопределённый через бота домен/IP для ссылок (не в git, создаётся автоматически). Если файла/ключа нет — используется `WDTT_PUBLIC_IP` из `.env` |
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

- **Создать клиента** → диалог: имя → VK-хеш/ссылка → срок в днях → создаёт запись, возвращает `wdtt://`- и `vkturnproxy://`-ссылки
- **Список клиентов** → кнопки по 2 в ряд (имя или `AAAA...ZZZZ`, если имя не задано) → карточка клиента
- **Получить ссылку** → без диалога обе ссылки, если VK-хеш уже сохранён; иначе один раз спрашивает и сохраняет
- **Редактировать** → подменю из карточки клиента с четырьмя пунктами:
  - **Переименовать** → диалог: новое имя → `wdtt.set_name`
  - **VK-хеш** → диалог: новый VK-хеш/ссылка (та же валидация, что при создании) → `wdtt.set_vk_hash`, перезаписывает уже сохранённый хеш
  - **Статус** → экран с текущим статусом и одной кнопкой-переключателем (Активировать/Деактивировать) → `wdtt.set_deactivated`; переключает только флаг `is_deactivated`, статус «истёк» не трогает (он вычисляется из `expires_at`)
  - **Срок** → диалог: число дней 1–365 (как при создании) → `wdtt.set_expires_days`, пересчитывает `expires_at` = текущее время + N дней (не прибавляет к старому сроку, а задаёт новый от текущего момента)
  - Все пункты после сохранения возвращают на карточку клиента
- **Удалить** → подтверждение → удаление записи + связанного устройства
- **Настройки** → **Изменить домен** → диалог: новый домен/IP → `wdtt.set_public_domain` (сохраняется в `settings.json`, подставляется во все новые ссылки вместо `WDTT_PUBLIC_IP`); доступно в любой момент из главного меню, вне диалога создания клиента

В карточке клиента срок действия показывается с количеством оставшихся дней в
скобках, например `до 01.08.2026 12:00 (9 дн.)` (округление вверх, минимум 0).

После каждого создания/переименования/задания VK-хеша/удаления клиента бот
шлёт всем `ALLOWED_USERS` архив `passwords.json`+`names.json`+`settings.json`
(`bot.send_backup`, `wdtt.backup_archive`) беззвучным сообщением
(`disable_notification=True`) — бекап без отдельного крона.

## FSM-состояния

| Состояние | Что ждёт |
|---|---|
| `NewClient.waiting_name` → `.waiting_vk_hash` → `.waiting_days` | Имя → VK-хеш/ссылка → срок в днях (1–365) для нового клиента |
| `GetLink.waiting_vk_hash` | VK-хеш для клиента, если он ещё не задан |
| `Rename.waiting_name` | Новое имя клиента (пункт «Переименовать» в меню «Редактировать») |
| `EditClient.waiting_vk_hash` | Новый VK-хеш/ссылка для уже существующего клиента (перезаписывает старый) |
| `EditClient.waiting_days` | Новый срок действия в днях (1–365) от текущего момента |
| `Settings.waiting_domain` | Новый домен/IP для ссылок |

## Валидация

- **Имя**: `re.sub(r"[^a-zA-Z0-9_-]", "", raw)` — всё лишнее удаляется; если результат пустой — ошибка
- **VK-хеш/ссылка**: не валидируется строго, принимается любая непустая строка

## wdtt.py — ключевые функции

```python
list_clients()                             # [{password, name, vk_hash, expires_at, is_deactivated, device_id, ip}, ...]
get_client(password)                       # детальная запись одного клиента
add_client(name, vk_hash, expires_days)    # создаёт запись, возвращает {password, vk_hash}
delete_client(password)                    # удаляет запись (+ связанное устройство), возвращает name
set_vk_hash(password, vk_hash)             # задаёт/перезаписывает VK-хеш
set_name(password, name)                   # задаёт/меняет имя клиента (используется и кнопкой "Переименовать")
set_deactivated(password, is_deactivated)  # переключает флаг is_deactivated (кнопка "Статус")
set_expires_days(password, expires_days)   # задаёт expires_at = сейчас + N дней (кнопка "Срок")
build_wdtt_link(password, vk_hash)         # wdtt://domain:56000:56001:9000:password:vk_hash
short_password(password)                   # "AAAA...ZZZZ" — заглушка вместо имени в списке
backup_archive()                           # (bytes, filename) — tar.gz из passwords.json+names.json+settings.json в памяти
get_public_domain()                        # домен/IP для ссылок: settings.json, иначе WDTT_PUBLIC_IP
set_public_domain(domain)                  # сохраняет домен/IP в settings.json
```

Мутирующие функции (`add_client`, `delete_client`, `set_vk_hash`,
`set_deactivated`, `set_expires_days`) оборачивают
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
- Порты и путь конфига фиксированы через `.env`, диалогом не настраиваются
