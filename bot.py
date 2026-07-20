import asyncio
import html
import logging
import re
import time
from datetime import datetime
from urllib.parse import quote
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
from config import BOT_TOKEN, ALLOWED_USERS
import wdtt
from ios_link import build_ios_link

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------

class NewClient(StatesGroup):
    waiting_name    = State()
    waiting_vk_hash = State()
    waiting_days    = State()

class GetLink(StatesGroup):
    waiting_vk_hash = State()

class Rename(StatesGroup):
    waiting_name = State()


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
        InlineKeyboardButton(
            text=c["name"] if c["name"] else wdtt.short_password(c["password"]),
            callback_data=f"client:{c['password']}",
        )
        for c in clients
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="← Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_client_actions(password: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Получить ссылку", callback_data=f"link:{password}")],
        [InlineKeyboardButton(text="✏️ Переименовать",   callback_data=f"rename:{password}")],
        [InlineKeyboardButton(text="🗑 Удалить",          callback_data=f"del:{password}")],
        [InlineKeyboardButton(text="← Список",           callback_data="clients")],
    ])


def kb_confirm_delete(password: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"del_confirm:{password}"),
            InlineKeyboardButton(text="❌ Отмена",      callback_data=f"client:{password}"),
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
        clients = wdtt.list_clients()
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
        text = f"Клиенты ({len(clients)}):"
        kb = kb_clients(clients)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


def _status_text(client: dict) -> str:
    if client["is_deactivated"]:
        return "🔴 деактивирован"
    if client["expires_at"] and int(time.time()) > client["expires_at"]:
        return "❌ истёк"
    return "🟢 активен"


def _expires_text(client: dict) -> str:
    if not client["expires_at"]:
        return "бессрочно"
    dt = datetime.fromtimestamp(client["expires_at"])
    return f"до {dt.strftime('%d.%m.%Y %H:%M')}"


def _device_text(client: dict) -> str:
    if not client["device_id"]:
        return "ещё не подключалось"
    return f"{client['device_id']}, {client['ip'] or '?'}"


def _qr_link(data: str) -> str:
    return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(data, safe='')}"


def _links_text(password: str, vk_hash: str) -> str:
    wdtt_link = wdtt.build_wdtt_link(password, vk_hash)
    ios_link = build_ios_link(vk_hash, wdtt.ios_peer_address(), password)
    wdtt_qr = _qr_link(wdtt_link)
    ios_qr = _qr_link(ios_link)
    return (
        f"WDTT:\n<code>{wdtt_link}</code>\n"
        f'<a href="{wdtt_qr}">QR-код WDTT</a>\n\n'
        f"iOS:\n<code>{ios_link}</code>\n"
        f'<a href="{ios_qr}">QR-код iOS</a>'
    )


async def screen_client(cb: CallbackQuery, password: str) -> None:
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
        f"Статус: {_status_text(client)}\n"
        f"Срок: {_expires_text(client)}\n"
        f"Устройство: {html.escape(_device_text(client))}"
    )
    await cb.message.edit_text(text, reply_markup=kb_client_actions(password), parse_mode="HTML")
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
    await screen_clients(cb)


@dp.callback_query(F.data.startswith("client:"))
async def cb_client(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    password = cb.data.split(":", 1)[1]
    await screen_client(cb, password)


# ---------------------------------------------------------------------------
# Callback handlers — create client
# ---------------------------------------------------------------------------

@dp.callback_query(F.data == "newclient")
async def cb_newclient(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.set_state(NewClient.waiting_name)
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
    reply = "Введите VK-хеш или ссылку на VK-звонок:\n(/cancel — отменить)"
    if name != raw:
        reply = f"Имя сохранено как: <code>{html.escape(name)}</code>\n\n" + reply
    await state.update_data(name=name)
    await state.set_state(NewClient.waiting_vk_hash)
    await message.answer(reply, parse_mode="HTML")


@dp.message(NewClient.waiting_vk_hash)
async def step_vk_hash(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    if not raw:
        await message.answer("Отправьте VK-хеш или ссылку текстом:")
        return
    await state.update_data(vk_hash=raw)
    await state.set_state(NewClient.waiting_days)
    await message.answer("Введите срок действия в днях (1–365):\n(/cancel — отменить)")


@dp.message(NewClient.waiting_days)
async def step_days(message: Message, state: FSMContext):
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

    links = _links_text(client["password"], client["vk_hash"])
    await message.answer(
        f'✅ Клиент "{html.escape(name)}" создан.\n\nСсылки для подключения:\n\n{links}',
        parse_mode="HTML",
        link_preview_options=NO_PREVIEW,
    )
    await screen_menu(message)


# ---------------------------------------------------------------------------
# Callback handlers — get link for existing client
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("link:"))
async def cb_link(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    try:
        client = wdtt.get_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return

    if client["vk_hash"]:
        links = _links_text(password, client["vk_hash"])
        await cb.message.edit_text(
            f'🔗 Ссылки для "{html.escape(client["name"] or "без имени")}":\n\n{links}',
            reply_markup=kb_client_actions(password),
            parse_mode="HTML",
            link_preview_options=NO_PREVIEW,
        )
        await cb.answer()
        return

    await state.update_data(password=password)
    await state.set_state(GetLink.waiting_vk_hash)
    await cb.message.edit_text(
        "VK-хеш не задан. Введите VK-хеш или ссылку на VK-звонок:\n(/cancel — отменить)",
        reply_markup=None,
    )
    await cb.answer()


@dp.message(GetLink.waiting_vk_hash)
async def step_existing_vk_hash(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    if not raw:
        await message.answer("Отправьте VK-хеш или ссылку текстом:")
        return
    data = await state.get_data()
    password = data["password"]
    await state.clear()

    await message.answer("⏳ Сохраняю...")
    try:
        vk_hash = wdtt.set_vk_hash(password, raw)
        client = wdtt.get_client(password)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await screen_menu(message)
        return

    links = _links_text(password, vk_hash)
    await message.answer(
        f'🔗 Ссылки для "{html.escape(client["name"] or "без имени")}":\n\n{links}',
        parse_mode="HTML",
        link_preview_options=NO_PREVIEW,
    )
    await screen_menu(message)


# ---------------------------------------------------------------------------
# Callback handlers — rename client
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("rename:"))
async def cb_rename(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    await state.update_data(password=password)
    await state.set_state(Rename.waiting_name)
    await cb.message.edit_text(
        "Введите новое имя клиента:\n(/cancel — отменить)",
        reply_markup=None,
    )
    await cb.answer()


@dp.message(Rename.waiting_name)
async def step_rename(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправьте имя текстом:")
        return
    raw = message.text.strip()
    name = re.sub(r"[^a-zA-Z0-9_-]", "", raw)
    if not name:
        await message.answer("Имя должно содержать хотя бы одну латинскую букву или цифру. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    password = data["password"]
    await state.clear()

    try:
        wdtt.set_name(password, name)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await screen_menu(message)
        return

    await message.answer(f'✅ Клиент переименован в "{html.escape(name)}".', parse_mode="HTML")
    await screen_clients(message)


# ---------------------------------------------------------------------------
# Callback handlers — delete client
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("del:"))
async def cb_del(cb: CallbackQuery, state: FSMContext):
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
        reply_markup=kb_confirm_delete(password),
        parse_mode="HTML",
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("del_confirm:"))
async def cb_del_confirm(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    try:
        deleted_name = wdtt.delete_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    await cb.answer(f'Клиент "{deleted_name}" удалён.')
    await screen_clients(cb)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    bot = Bot(token=BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
