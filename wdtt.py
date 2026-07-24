import io
import json
import os
import secrets
import subprocess
import tarfile
import time
from datetime import datetime

from config import (
    WDTT_CONFIG_DIR,
    WDTT_PUBLIC_IP,
    WDTT_PORTS,
    WDTT_MAX_BACKUPS,
    WDTT_SSH_HOST,
    WDTT_SSH_USER,
    WDTT_SSH_KEY_PATH,
)

PASS_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"

_PASSWORDS_FILE = os.path.join(WDTT_CONFIG_DIR, "passwords.json")
_NAMES_FILE = os.path.join(WDTT_CONFIG_DIR, "names.json")
_BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups", "wdtt")
_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


# ---------------------------------------------------------------------------
# Low-level file helpers
# ---------------------------------------------------------------------------

def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _write_json_atomic(path: str, data: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _read_passwords() -> dict:
    return _read_json(_PASSWORDS_FILE, {"passwords": {}, "devices": {}})


def _write_passwords_atomic(data: dict) -> None:
    _write_json_atomic(_PASSWORDS_FILE, data)


def _read_names() -> dict:
    return _read_json(_NAMES_FILE, {})


def _write_names_atomic(data: dict) -> None:
    _write_json_atomic(_NAMES_FILE, data)


def _read_settings() -> dict:
    return _read_json(_SETTINGS_FILE, {})


def get_public_domain() -> str:
    """Домен/IP, подставляемый в ссылки. Переопределяется через бота (settings.json),
    по умолчанию — WDTT_PUBLIC_IP из .env."""
    return _read_settings().get("public_domain") or WDTT_PUBLIC_IP


def set_public_domain(domain: str) -> None:
    settings = _read_settings()
    settings["public_domain"] = domain
    _write_json_atomic(_SETTINGS_FILE, settings)


def get_backups_enabled() -> bool:
    """Включена ли отправка бекапов в Telegram при изменении клиентов (по умолчанию — нет)."""
    return bool(_read_settings().get("backups_enabled", False))


def set_backups_enabled(enabled: bool) -> None:
    settings = _read_settings()
    settings["backups_enabled"] = enabled
    _write_json_atomic(_SETTINGS_FILE, settings)


def _backup() -> None:
    os.makedirs(_BACKUP_DIR, exist_ok=True)
    data = _read_json(_PASSWORDS_FILE, None)
    if data is None:
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(_BACKUP_DIR, f"{stamp}_passwords.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(dest, 0o600)
    _prune_backups()


def _prune_backups() -> None:
    """Оставляет не больше WDTT_MAX_BACKUPS файлов в _BACKUP_DIR, удаляя самые
    старые (имена начинаются с timestamp'а, поэтому сортировка по имени —
    она же сортировка по времени)."""
    files = sorted(f for f in os.listdir(_BACKUP_DIR) if f.endswith("_passwords.json"))
    excess = len(files) - WDTT_MAX_BACKUPS
    if excess <= 0:
        return
    for f in files[:excess]:
        os.remove(os.path.join(_BACKUP_DIR, f))


# ---------------------------------------------------------------------------
# SSH control of wdtt.service
# ---------------------------------------------------------------------------

def _ssh_ctl(action: str) -> tuple[bool, str]:
    if action not in ("start", "stop", "status"):
        raise ValueError(f"недопустимая команда: {action}")
    try:
        proc = subprocess.run(
            [
                "ssh",
                "-i", WDTT_SSH_KEY_PATH,
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=5",
                f"{WDTT_SSH_USER}@{WDTT_SSH_HOST}",
                action,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return False, "SSH-таймаут"
    except OSError as e:
        return False, str(e)

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if action == "status":
        return "active" in out, out or err
    return proc.returncode == 0, out or err


def _with_service_restart(mutator):
    """backup -> stop -> read -> mutator(data) -> write -> start (always) -> status-check."""
    _backup()

    ok, out = _ssh_ctl("stop")
    if not ok:
        raise RuntimeError(f"Не удалось остановить wdtt.service: {out}")

    data = _read_passwords()
    mutator_error = None
    result = None
    try:
        result = mutator(data)
    except Exception as e:
        mutator_error = e
    finally:
        _write_passwords_atomic(data)

    # Всегда пытаемся поднять сервис обратно, даже если mutator упал.
    start_ok, start_out = _ssh_ctl("start")

    if mutator_error is not None:
        if not start_ok:
            raise RuntimeError(
                f"{mutator_error}; вдобавок wdtt.service не запустился: {start_out}"
            ) from mutator_error
        raise mutator_error

    if not start_ok:
        raise RuntimeError(f"wdtt.service не запустился после изменения: {start_out}")

    status_ok, status_out = _ssh_ctl("status")
    if not status_ok:
        raise RuntimeError(f"wdtt.service запущен, но статус не 'active': {status_out}")

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_password(existing: set[str]) -> str:
    while True:
        candidate = "".join(secrets.choice(PASS_CHARS) for _ in range(16))
        if candidate not in existing:
            return candidate


def short_password(password: str) -> str:
    return f"{password[:4]}...{password[-4:]}"


def set_name(password: str, name: str) -> None:
    data = _read_passwords()
    if password not in (data.get("passwords") or {}):
        raise RuntimeError(f"Клиент с паролем {password} не найден")
    names = _read_names()
    names[password] = name
    _write_names_atomic(names)


def _strip_vk_hash(raw: str) -> str:
    s = raw.strip()
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    if "?" in s:
        s = s.split("?", 1)[0]
    return s.strip()


def _entry_to_dict(password: str, entry: dict, devices: dict, names: dict) -> dict:
    device_id = entry.get("device_id") or ""
    device = devices.get(device_id) if device_id else None
    return {
        "password": password,
        "name": names.get(password, ""),
        "vk_hash": entry.get("vk_hash", ""),
        "expires_at": entry.get("expires_at", 0),
        "is_deactivated": entry.get("is_deactivated", False),
        "device_id": device_id,
        "ip": (device or {}).get("ip", ""),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_clients() -> list[dict]:
    data = _read_passwords()
    devices = data.get("devices") or {}
    names = _read_names()
    passwords = data.get("passwords") or {}
    return [
        _entry_to_dict(password, entry, devices, names)
        for password, entry in passwords.items()
    ]


def get_client(password: str) -> dict:
    data = _read_passwords()
    passwords = data.get("passwords") or {}
    entry = passwords.get(password)
    if entry is None:
        raise RuntimeError(f"Клиент с паролем {password} не найден")
    devices = data.get("devices") or {}
    names = _read_names()
    return _entry_to_dict(password, entry, devices, names)


def add_client(name: str, vk_hash: str, expires_days: int) -> dict:
    vk_hash = _strip_vk_hash(vk_hash)

    def mutator(data: dict) -> str:
        passwords = data.setdefault("passwords", {})
        password = _generate_password(set(passwords.keys()))
        expires_at = int(time.time()) + expires_days * 86400
        passwords[password] = {
            "device_id": "",
            "expires_at": expires_at,
            "down_bytes": 0,
            "up_bytes": 0,
            "vk_hash": vk_hash,
            "ports": WDTT_PORTS,
            "is_deactivated": False,
        }
        return password

    password = _with_service_restart(mutator)

    names = _read_names()
    names[password] = name
    _write_names_atomic(names)

    return {"password": password, "vk_hash": vk_hash}


def delete_client(password: str) -> str:
    def mutator(data: dict) -> None:
        passwords = data.setdefault("passwords", {})
        devices = data.setdefault("devices", {})
        entry = passwords.pop(password, None)
        if entry is None:
            raise RuntimeError(f"Клиент с паролем {password} не найден")
        device_id = entry.get("device_id")
        if device_id:
            devices.pop(device_id, None)

    _with_service_restart(mutator)

    names = _read_names()
    name = names.pop(password, "") or short_password(password)
    _write_names_atomic(names)

    return name


def set_vk_hash(password: str, vk_hash: str) -> str:
    vk_hash = _strip_vk_hash(vk_hash)

    def mutator(data: dict) -> None:
        passwords = data.setdefault("passwords", {})
        entry = passwords.get(password)
        if entry is None:
            raise RuntimeError(f"Клиент с паролем {password} не найден")
        entry["vk_hash"] = vk_hash

    _with_service_restart(mutator)
    return vk_hash


def set_deactivated(password: str, is_deactivated: bool) -> None:
    def mutator(data: dict) -> None:
        passwords = data.setdefault("passwords", {})
        entry = passwords.get(password)
        if entry is None:
            raise RuntimeError(f"Клиент с паролем {password} не найден")
        entry["is_deactivated"] = is_deactivated

    _with_service_restart(mutator)


def set_expires_days(password: str, expires_days: int) -> int:
    def mutator(data: dict) -> int:
        passwords = data.setdefault("passwords", {})
        entry = passwords.get(password)
        if entry is None:
            raise RuntimeError(f"Клиент с паролем {password} не найден")
        expires_at = int(time.time()) + expires_days * 86400
        entry["expires_at"] = expires_at
        return expires_at

    return _with_service_restart(mutator)


def build_wdtt_link(password: str, vk_hash: str) -> str:
    ports = WDTT_PORTS.split(",")
    return f"wdtt://{get_public_domain()}:{ports[0]}:{ports[1]}:{ports[2]}:{password}:{vk_hash}"


def backup_archive() -> tuple[bytes, str]:
    """Архив passwords.json + names.json + settings.json на текущий момент — для
    отправки в Telegram после каждого изменения клиентов."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, arcname in (
            (_PASSWORDS_FILE, "passwords.json"),
            (_NAMES_FILE, "names.json"),
            (_SETTINGS_FILE, "settings.json"),
        ):
            if os.path.exists(path):
                tar.add(path, arcname=arcname)
    return buf.getvalue(), f"wdtt-backup-{stamp}.tar.gz"
