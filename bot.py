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
    BotCommand,
    BufferedInputFile,
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

class EditClient(StatesGroup):
    waiting_vk_hash = State()
    waiting_days    = State()

class Settings(StatesGroup):
    waiting_domain = State()


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать клиента",  callback_data="newclient")],
        [InlineKeyboardButton(text="📋 Список клиентов", callback_data="clients")],
        [InlineKeyboardButton(text="⚙️ Настройки",       callback_data="settings")],
    ])


def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Изменить домен", callback_data="setdomain")],
        [InlineKeyboardButton(text="💾 Бекапы",          callback_data="backups_menu")],
        [InlineKeyboardButton(text="← Главное меню",    callback_data="menu")],
    ])


def kb_backups(enabled: bool) -> InlineKeyboardMarkup:
    action_text = "🔴 Выключить" if enabled else "🟢 Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=action_text, callback_data="backupstoggle")],
        [InlineKeyboardButton(text="← Настройки", callback_data="settings")],
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
        [InlineKeyboardButton(text="✏️ Редактировать",   callback_data=f"edit:{password}")],
        [InlineKeyboardButton(text="🗑 Удалить",          callback_data=f"del:{password}")],
        [InlineKeyboardButton(text="← Список",           callback_data="clients")],
    ])


def kb_edit_client(password: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"rename:{password}")],
        [InlineKeyboardButton(text="🔑 VK-хеш",         callback_data=f"editvk:{password}")],
        [InlineKeyboardButton(text="🔘 Статус",         callback_data=f"editstatus:{password}")],
        [InlineKeyboardButton(text="📅 Срок",           callback_data=f"editexpiry:{password}")],
        [InlineKeyboardButton(text="← Назад",           callback_data=f"client:{password}")],
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


async def screen_settings(target: Message | CallbackQuery) -> None:
    domain = wdtt.get_public_domain()
    backups = "🟢 включены" if wdtt.get_backups_enabled() else "🔴 выключены"
    text = (
        f"⚙️ Настройки:\n\n"
        f"Текущий домен/IP: <code>{html.escape(domain)}</code>\n"
        f"Бекапы: {backups}"
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb_settings(), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb_settings(), parse_mode="HTML")


async def screen_backups(target: Message | CallbackQuery) -> None:
    enabled = wdtt.get_backups_enabled()
    status = "🟢 включены" if enabled else "🔴 выключены"
    text = (
        f"💾 Бекапы: {status}\n\n"
        f"Бекапы (<code>passwords.json</code> + <code>names.json</code> + "
        f"<code>settings.json</code>) присылаются сюда автоматически только в "
        f"момент, когда что-либо меняется — создание, переименование, смена "
        f"VK-хеша или удаление клиента. По расписанию бекапы не отправляются."
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb_backups(enabled), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb_backups(enabled), parse_mode="HTML")


_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$")


