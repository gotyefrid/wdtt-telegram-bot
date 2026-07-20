#!/usr/bin/env bash
# Бекапит /etc/wdtt/{passwords,names}.json в архив и шлёт его в Telegram
# беззвучным сообщением (disable_notification=true). Предназначен для cron
# на хосте (не в контейнере), поэтому конфиг читает из .env сам.
#
# Пример crontab (раз в сутки в 04:00):
#   0 4 * * * /path/to/bot/scripts/backup-to-telegram.sh >> /var/log/wdtt-backup.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN не задан в .env}"

# Кому слать бекап: отдельная переменная TELEGRAM_BACKUP_CHAT_ID,
# иначе — первый id из ALLOWED_USERS.
CHAT_ID="${TELEGRAM_BACKUP_CHAT_ID:-${ALLOWED_USERS%%,*}}"
if [[ -z "${CHAT_ID:-}" ]]; then
    echo "Не удалось определить chat_id: задайте TELEGRAM_BACKUP_CHAT_ID или ALLOWED_USERS в .env" >&2
    exit 1
fi

WDTT_DIR="${WDTT_CONFIG_DIR:-/etc/wdtt}"
STAMP="$(date +%Y%m%d_%H%M%S)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ARCHIVE="${TMP_DIR}/wdtt-backup-${STAMP}.tar.gz"

FILES=()
for f in passwords.json names.json; do
    [[ -f "${WDTT_DIR}/${f}" ]] && FILES+=("${f}")
done

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "Нет файлов для бекапа в ${WDTT_DIR}" >&2
    exit 1
fi

tar -czf "$ARCHIVE" -C "$WDTT_DIR" "${FILES[@]}"

HTTP_CODE="$(curl -sS -o /tmp/wdtt-backup-response.$$ -w '%{http_code}' \
    -F "chat_id=${CHAT_ID}" \
    -F "disable_notification=true" \
    -F "document=@${ARCHIVE}" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument")"

if [[ "$HTTP_CODE" != "200" ]]; then
    echo "Ошибка отправки в Telegram (HTTP ${HTTP_CODE}):" >&2
    cat /tmp/wdtt-backup-response.$$ >&2
    rm -f /tmp/wdtt-backup-response.$$
    exit 1
fi
rm -f /tmp/wdtt-backup-response.$$

echo "Бекап отправлен: ${ARCHIVE##*/}"
