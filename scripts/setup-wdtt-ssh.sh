#!/usr/bin/env bash
# Провижининг SSH-доступа для управления wdtt.service ботом wdtt-telegram-bot.
#
# Запускать от root НА ХОСТЕ (не в контейнере) при разворачивании на новом сервере,
# после того как wdtt.service уже установлен и настроен.
#
# Создаёт непривилегированного системного пользователя, ключевую пару ed25519,
# forced-command запись в его authorized_keys (указывает на scripts/wdtt-ctl.sh
# рядом с этим скриптом) и sudo-правило, разрешающее этому пользователю только
# systemctl start/stop/status wdtt.service. Идемпотентен — можно запускать повторно.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CTL_USER="${WDTT_SSH_USER:-wdtt-ctl}"
KEY_PATH="$PROJECT_DIR/secrets/wdtt_ssh_key"
CTL_SCRIPT="$PROJECT_DIR/scripts/wdtt-ctl.sh"
SYSTEMCTL_BIN="$(command -v systemctl)"
CTL_SHELL="$(command -v sh)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите от root: sudo $0" >&2
    exit 1
fi

if ! systemctl list-unit-files 2>/dev/null | grep -q '^wdtt\.service'; then
    echo "Предупреждение: wdtt.service не найден в systemd — убедитесь, что сервис уже установлен." >&2
fi

# 1. Системный пользователь. Шелл должен быть рабочим (не nologin/false):
# sshd запускает forced command как "$SHELL -c command", и nologin эту -c
# команду игнорирует, просто отказывая в доступе — реальную защиту даёт
# сам forced command в authorized_keys (см. ниже), а не шелл.
if ! id "$CTL_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "/home/$CTL_USER" --shell "$CTL_SHELL" "$CTL_USER"
    echo "Создан пользователь $CTL_USER"
else
    echo "Пользователь $CTL_USER уже существует"
fi
usermod --shell "$CTL_SHELL" "$CTL_USER"

install -d -m 700 -o "$CTL_USER" -g "$CTL_USER" "/home/$CTL_USER/.ssh"

# 2. Ключевая пара для бота
mkdir -p "$PROJECT_DIR/secrets"
if [ ! -f "$KEY_PATH" ]; then
    ssh-keygen -t ed25519 -N "" -C "wdtt-telegram-bot-ctl" -f "$KEY_PATH" >/dev/null
    echo "Сгенерирован ключ $KEY_PATH"
else
    echo "Ключ $KEY_PATH уже существует, пропускаю генерацию"
fi
chmod 700 "$PROJECT_DIR/secrets"
chmod 600 "$KEY_PATH"
chmod 644 "$KEY_PATH.pub"

# 2b. Проект обычно лежит под /root (0700) — sshd не сможет даже
# stat'нуть forced-command скрипт для непривилегированного CTL_USER
# ("Permission denied"), пока тот не получит право прохода (execute-bit)
# через все родительские каталоги. Даём точечный ACL только на --x,
# без чтения/листинга — secrets/ и остальные файлы проекта им не
# читаются, т.к. защищены собственными правами.
if ! command -v setfacl >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        apt-get install -y acl
    else
        echo "Установите пакет acl (нужен setfacl) и запустите скрипт снова." >&2
        exit 1
    fi
fi
walk_dir="$(dirname "$CTL_SCRIPT")"
while [ "$walk_dir" != "/" ]; do
    setfacl -m "u:$CTL_USER:--x" "$walk_dir"
    walk_dir="$(dirname "$walk_dir")"
done

# 2c. .env часто оказывается мирочитаемым (644) — с открытым выше
# проходом в /root это стало бы доступно CTL_USER. Закрываем.
if [ -f "$PROJECT_DIR/.env" ]; then
    chmod 600 "$PROJECT_DIR/.env"
fi

# 3. authorized_keys с forced command на scripts/wdtt-ctl.sh
chmod +x "$CTL_SCRIPT"
AUTH_KEYS="/home/$CTL_USER/.ssh/authorized_keys"
PUB_KEY="$(cat "$KEY_PATH.pub")"
FORCED_LINE="command=\"$CTL_SCRIPT\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $PUB_KEY"

touch "$AUTH_KEYS"
if grep -qF "$PUB_KEY" "$AUTH_KEYS" 2>/dev/null; then
    echo "Ключ уже прописан в $AUTH_KEYS"
else
    echo "$FORCED_LINE" >> "$AUTH_KEYS"
    echo "Добавлена запись в $AUTH_KEYS"
fi
chmod 600 "$AUTH_KEYS"
chown -R "$CTL_USER:$CTL_USER" "/home/$CTL_USER/.ssh"

# 4. sudo-правило только на start/stop/status wdtt.service, без пароля
SUDOERS_FILE="/etc/sudoers.d/wdtt-ctl"
cat > "$SUDOERS_FILE" <<EOF
$CTL_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN start wdtt.service, $SYSTEMCTL_BIN stop wdtt.service, $SYSTEMCTL_BIN status wdtt.service
EOF
chmod 440 "$SUDOERS_FILE"
visudo -cf "$SUDOERS_FILE"

echo
echo "Готово. В .env на этом сервере укажите:"
echo "  WDTT_SSH_USER=$CTL_USER"
echo "  WDTT_SSH_HOST=host.docker.internal"
echo "  WDTT_SSH_KEY_PATH=/app/secrets/wdtt_ssh_key"