def _normalize_domain(raw: str) -> str | None:
    s = raw.strip()
    s = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", s)
    s = s.split("/", 1)[0]
    s = s.rstrip(".")
    if not s or not _DOMAIN_RE.match(s):
        return None
    return s


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
    remaining = client["expires_at"] - int(time.time())
    days_left = max(0, -(-remaining // 86400))  # ceil, clamped at 0
    return f"до {dt.strftime('%d.%m.%Y %H:%M')} ({days_left} дн.)"


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


async def screen_client(target: Message | CallbackQuery, password: str) -> None:
    try:
        client = wdtt.get_client(password)
    except Exception as e:
        err = f"Ошибка: {e}"
        if isinstance(target, CallbackQuery):
            await target.answer(err, show_alert=True)
        else:
            await target.answer(err)
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
    kb = kb_client_actions(password)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


async def screen_edit_client(cb: CallbackQuery, password: str) -> None:
    try:
        client = wdtt.get_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    name = client["name"] or "без имени"
    text = f'✏️ Редактирование "{html.escape(name)}":'
    await cb.message.edit_text(text, reply_markup=kb_edit_client(password), parse_mode="HTML")
    await cb.answer()


# ---------------------------------------------------------------------------
# Access guard
# ---------------------------------------------------------------------------

def allowed(user_id: int) -> bool:
    return user_id in ALLOWED_USERS


async def send_backup(bot: Bot) -> None:
    """Шлёт архив passwords.json+names.json всем ALLOWED_USERS беззвучным сообщением,
    если отправка бекапов не выключена в настройках."""
    if not wdtt.get_backups_enabled():
        return
    try:
        data, filename = wdtt.backup_archive()
    except Exception:
        logging.exception("Не удалось собрать бекап")
        return
    for user_id in ALLOWED_USERS:
        try:
            document = BufferedInputFile(data, filename=filename)
            await bot.send_document(user_id, document, disable_notification=True)
        except Exception:
            logging.exception("Не удалось отправить бекап пользователю %s", user_id)


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


@dp.callback_query(F.data.startswith("edit:"))
async def cb_edit(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    password = cb.data.split(":", 1)[1]
    await screen_edit_client(cb, password)


# ---------------------------------------------------------------------------
# Callback handlers — settings
# ---------------------------------------------------------------------------

@dp.callback_query(F.data == "settings")
async def cb_settings(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    await screen_settings(cb)


@dp.callback_query(F.data == "setdomain")
async def cb_setdomain(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.set_state(Settings.waiting_domain)
    await cb.message.edit_text(
        f"Текущий домен/IP: <code>{html.escape(wdtt.get_public_domain())}</code>\n\n"
        "Введите новый домен или IP:\n(/cancel — отменить)",
        reply_markup=None,
        parse_mode="HTML",
    )
    await cb.answer()


@dp.message(Settings.waiting_domain)
async def step_domain(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    domain = _normalize_domain(raw)
    if not domain:
        await message.answer("Некорректный домен или IP. Попробуйте ещё раз:")
        return
    await state.clear()
    wdtt.set_public_domain(domain)
    await message.answer(f'✅ Домен изменён на: <code>{html.escape(domain)}</code>', parse_mode="HTML")
    await screen_settings(message)


@dp.callback_query(F.data == "backups_menu")
async def cb_backups_menu(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    await state.clear()
    await screen_backups(cb)


@dp.callback_query(F.data == "backupstoggle")
async def cb_backupstoggle(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    wdtt.set_backups_enabled(not wdtt.get_backups_enabled())
    await cb.answer("Настройка изменена")
    await screen_backups(cb)


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

    await send_backup(message.bot)
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

    await send_backup(message.bot)
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

    await send_backup(message.bot)
    await message.answer(f'✅ Клиент переименован в "{html.escape(name)}".', parse_mode="HTML")
    await screen_client(message, password)


# ---------------------------------------------------------------------------
# Callback handlers — edit VK-hash
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("editvk:"))
async def cb_editvk(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    try:
        client = wdtt.get_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    await state.update_data(password=password)
    await state.set_state(EditClient.waiting_vk_hash)
    current = html.escape(client["vk_hash"] or "не задан")
    await cb.message.edit_text(
        f"Текущий VK-хеш: {current}\n\n"
        "Введите новый VK-хеш или ссылку на VK-звонок:\n(/cancel — отменить)",
        reply_markup=None,
        parse_mode="HTML",
    )
    await cb.answer()


@dp.message(EditClient.waiting_vk_hash)
async def step_editvk(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    if not raw:
        await message.answer("Отправьте VK-хеш или ссылку текстом:")
        return
    data = await state.get_data()
    password = data["password"]
    await state.clear()

    try:
        vk_hash = wdtt.set_vk_hash(password, raw)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await screen_menu(message)
        return

    await send_backup(message.bot)
    await message.answer(f'✅ VK-хеш обновлён: <code>{html.escape(vk_hash)}</code>', parse_mode="HTML")
    await screen_client(message, password)


# ---------------------------------------------------------------------------
# Callback handlers — edit expiry
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("editexpiry:"))
async def cb_editexpiry(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    await state.update_data(password=password)
    await state.set_state(EditClient.waiting_days)
    await cb.message.edit_text(
        "Введите срок действия в днях от текущего момента (1–365):\n(/cancel — отменить)",
        reply_markup=None,
    )
    await cb.answer()


@dp.message(EditClient.waiting_days)
async def step_editdays(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    if not raw.isdigit() or not (1 <= int(raw) <= 365):
        await message.answer("Введите целое число от 1 до 365. Попробуйте ещё раз:")
        return
    days = int(raw)
    data = await state.get_data()
    password = data["password"]
    await state.clear()

    await message.answer("⏳ Сохраняю...")
    try:
        wdtt.set_expires_days(password, days)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await screen_menu(message)
        return

    await send_backup(message.bot)
    await message.answer(f"✅ Срок продлён на {days} дн. от текущего момента.")
    await screen_client(message, password)


# ---------------------------------------------------------------------------
# Callback handlers — edit status
# ---------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("editstatus:"))
async def cb_editstatus(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    try:
        client = wdtt.get_client(password)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return
    current = "🔴 деактивирован" if client["is_deactivated"] else "🟢 активен"
    action_text = "🟢 Активировать" if client["is_deactivated"] else "🔴 Деактивировать"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=action_text, callback_data=f"statustoggle:{password}")],
        [InlineKeyboardButton(text="← Назад", callback_data=f"edit:{password}")],
    ])
    await cb.message.edit_text(f"Текущий статус: {current}", reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data.startswith("statustoggle:"))
async def cb_statustoggle(cb: CallbackQuery, state: FSMContext):
    if not allowed(cb.from_user.id):
        return
    password = cb.data.split(":", 1)[1]
    try:
        client = wdtt.get_client(password)
        wdtt.set_deactivated(password, not client["is_deactivated"])
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)
        return

    await send_backup(cb.bot)
    await cb.answer("Статус изменён")
    await screen_client(cb, password)


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
    await send_backup(cb.bot)
    await cb.answer(f'Клиент "{deleted_name}" удалён.')
    await screen_clients(cb)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="cancel", description="Отменить текущий диалог"),
]


async def main():
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands(BOT_COMMANDS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
