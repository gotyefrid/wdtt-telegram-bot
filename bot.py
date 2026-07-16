import asyncio
import html
import logging
import re
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from config import BOT_TOKEN, ALLOWED_USERS, WG_SERVER_PUBLIC_KEY, WG_PEER_ADDRESS
import xui
import wdtt
from link import build_link

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------

class NewClient(StatesGroup):
    waiting_name    = State()
    waiting_vk_link = State()

class GetLink(StatesGroup):
    waiting_vk_link = State()


class NewClientWdtt(StatesGroup):
    waiting_name    = State()
    waiting_vk_hash = State()
    waiting_days    = State()

class GetLinkWdtt(StatesGroup):
    waiting_vk_hash = State()


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать клиента",  callback_data="newclient")],
        [InlineKeyboardButton(text="📋 Список клиентов", callback_data="clients")],
    ])


def kb_clients(clients: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=c["name"], callback_data=f"client:{c['index']}")
        for c in clients
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="← Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_client_actions(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Получить ссылку", callback_data=f"link:{index}")],
        [InlineKeyboardButton(text="🗑 Удалить",          callback_data=f"del:{index}")],
        [InlineKeyboardButton(text="← Список",           callback_data="clients")],
    ])


def kb_confirm_delete(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"del_confirm:{index}"),
            InlineKeyboardButton(text="❌ Отмена",      callback_data=f"client:{index}"),
        ],
    ])


def kb_type_choice(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍏 Apple", callback_data=f"{action}type:apple")],
        [InlineKeyboardButton(text="📡 WDTT",  callback_data=f"{action}type:wdtt")],
        [InlineKeyboardButton(text="← Главное меню", callback_data="menu")],
    ])


def kb_clients_wdtt(clients: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=c["name"] if c["name"] else wdtt.short_password(c["password"]),
            callback_data=f"wclient:{c['password']}",
        )
        for c in clients
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="← Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_wdtt_client_actions(password: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Получить ссылку", callback_data=f"wlink:{password}")],
        [InlineKeyboardButton(text="🗑 Удалить",          callback_data=f"wdel:{password}")],
        [InlineKeyboardButton(text="← Список",           callback_data="wclients")],
    ])


def kb_wdtt_confirm_delete(password: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"wdel_confirm:{password}"),
            InlineKeyboardButton(text="❌ Отмена",      callback_data=f"wclient:{password}"),
        ],
    ])


# ---------------------------------------------------------------------------
# Screen helpers
# ---------------------------------------------------------------------------

async def screen_menu(target: Message | CallbackQuery) -> None:
    text = "Главное меню:"
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb_main())
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb_main())


async def screen_clients(target: Message | CallbackQuery) -> None:
    try:
        clients = xui.list_clients()
    except Exception as e:
        err = f"Ошибка: {e}"
        if isinstance(target, CallbackQuery):
            await target.answer(err, show_alert=True)
        else:
            await target.answer(err)
        return

    if not clients:
        text = "Клиентов пока нет."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Главное меню", callback_data="menu")]
        ])
    else:
        text = f"Клиенты WireGuard ({len(clients)}):"
        kb = kb_clients(clients)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


async def screen_client(cb: CallbackQuery, index: int) -> None:
    try:
        peer = xui.get_peer(index)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    text = f"👤 {peer['name']}\nIP: {peer['ip']}"
    await cb.message.edit_text(text, reply_markup=kb_client_actions(index))
    await cb.answer()


async def screen_type_choice(cb: CallbackQuery, action: str, prompt: str) -> None:
    await cb.message.edit_text(prompt, reply_markup=kb_type_choice(action))
    await cb.answer()


async def screen_clients_wdtt(target: Message | CallbackQuery) -> None:
    try:
        clients = wdtt.list_clients()
    except Exception as e:
        err = f"Ошибка: {e}"
        if isinstance(target, CallbackQuery):
            await target.answer(err, show_alert=True)
        else:
            await target.answer(err)
        return

    if not clients:
        text = "Клиентов WDTT пока нет."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Главное меню", callback_data="menu")]
        ])
    else:
        text = f"Клиенты WDTT ({len(clients)}):"
        kb = kb_clients_wdtt(clients)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


