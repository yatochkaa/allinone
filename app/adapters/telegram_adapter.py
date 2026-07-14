"""
Telegram-адаптер на aiogram 3.x.

Отвечает только за транспорт: ведёт диалог-меню
(имя → телефон → тип запроса → [авто] → описание → подтверждение),
собирает данные и отдаёт их в LeadService в виде единой модели Lead.

Авто спрашиваем по-разному:
  • Ремонт — марка → модель → год (это важно для ремонта).
  • Запчасти — один вопрос: VIN либо марка+год (чтобы не грузить клиента).
  • Другое — авто не спрашиваем.
Бизнес-логики здесь нет — только сбор и нормализация.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.core.models import Lead
from app.core.service import LeadService
from app.core.validators import normalize_phone, parse_vehicle_freeform

log = logging.getLogger(__name__)


class LeadForm(StatesGroup):
    """Состояния диалога-меню сбора заявки."""

    name = State()
    phone = State()
    request_type = State()   # ждём нажатия inline-кнопки
    veh_parts = State()      # авто (ремонт/запчасти): VIN или марка+год одним сообщением
    description = State()
    confirm = State()        # ждём подтверждения кнопкой


# --- клавиатуры ---

def _type_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора типа запроса."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔧 Запчасти", callback_data="type:parts")],
            [InlineKeyboardButton(text="🛠 Ремонт", callback_data="type:repair")],
            [InlineKeyboardButton(text="❓ Другой вопрос", callback_data="type:question")],
        ]
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    """Кнопки подтверждения заявки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласен, отправить заявку", callback_data="confirm:send")],
            [InlineKeyboardButton(text="✏️ Заполнить заново", callback_data="confirm:restart")],
        ]
    )


