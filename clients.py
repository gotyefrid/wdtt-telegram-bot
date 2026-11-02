"""Единый интерфейс над типами клиентов: WDTT (wdtt.py) и iPhone (xui.py).

Клиент адресуется ссылкой `ref` = "<тип>:<id>": id у WDTT — пароль, у iPhone —
email клиента в 3x-ui. Ref целиком влезает в callback_data Telegram (64 байта)."""
import wdtt
import xui

KIND_WDTT = "w"
KIND_IPHONE = "i"
KIND_TITLES = {KIND_WDTT: "WDTT", KIND_IPHONE: "iPhone"}
KIND_EMOJI = {KIND_WDTT: "🤖", KIND_IPHONE: "📱"}

# Для iPhone имя клиента — его email в 3x-ui и часть callback_data.
MAX_IPHONE_NAME = 32


def make_ref(kind: str, ident: str) -> str:
    return f"{kind}:{ident}"


def split_ref(ref: str) -> tuple[str, str]:
    kind, sep, ident = ref.partition(":")
    if not sep or kind not in KIND_TITLES or not ident:
        raise RuntimeError(f"Некорректный идентификатор клиента: {ref}")
    return kind, ident


def kind_of(ref: str) -> str:
    return split_ref(ref)[0]


def can_rename(ref: str) -> bool:
    # У iPhone имя = email в 3x-ui, смена email создала бы нового клиента с новыми ключами.
    return kind_of(ref) == KIND_WDTT


def _wrap_wdtt(c: dict) -> dict:
    return {
        **c,
        "kind": KIND_WDTT,
        "id": c["password"],
        "ref": make_ref(KIND_WDTT, c["password"]),
        "label": c["name"] or wdtt.short_password(c["password"]),
    }


def _wrap_iphone(c: dict) -> dict:
    return {
        **c,
        "kind": KIND_IPHONE,
        "id": c["name"],
        "ref": make_ref(KIND_IPHONE, c["name"]),
        "label": c["name"],
    }


def list_clients() -> tuple[list[dict], list[str]]:
    """Все клиенты обоих типов и список ошибок по недоступным источникам:
    если 3x-ui не отвечает, WDTT-клиенты всё равно показываются."""
    result: list[dict] = []
    errors: list[str] = []
    try:
        result += [_wrap_wdtt(c) for c in wdtt.list_clients()]
    except Exception as e:
        errors.append(f"WDTT: {e}")
    try:
        result += [_wrap_iphone(c) for c in xui.list_clients()]
    except Exception as e:
        errors.append(f"iPhone: {e}")
    return result, errors


def get_client(ref: str) -> dict:
    kind, ident = split_ref(ref)
    if kind == KIND_WDTT:
        return _wrap_wdtt(wdtt.get_client(ident))
    return _wrap_iphone(xui.get_client(ident))


def add_client(kind: str, name: str, vk_hash: str, days: int) -> dict:
    """Создаёт клиента, возвращает {ref, vk_hash}."""
    if kind == KIND_WDTT:
        r = wdtt.add_client(name, vk_hash, days)
        return {"ref": make_ref(KIND_WDTT, r["password"]), "vk_hash": r["vk_hash"]}
    if kind == KIND_IPHONE:
        r = xui.add_client(name, vk_hash, days)
        return {"ref": make_ref(KIND_IPHONE, r["name"]), "vk_hash": r["vk_hash"]}
    raise RuntimeError(f"Неизвестный тип клиента: {kind}")


def delete_client(ref: str) -> str:
    kind, ident = split_ref(ref)
    return wdtt.delete_client(ident) if kind == KIND_WDTT else xui.delete_client(ident)


def set_name(ref: str, name: str) -> None:
    kind, ident = split_ref(ref)
    if kind != KIND_WDTT:
        raise RuntimeError("Переименование доступно только для WDTT-клиентов")
    wdtt.set_name(ident, name)


def set_vk_hash(ref: str, vk_hash: str) -> str:
    kind, ident = split_ref(ref)
    return wdtt.set_vk_hash(ident, vk_hash) if kind == KIND_WDTT else xui.set_vk_hash(ident, vk_hash)


def set_deactivated(ref: str, is_deactivated: bool) -> None:
    kind, ident = split_ref(ref)
    if kind == KIND_WDTT:
        wdtt.set_deactivated(ident, is_deactivated)
    else:
        xui.set_deactivated(ident, is_deactivated)


def set_expires_days(ref: str, days: int) -> int:
    kind, ident = split_ref(ref)
    return wdtt.set_expires_days(ident, days) if kind == KIND_WDTT else xui.set_expires_days(ident, days)


def build_link(ref: str, vk_hash: str) -> str:
    kind, ident = split_ref(ref)
    if kind == KIND_WDTT:
        return wdtt.build_wdtt_link(ident, vk_hash)
    return xui.build_link(ident, vk_hash)
