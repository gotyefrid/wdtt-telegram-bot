import os

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USERS = [int(x) for x in os.environ.get("ALLOWED_USERS", "").split(",") if x]

WDTT_CONFIG_DIR = os.environ.get("WDTT_CONFIG_DIR", "/etc/wdtt")
WDTT_PUBLIC_IP = os.environ.get("WDTT_PUBLIC_IP", "203.0.113.114")
WDTT_SERVICE_NAME = os.environ.get("WDTT_SERVICE_NAME", "wdtt")
WDTT_PORTS = os.environ.get("WDTT_PORTS", "56000,56001,9000")
WDTT_MAX_BACKUPS = int(os.environ.get("WDTT_MAX_BACKUPS", "20"))
WDTT_SSH_HOST = os.environ.get("WDTT_SSH_HOST", "host.docker.internal")
WDTT_SSH_USER = os.environ.get("WDTT_SSH_USER", "wdtt-ctl")
WDTT_SSH_KEY_PATH = os.environ.get("WDTT_SSH_KEY_PATH", "/app/secrets/wdtt_ssh_key")

# iPhone: WireGuard-клиенты в 3x-ui (см. xui.py)
XUI_BASE_URL = os.environ.get("XUI_BASE_URL", "")
XUI_TOKEN = os.environ.get("XUI_TOKEN", "")
XUI_INBOUND_ID = int(os.environ.get("XUI_INBOUND_ID", "3"))
XUI_VERIFY_TLS = os.environ.get("XUI_VERIFY_TLS", "1") != "0"
IOS_PEER_ADDRESS = os.environ.get("IOS_PEER_ADDRESS", "")
IOS_DNS = os.environ.get("IOS_DNS", "1.1.1.1")
IOS_NUM_CONNECTIONS = int(os.environ.get("IOS_NUM_CONNECTIONS", "30"))
