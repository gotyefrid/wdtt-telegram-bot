#!/usr/bin/env bash
# Провижининг SSH-доступа для управления wdtt.service ботом vkturntgbot.
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
NOLOGIN_BIN="$(command -v nologin || echo /usr/sbin/nologin)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Запустите от root: sudo $0" >&2
    exit 1
fi

if ! systemctl list-unit-files 2>/dev/null | grep -q '^wdtt\.service'; then
    echo "Предупреждение: wdtt.service не найден в systemd — убедитесь, что сервис уже установлен." >&2
fi

# 1. Системный пользователь без интерактивного логина
if ! id "$CTL_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "/home/$CTL_USER" --shell "$NOLOGIN_BIN" "$CTL_USER"
    echo "Создан пользователь $CTL_USER"
else
    echo "Пользователь $CTL_USER уже существует"
fi

install -d -m 700 -o "$CTL_USER" -g "$CTL_USER" "/home/$CTL_USER/.ssh"

# 2. Ключевая пара для бота
mkdir -p "$PROJECT_DIR/secrets"
if [ ! -f "$KEY_PATH" ]; then
    ssh-keygen -t ed25519 -N "" -C "vkturntgbot-wdtt-ctl" -f "$KEY_PATH" >/dev/null
    echo "Сгенерирован ключ $KEY_PATH"
else
    echo "Ключ $KEY_PATH уже существует, пропускаю генерацию"
fi
chmod 600 "$KEY_PATH"
chmod 644 "$KEY_PATH.pub"

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