def _wdtt_status_text(client: dict) -> str:
    if client["is_deactivated"]:
        return "🔴 деактивирован"
    if client["expires_at"] and int(time.time()) > client["expires_at"]:
        return "❌ истёк"
    return "🟢 активен"


def _wdtt_expires_text(client: dict) -> str:
    if not client["expires_at"]:
        return "бессрочно"
    dt = datetime.fromtimestamp(client["expires_at"])
    return f"до {dt.strftime('%d.%m.%Y %H:%M')}"


def _wdtt_device_text(client: dict) -> str:
    if not client["device_id"]:
        return "ещё не подключалось"
    return f"{client['device_id']}, {client['ip'] or '?'}"


async def screen_client_wdtt(cb: CallbackQuery, password: str) -> None:
    try:
        client = wdtt.get_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    name = client["name"] or "без имени"
    vk_hash = client["vk_hash"] or "не задан"
    text = (
        f"👤 {html.escape(name)}\n"
        f"Пароль: <code>{html.escape(client['password'])}</code>\n"
        f"VK-хеш: {html.escape(vk_hash)}\n"
        f"Статус: {_wdtt_status_text(client)}\n"
        f"Срок: {_wdtt_expires_text(client)}\n"
        f"Устройство: {html.escape(_wdtt_device_text(client))}"
    )
    await cb.message.edit_text(text, reply_markup=kb_wdtt_client_actions(password), parse_mode="HTML")
    await cb.answer()


# ---------------------------------------------------------------------------
# Access guard
# ---------------------------------------------------------------------------

def allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if not allowed(message.from_user.id):
        return
    await state.clear()
    await screen_menu(message)


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if not allowed(message.from_user.id):
        return
    if await state.get_state() is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("Действие отменено.")
    await screen_menu(message)


# ---------------------------------------------------------------------------
# Callback handlers — navigation
# ---------------------------------------------------------------------------

@dp.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    await screen_menu(cb)


