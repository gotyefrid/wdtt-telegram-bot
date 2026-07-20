#!/bin/sh
# Forced command для SSH-ключа vkturntgbot-wdtt-ctl (см. scripts/setup-wdtt-ssh.sh).
# Разбирает $SSH_ORIGINAL_COMMAND по белому списку и вызывает systemctl через sudo.
# Любая другая команда — отказ.
set -eu

SYSTEMCTL="$(command -v systemctl)"
SERVICE="wdtt.service"

case "${SSH_ORIGINAL_COMMAND:-}" in
    start|stop|status)
        exec sudo -n "$SYSTEMCTL" "$SSH_ORIGINAL_COMMAND" "$SERVICE"
        ;;
    *)
        echo "wdtt-ctl: недопустимая команда: ${SSH_ORIGINAL_COMMAND:-<пусто>}" >&2
        exit 1
        ;;
esac
