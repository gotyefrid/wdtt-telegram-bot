import os

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USERS = [int(x) for x in os.environ.get("ALLOWED_USERS", "").split(",") if x]
XUI_BASE_URL = os.environ.get("XUI_BASE_URL", "https://46.32.185.135:48151")
XUI_API_TOKEN = os.environ["XUI_API_TOKEN"]
DEFAULT_INBOUND_ID = int(os.environ.get("DEFAULT_INBOUND_ID", "3"))
XUI_VERIFY_SSL = os.environ.get("XUI_VERIFY_SSL", "false").lower() == "true"
WG_SERVER_PUBLIC_KEY = os.environ["WG_SERVER_PUBLIC_KEY"]
WG_PEER_ADDRESS = os.environ["WG_PEER_ADDRESS"]