@dp.callback_query(F.data == "clients")
async def cb_clients(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    await screen_type_choice(cb, "list", "Список клиентов — выберите тип:")


@dp.callback_query(F.data == "listtype:apple")
async def cb_listtype_apple(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    await screen_clients(cb)


@dp.callback_query(F.data == "listtype:wdtt")
async def cb_listtype_wdtt(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    await screen_clients_wdtt(cb)


@dp.callback_query(F.data == "wclients")
async def cb_wclients(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    await screen_clients_wdtt(cb)


@dp.callback_query(F.data.startswith("client:"))
async def cb_client(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    index = int(cb.data.split(":")[1])
    await screen_client(cb, index)


@dp.callback_query(F.data.startswith("wclient:"))
async def cb_wclient(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    password = cb.data.split(":", 1)[1]
    await screen_client_wdtt(cb, password)


# ---------------------------------------------------------------------------
# Callback handlers — create client
# ---------------------------------------------------------------------------

@dp.callback_query(F.data == "newclient")
async def cb_newclient(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    await screen_type_choice(cb, "new", "Создание клиента — выберите тип:")


@dp.callback_query(F.data == "newtype:apple")
async def cb_newtype_apple(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.set_state(NewClient.waiting_name)
    await cb.message.edit_text(
        "Введите имя нового клиента:\n(/cancel — отменить)",
        reply_markup=None,
    )
    await cb.answer()


@dp.callback_query(F.data == "newtype:wdtt")
async def cb_newtype_wdtt(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.set_state(NewClientWdtt.waiting_name)
    await cb.message.edit_text(
        "Введите имя нового клиента:\n(/cancel — отменить)",
        reply_markup=None,
    )
    await cb.answer()


@dp.message(NewClient.waiting_name)
async def step_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправьте имя текстом:")
        return
    raw = message.text.strip()
    name = re.sub(r"[^a-zA-Z0-9_-]", "", raw)
    if not name:
        await message.answer("Имя должно содержать хотя бы одну латинскую букву или цифру. Попробуйте ещё раз:")
        return
    reply = f"Введите ссылку на VK-звонок:\n(/cancel — отменить)"
    if name != raw:
        reply = f"Имя сохранено как: <code>{html.escape(name)}</code>\n\n" + reply
    await state.update_data(name=name)
    await state.set_state(NewClient.waiting_vk_link)
    await message.answer(reply, parse_mode="HTML")


@dp.message(NewClient.waiting_vk_link)
async def step_new_vk_link(message: Message, state: FSMContext):
    vk_link = _valid_vk_link(message.text)
    if not vk_link:
        await message.answer("Ссылка должна начинаться с https://vk.com/call/join/ или https://vk.ru/call/join/. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    name = data["name"]
    await state.clear()

    await message.answer("⏳ Создаю клиента...")
    try:
        peer = xui.add_peer(name)
    except Exception as e:
        await message.answer(f"Ошибка при создании: {e}")
        await screen_menu(message)
        return

    link = build_link(_make_link_settings(peer["private_key"], peer["ip"], vk_link))
    await message.answer(
        f'✅ Клиент "{html.escape(name)}" создан.\n\nСсылка для подключения:\n<code>{link}</code>',
        parse_mode="HTML",
    )
    await screen_menu(message)


# ---------------------------------------------------------------------------
# Callback handlers — create client (WDTT)
# ---------------------------------------------------------------------------

@dp.message(NewClientWdtt.waiting_name)
async def step_wdtt_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправьте имя текстом:")
        return
    raw = message.text.strip()
    name = re.sub(r"[^a-zA-Z0-9_-]", "", raw)
    if not name:
        await message.answer("Имя должно содержать хотя бы одну латинскую букву или цифру. Попробуйте ещё раз:")
        return
    reply = "Введите VK-хеш или ссылку на VK-звонок:\n(/cancel — отменить)"
    if name != raw:
        reply = f"Имя сохранено как: <code>{html.escape(name)}</code>\n\n" + reply
    await state.update_data(name=name)
    await state.set_state(NewClientWdtt.waiting_vk_hash)
    await message.answer(reply, parse_mode="HTML")


@dp.message(NewClientWdtt.waiting_vk_hash)
async def step_wdtt_vk_hash(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    if not raw:
        await message.answer("Отправьте VK-хеш или ссылку текстом:")
        return
    await state.update_data(vk_hash=raw)
    await state.set_state(NewClientWdtt.waiting_days)
    await message.answer("Введите срок действия в днях (1–365):\n(/cancel — отменить)")


@dp.message(NewClientWdtt.waiting_days)
async def step_wdtt_days(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    if not raw.isdigit() or not (1 <= int(raw) <= 365):
        await message.answer("Введите целое число от 1 до 365. Попробуйте ещё раз:")
        return
    days = int(raw)
    data = await state.get_data()
    name = data["name"]
    vk_hash = data["vk_hash"]
    await state.clear()

    await message.answer("⏳ Создаю клиента...")
    try:
        client = wdtt.add_client(name, vk_hash, days)
    except Exception as e:
        await message.answer(f"Ошибка при создании: {e}")
        await screen_menu(message)
        return

    link = wdtt.build_wdtt_link(client["password"], client["vk_hash"])
    await message.answer(
        f'✅ Клиент "{html.escape(name)}" создан.\n\nСсылка для подключения:\n<code>{link}</code>',
        parse_mode="HTML",
    )
    await screen_menu(message)


# ---------------------------------------------------------------------------
# Callback handlers — get link for existing client
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("link:"))
async def cb_link(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    index = int(cb.data.split(":")[1])
    await state.update_data(peer_index=index)
    await state.set_state(GetLink.waiting_vk_link)
    await cb.message.edit_text(
        "Введите ссылку на VK-звонок:\n(/cancel — отменить)",
        reply_markup=None,
    )
    await cb.answer()


@dp.message(GetLink.waiting_vk_link)
async def step_existing_vk_link(message: Message, state: FSMContext):
    vk_link = _valid_vk_link(message.text)
    if not vk_link:
        await message.answer("Ссылка должна начинаться с https://vk.com/call/join/ или https://vk.ru/call/join/. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    index = data["peer_index"]
    await state.clear()

    try:
        peer = xui.get_peer(index)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await screen_menu(message)
        return

    link = build_link(_make_link_settings(peer["private_key"], peer["ip"], vk_link))
    await message.answer(
        f'🔗 Ссылка для "{html.escape(peer["name"])}":\n<code>{link}</code>',
        parse_mode="HTML",
    )
    await screen_menu(message)


# ---------------------------------------------------------------------------
# Callback handlers — get link for existing client (WDTT)
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("wlink:"))
async def cb_wlink(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    try:
        client = wdtt.get_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return

    if client["vk_hash"]:
        link = wdtt.build_wdtt_link(password, client["vk_hash"])
        await cb.message.edit_text(
            f'🔗 Ссылка для "{html.escape(client["name"] or "без имени")}":\n<code>{link}</code>',
            reply_markup=kb_wdtt_client_actions(password),
            parse_mode="HTML",
        )
        await cb.answer()
        return

    await state.update_data(wdtt_password=password)
    await state.set_state(GetLinkWdtt.waiting_vk_hash)
    await cb.message.edit_text(
        "VK-хеш не задан. Введите VK-хеш или ссылку на VK-звонок:\n(/cancel — отменить)",
        reply_markup=None,
    )
    await cb.answer()


@dp.message(GetLinkWdtt.waiting_vk_hash)
async def step_wdtt_existing_vk_hash(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    if not raw:
        await message.answer("Отправьте VK-хеш или ссылку текстом:")
        return
    data = await state.get_data()
    password = data["wdtt_password"]
    await state.clear()

    await message.answer("⏳ Сохраняю...")
    try:
        vk_hash = wdtt.set_vk_hash(password, raw)
        client = wdtt.get_client(password)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await screen_menu(message)
        return

    link = wdtt.build_wdtt_link(password, vk_hash)
    await message.answer(
        f'🔗 Ссылка для "{html.escape(client["name"] or "без имени")}":\n<code>{link}</code>',
        parse_mode="HTML",
    )
    await screen_menu(message)


# ---------------------------------------------------------------------------
# Callback handlers — delete client
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("del:"))
async def cb_del(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    index = int(cb.data.split(":")[1])
    try:
        peer = xui.get_peer(index)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    await cb.message.edit_text(
        f'Удалить клиента "{peer["name"]}"?',
        reply_markup=kb_confirm_delete(index),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("del_confirm:"))
async def cb_del_confirm(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    index = int(cb.data.split(":")[1])
    try:
        deleted_name = xui.delete_peer(index)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    await cb.answer(f'Клиент "{deleted_name}" удалён.')
    await screen_clients(cb)


# ---------------------------------------------------------------------------
# Callback handlers — delete client (WDTT)
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("wdel:"))
async def cb_wdel(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    try:
        client = wdtt.get_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    name = client["name"] or "без имени"
    await cb.message.edit_text(
        f'Удалить клиента "{html.escape(name)}"?',
        reply_markup=kb_wdtt_confirm_delete(password),
        parse_mode="HTML",
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("wdel_confirm:"))
async def cb_wdel_confirm(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    try:
        deleted_name = wdtt.delete_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    await cb.answer(f'Клиент "{deleted_name}" удалён.')
    await screen_clients_wdtt(cb)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VK_LINK_PREFIXES = ("https://vk.com/call/join/", "https://vk.ru/call/join/")


def _valid_vk_link(text: str | None) -> str | None:
    """Return stripped link if valid, else None."""
    if not text or not text.strip():
        return None
    s = text.strip()
    return s if s.startswith(_VK_LINK_PREFIXES) else None


def _make_link_settings(private_key: str, ip: str, vk_link: str) -> dict:
    return {
        "privateKey":     private_key,
        "peerPublicKey":  WG_SERVER_PUBLIC_KEY,
        "tunnelAddress":  f"{ip}/32",
        "allowedIPs":     "0.0.0.0/0",
        "vkLink":         vk_link,
        "peerAddress":    WG_PEER_ADDRESS,
        "dnsServers":     "1.1.1.1",
        "numConnections": 30,
        "useDTLS":        True,
        "useWrap":        False,
        "wrapKeyHex":     "",
        "useSrtp":        True,
        "useUDP":         False,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
