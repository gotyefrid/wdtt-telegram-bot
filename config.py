import os

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USERS = [int(x) for x in os.environ.get("ALLOWED_USERS", "").split(",") if x]

WDTT_CONFIG_DIR = os.environ.get("WDTT_CONFIG_DIR", "/etc/wdtt")
WDTT_PUBLIC_IP = os.environ.get("WDTT_PUBLIC_IP", "46.32.185.135")
WDTT_SERVICE_NAME = os.environ.get("WDTT_SERVICE_NAME", "wdtt")
WDTT_SSH_HOST = os.environ.get("WDTT_SSH_HOST", "host.docker.internal")
WDTT_SSH_USER = os.environ.get("WDTT_SSH_USER", "wdtt-ctl")
WDTT_SSH_KEY_PATH = os.environ.get("WDTT_SSH_KEY_PATH", "/app/secrets/wdtt_ssh_key")