def _phone_keyboard() -> ReplyKeyboardMarkup:
    """Кнопка отправки контакта."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


class TelegramAdapter:
    """Реализация MessengerAdapter для Telegram."""

    def __init__(self, bot: Bot, service: LeadService) -> None:
        self._bot = bot
        self._service = service
        self._dp = Dispatcher()
        self._register_handlers()

    # --- реализация интерфейса MessengerAdapter ---

    async def listen(self) -> None:
        """Запустить long-polling. Блокирует выполнение до остановки."""
        log.info("TelegramAdapter запущен, начинаю polling…")
        # Сбрасываем "хвост" старых апдейтов, чтобы не обрабатывать устаревшее.
        await self._bot.delete_webhook(drop_pending_updates=True)
        await self._dp.start_polling(self._bot)

    async def send(self, chat_id: Any, text: str) -> None:
        """Отправить сообщение пользователю."""
        await self._bot.send_message(chat_id=chat_id, text=text)

    def normalize(self, raw: dict[str, Any]) -> Lead:
        """Собрать Lead из собранных в диалоге данных."""
        return Lead(
            name=str(raw.get("name", "")).strip(),
            phone=str(raw.get("phone", "")).strip(),
            request_text=str(raw.get("description", "")).strip(),
            request_type=str(raw.get("request_type", "question")),
            brand=str(raw.get("brand", "")).strip(),
            model=str(raw.get("model", "")).strip(),
            year=str(raw.get("year", "")).strip(),
            vin=str(raw.get("vin", "")).strip(),
            source="telegram",
            external_user_id=str(raw.get("user_id")) if raw.get("user_id") else None,
            external_username=raw.get("username"),
            marketing_consent=bool(raw.get("marketing_consent", False)),
        )

    # --- внутренние хэндлеры диалога ---

    def _register_handlers(self) -> None:
        dp = self._dp

        @dp.message(Command("start"))
        async def cmd_start(message: Message, state: FSMContext) -> None:
            """Старт диалога: приветствие + вопрос имени."""
            await self._start_dialog(message, state)

        @dp.message(Command("cancel"))
        async def cmd_cancel(message: Message, state: FSMContext) -> None:
            """Отмена диалога в любой момент."""
            await state.clear()
            await message.answer(
                "Заявка отменена. Чтобы начать заново — отправьте /start.",
                reply_markup=ReplyKeyboardRemove(),
            )

        @dp.message(LeadForm.name, F.text)
        async def step_name(message: Message, state: FSMContext) -> None:
            """Приняли имя → просим телефон (кнопкой или текстом)."""
            await state.update_data(name=message.text.strip())
            await message.answer(
                "Приятно! Оставьте номер телефона для связи.\n"
                "Можно нажать кнопку ниже или написать номер вручную.",
                reply_markup=_phone_keyboard(),
            )
            await state.set_state(LeadForm.phone)

        @dp.message(LeadForm.phone, F.contact)
        async def step_phone_contact(message: Message, state: FSMContext) -> None:
            """Телефон пришёл через кнопку контакта (уже валидный)."""
            raw = message.contact.phone_number
            # Контакт часто приходит без «+». Если РФ-нормализация не сработала,
            # хотя бы приведём к виду «+цифры», чтобы в таблице был единый формат.
            normalized = normalize_phone(raw)
            if normalized is None:
                digits = re.sub(r"\D", "", raw)
                normalized = ("+" + digits) if digits else raw
            await state.update_data(phone=normalized)
            await self._ask_type(message, state)

        @dp.message(LeadForm.phone, F.text)
        async def step_phone_text(message: Message, state: FSMContext) -> None:
            """Телефон ввели текстом — валидируем."""
            phone = normalize_phone(message.text)
            if phone is None:
                # Не похоже на номер — остаёмся на этом шаге и просим повторить.
                await message.answer(
                    "Не похоже на номер телефона 😅\n"
                    "Введите, пожалуйста, в формате +7 999 123-45-67 или нажмите кнопку ниже.",
                    reply_markup=_phone_keyboard(),
                )
                return
            await state.update_data(phone=phone)
            await self._ask_type(message, state)

        @dp.callback_query(LeadForm.request_type, F.data.startswith("type:"))
        async def choose_type(callback: CallbackQuery, state: FSMContext) -> None:
            """Выбран тип запроса кнопкой."""
            req_type = callback.data.split(":", 1)[1]
            await state.update_data(request_type=req_type)
            await callback.answer()  # убираем "часики" на кнопке

            if req_type == "repair":
                # Ремонт: авто одной строкой (как для запчастей), чтобы не грузить клиента.
                await callback.message.answer(
                    "Напишите авто одной строкой: <b>марку, модель, поколение "
                    "(если есть) и год</b>.\n"
                    "Например: <i>Lada Priora 2014</i> или <i>Toyota Camry 70 2022</i>."
                )
                await state.set_state(LeadForm.veh_parts)
            elif req_type == "parts":
                # Запчасти: один вопрос — VIN либо марка+год (не грузим клиента).
                await callback.message.answer(
                    "Подскажите авто для подбора запчастей.\n"
                    "Проще всего — <b>VIN</b> (17 символов), этого достаточно.\n"
                    "Если VIN под рукой нет — напишите <b>марку, модель, поколение "
                    "(если есть) и год</b> одной строкой.\n"
                    "Например: <i>Lada Priora 2014</i> или <i>Toyota Camry 70 2022</i>."
                )
                await state.set_state(LeadForm.veh_parts)
            else:
                # Другой вопрос — авто не нужно.
                await state.update_data(brand="", model="", year="", vin="")
                await self._ask_description(callback.message, state)

        @dp.message(LeadForm.request_type)
        async def type_fallback(message: Message) -> None:
            """Если вместо кнопки написали текст — мягко напоминаем."""
            await message.answer(
                "Пожалуйста, выберите тип запроса кнопкой выше 👆",
                reply_markup=_type_keyboard(),
            )

        @dp.message(LeadForm.veh_parts, F.text)
        async def step_veh_parts(message: Message, state: FSMContext) -> None:
            """Запчасти: разбираем свободный ввод (VIN либо марка+год)."""
            parsed = parse_vehicle_freeform(message.text)
            await state.update_data(
                brand=parsed["brand"],
                model=parsed["model"],
                year=parsed["year"],
                vin=parsed["vin"],
            )
            await self._ask_description(message, state)

        @dp.message(LeadForm.description, F.text)
        async def step_description(message: Message, state: FSMContext) -> None:
            """Получили описание → показываем экран подтверждения."""
            await state.update_data(description=message.text.strip())
            data = await state.get_data()
            # Собираем черновик Lead только для красивого превью.
            preview = self.normalize(data)
            await message.answer(
                preview.as_confirmation(),
                reply_markup=_confirm_keyboard(),
            )
            await state.set_state(LeadForm.confirm)

        @dp.callback_query(LeadForm.confirm, F.data == "confirm:send")
        async def confirm_send(callback: CallbackQuery, state: FSMContext) -> None:
            """Клиент подтвердил → регистрируем заявку.

            Защита от двойного нажатия: ставим флаг и сразу убираем кнопки,
            чтобы повторные тапы не создавали дубли заявок.
            """
            data = await state.get_data()
            if data.get("_submitting"):
                await callback.answer("Уже отправляю заявку…")
                return
            await state.update_data(_submitting=True)
            await callback.answer()
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            data["user_id"] = callback.from_user.id
            data["username"] = callback.from_user.username
            lead = self.normalize(data)
            try:
                await self._service.register_lead(lead)
                await callback.message.edit_text(
                    f"✅ Заявка №{lead.lead_number} отправлена!\n"
                    "Ожидайте, менеджер уже скоро свяжется с вами."
                )
            except Exception:
                # Любая ошибка обработки НЕ должна ронять бота.
                log.exception("Ошибка при регистрации заявки")
                await callback.message.answer(
                    "Произошла техническая ошибка, но мы уже разбираемся. "
                    "Пожалуйста, попробуйте ещё раз через /start.",
                    reply_markup=ReplyKeyboardRemove(),
                )
            finally:
                await state.clear()

        @dp.callback_query(LeadForm.confirm, F.data == "confirm:restart")
        async def confirm_restart(callback: CallbackQuery, state: FSMContext) -> None:
            """Клиент хочет заполнить заново."""
            await callback.answer()
            await self._start_dialog(callback.message, state)

        @dp.message()
        async def fallback(message: Message, state: FSMContext) -> None:
            """Сообщение, не подошедшее ни одному шагу.

            Если мы посреди анкеты, а пришло не то, что ждём (стикер/фото вместо
            текста) — мягко просим повторить текстом и НЕ сбрасываем диалог.
            Вне анкеты — подсказываем, как начать.
            """
            if await state.get_state() is not None:
                await message.answer(
                    "Пожалуйста, отправьте ответ текстом 🙏\n"
                    "Или /cancel, чтобы отменить заявку."
                )
                return
            await message.answer("Чтобы оставить заявку, отправьте /start.")

    # --- общие шаги диалога ---

    async def _start_dialog(self, message: Message, state: FSMContext) -> None:
        """Начать (или начать заново) диалог сбора заявки."""
        await state.clear()
        await message.answer(
            "Здравствуйте! Я помогу оформить заявку. Это займёт 30 секунд.\n\n"
            "Как вас зовут?",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(LeadForm.name)

    async def _ask_type(self, message: Message, state: FSMContext) -> None:
        """После телефона — спрашиваем тип запроса кнопками (одним сообщением)."""
        await message.answer(
            "Что вас интересует?",
            reply_markup=_type_keyboard(),
        )
        await state.set_state(LeadForm.request_type)

    async def _ask_description(self, message: Message, state: FSMContext) -> None:
        """Спросить описание запроса. Текст зависит от выбранного типа."""
        data = await state.get_data()
        req_type = data.get("request_type", "question")
        if req_type == "repair":
            text = (
                "Опишите, что беспокоит или какую работу нужно сделать.\n"
                "Например: «Стучат гидрики, надо продиагностировать»."
            )
        elif req_type == "parts":
            text = (
                "Опишите, какие запчасти нужны.\n"
                "Например: «Колодки передние и задние»."
            )
        else:
            text = "Опишите, пожалуйста, суть вашего вопроса."
        await message.answer(text)
        await state.set_state(LeadForm.description)

