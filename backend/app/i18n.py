"""Server-side messages in the reader's language.

Two audiences, two ways of choosing:
  * the app sends `Accept-Language`, matching what its own UI shows;
  * the bot uses the member's Telegram language, stored on the user so background
    jobs (reminders, digest) know it too.

Group-chat messages have no single reader, so they use DEFAULT_LANGUAGE.
"""

from typing import Annotated, Any

from fastapi import Header

RU = "ru"
EN = "en"
LANGUAGES = (RU, EN)

MESSAGES: dict[str, dict[str, str]] = {
    # --- API errors ---
    "error.voucher_not_found": {
        RU: "Купон не найден",
        EN: "Card not found",
    },
    "error.comment_not_found": {
        RU: "Комментарий не найден",
        EN: "Comment not found",
    },
    "error.comment_not_yours": {
        RU: "Удалять можно только свои комментарии",
        EN: "You can only delete your own comments",
    },
    "error.image_not_found": {
        RU: "Изображение не найдено",
        EN: "Image not found",
    },
    "error.image_unreadable": {
        RU: "Не удалось прочитать изображение",
        EN: "Could not read the image",
    },
    "error.bad_path": {
        RU: "Некорректный путь к файлу",
        EN: "Invalid file path",
    },
    "error.unsupported_type": {
        RU: "Неподдерживаемый тип файла: {content_type}",
        EN: "Unsupported file type: {content_type}",
    },
    "error.file_too_big": {
        RU: "Файл больше {limit} МБ",
        EN: "The file is larger than {limit} MB",
    },
    "error.empty_file": {
        RU: "Пустой файл",
        EN: "Empty file",
    },
    "error.already_used": {
        RU: "Купон уже отмечен использованным",
        EN: "This card is already marked as used",
    },
    "error.not_a_draft": {
        RU: "Это не черновик",
        EN: "This is not a draft",
    },
    "error.balance_amount_only": {
        RU: "Остаток есть только у купонов на сумму",
        EN: "Only cards with a money value have a balance",
    },
    "error.no_face_value": {
        RU: "У купона не указан номинал — сначала заполните его",
        EN: "This card has no face value — fill it in first",
    },
    "error.spend_too_much": {
        RU: "Нельзя списать {spent} — на купоне {current} {currency}",
        EN: "Cannot spend {spent} — the card holds {current} {currency}",
    },
    "error.above_face_value": {
        RU: "Остаток больше номинала ({face} {currency}) — поправьте номинал в купоне",
        EN: "The balance exceeds the face value ({face} {currency}) — fix the face value first",
    },
    "error.barcode_not_found": {
        RU: "Штрихкод не найден",
        EN: "Barcode not found",
    },
    "error.barcode_not_drawable": {
        RU: "Этот формат не перерисовывается",
        EN: "This symbology cannot be redrawn",
    },
    "error.auth_required": {
        RU: "Нужен вход: откройте приложение через бота или войдите по ссылке из чата",
        EN: "Sign in: open the app from the bot, or use the login link from the chat",
    },
    "error.no_access": {
        RU: "Нет доступа. Передайте администратору свой Telegram ID: {telegram_id}",
        EN: "No access. Give your Telegram ID to the admin: {telegram_id}",
    },
    "error.no_bot_token": {
        RU: "BOT_TOKEN не сконфигурирован",
        EN: "BOT_TOKEN is not configured",
    },
    "error.login_link_dead": {
        RU: "Ссылка недействительна или уже использована. Запросите новую: /login боту",
        EN: "This link is invalid or already used. Ask the bot for a new one: /login",
    },
    "error.init_data_no_hash": {
        RU: "initData без hash",
        EN: "initData without a hash",
    },
    "error.init_data_bad_signature": {
        RU: "Неверная подпись initData",
        EN: "Invalid initData signature",
    },
    "error.init_data_expired": {
        RU: "initData просрочен",
        EN: "initData has expired",
    },
    "error.init_data_no_user": {
        RU: "initData без блока user",
        EN: "initData without a user block",
    },
    # --- bot ---
    "bot.your_id": {
        RU: "Ваш Telegram ID: <code>{user_id}</code> → ALLOWED_TELEGRAM_IDS",
        EN: "Your Telegram ID: <code>{user_id}</code> → ALLOWED_TELEGRAM_IDS",
    },
    "bot.chat_id": {
        RU: "ID этого чата: <code>{chat_id}</code> → FAMILY_CHAT_ID",
        EN: "This chat's ID: <code>{chat_id}</code> → FAMILY_CHAT_ID",
    },
    "bot.no_access": {
        RU: (
            "Это семейное приложение для купонов. Доступа пока нет.\n"
            "Ваш Telegram ID: <code>{user_id}</code>"
        ),
        EN: (
            "This is a family gift-card app. You do not have access yet.\n"
            "Your Telegram ID: <code>{user_id}</code>"
        ),
    },
    "bot.start": {
        RU: (
            "Купили карту — пришлите скрин <b>с подписью</b> «Rewe 50», "
            "и она сразу появится в списке.\n\n"
            "Без подписи получится черновик: тогда просто напишите следом "
            "«Rewe 50» — или отдельно «Rewe», а потом «50».\n\n"
            "Ещё умею /login (вход в браузере), /digest, /backup и /id."
        ),
        EN: (
            "Bought a card? Send a screenshot <b>with the caption</b> “Rewe 50” "
            "and it lands in the list right away.\n\n"
            "Without a caption you get a draft: just write “Rewe 50” next — "
            "or “Rewe” first and “50” after.\n\n"
            "I also do /login (browser access), /digest, /backup and /id."
        ),
    },
    "bot.open_app": {RU: "🐷 Открыть Sparschwein", EN: "🐷 Open Sparschwein"},
    "bot.open_card": {RU: "Открыть карту", EN: "Open the card"},
    "bot.fill_in_app": {RU: "Заполнить в приложении", EN: "Fill it in the app"},
    "bot.open_cards": {RU: "Открыть карты", EN: "Open the cards"},
    "bot.look": {RU: "Посмотреть", EN: "Take a look"},
    "bot.no_webapp_url": {
        RU: "\n\n⚠️ WEBAPP_URL не настроен, кнопка приложения недоступна.",
        EN: "\n\n⚠️ WEBAPP_URL is not set, so the app button is unavailable.",
    },
    "bot.added": {
        RU: "✅ Добавил: <b>{merchant}</b> · {amount} {currency}",
        EN: "✅ Added: <b>{merchant}</b> · {amount} {currency}",
    },
    "bot.shop_noted": {
        RU: "Записал магазин: <b>{merchant}</b>. Теперь сумму — просто числом.",
        EN: "Shop noted: <b>{merchant}</b>. Now the amount — just the number.",
    },
    "bot.amount_noted": {
        RU: "Записал сумму {amount}. Теперь название магазина.",
        EN: "Amount noted: {amount}. Now the shop name.",
    },
    "bot.draft_created": {
        RU: "📸 Черновик создан. Напишите магазин и сумму — например «Rewe 50».",
        EN: "📸 Draft created. Write the shop and the amount — for example “Rewe 50”.",
    },
    "bot.barcode_found": {
        RU: "\n▮▮ Штрихкод распознан ({format}) — покажу его чётким.",
        EN: "\n▮▮ Barcode decoded ({format}) — I will show it sharp.",
    },
    "bot.barcode_missing": {
        RU: (
            "\n⚠️ Штрихкод в скрине не читается — покажу саму картинку. "
            "Пришлите скрин целиком, не обрезанный: в мелком коде штрихи теряются."
        ),
        EN: (
            "\n⚠️ No readable barcode in that screenshot — I will show the picture itself. "
            "Send the full screen, uncropped: thin bars are lost at small sizes."
        ),
    },
    "bot.not_understood": {
        RU: "Не понял. Пришлите скрин карты с подписью «Rewe 50» — или напишите так же текстом.",
        EN: "I did not get that. Send a card screenshot captioned “Rewe 50” — or just write it.",
    },
    "bot.no_drafts": {
        RU: "Черновиков нет. Пришлите скрин карты — можно сразу с подписью «Rewe 50».",
        EN: "No drafts. Send a card screenshot — with a caption like “Rewe 50” if you like.",
    },
    "bot.login_only_private": {
        RU: "Ссылку для входа пришлю только в личку — напишите мне туда.",
        EN: "I only send login links in a private chat — message me there.",
    },
    "bot.login_no_url": {
        RU: "WEBAPP_URL не настроен — ссылку сформировать не из чего.",
        EN: "WEBAPP_URL is not set — there is no address to build a link from.",
    },
    "bot.login_link": {
        RU: (
            "Ссылка для входа в браузере (действует {minutes} минут, один раз):\n{url}\n\n"
            "Откройте её в браузере телефона и добавьте приложение на домашний экран. "
            "Никому не пересылайте — она пускает в наши карты."
        ),
        EN: (
            "Browser login link (valid {minutes} minutes, single use):\n{url}\n\n"
            "Open it in your phone's browser and add the app to the home screen. "
            "Do not forward it — it opens our cards."
        ),
    },
    "bot.backup_no_chat": {
        RU: "FAMILY_CHAT_ID не настроен — бэкап отправлять некуда.",
        EN: "FAMILY_CHAT_ID is not set — there is nowhere to send the backup.",
    },
    "bot.backup_working": {RU: "Собираю бэкап…", EN: "Building the backup…"},
    "bot.backup_done": {RU: "Готово: {summary}", EN: "Done: {summary}"},
    "bot.backup_failed": {RU: "Не получилось: {error}", EN: "It did not work: {error}"},
    "bot.digest_nothing": {
        RU: "Пока не о чем рассказывать: активных карт нет.",
        EN: "Nothing to report yet: no active cards.",
    },
    # --- validation ---
    "error.new_voucher_status": {
        RU: "Новый купон может быть только черновиком или активным",
        EN: "A new card can only be a draft or active",
    },
    "error.spent_or_remaining": {
        RU: "Укажите либо потраченную сумму, либо остаток",
        EN: "Give either the amount spent or the remaining balance",
    },
    "error.empty_comment": {
        RU: "Пустой комментарий",
        EN: "Empty comment",
    },
    # --- labels ---
    "label.voucher": {RU: "купон", EN: "card"},
    "label.voucher_numbered": {RU: "Купон #{id}", EN: "Card #{id}"},
    "label.someone": {RU: "Кто-то", EN: "Someone"},
    # --- family-chat notifications ---
    "notify.card_added": {
        RU: "🐷 {actor} добавил карту: <b>{label}</b>",
        EN: "🐷 {actor} added a card: <b>{label}</b>",
    },
    "notify.card_used": {
        RU: "✅ {actor} использовал карту: <b>{label}</b>",
        EN: "✅ {actor} used a card: <b>{label}</b>",
    },
    "notify.balance_emptied": {
        RU: "💳 {actor} потратил <b>{label}</b> до конца",
        EN: "💳 {actor} spent <b>{label}</b> down to zero",
    },
    "notify.balance_spent": {
        RU: "💳 {actor}: −{spent} {currency} с <b>{label}</b>, осталось {remaining} {currency}",
        EN: "💳 {actor}: −{spent} {currency} off <b>{label}</b>, {remaining} {currency} left",
    },
    "notify.balance_fixed": {
        RU: "💳 {actor} поправил остаток <b>{label}</b>: {remaining} {currency}",
        EN: "💳 {actor} corrected the balance of <b>{label}</b>: {remaining} {currency}",
    },
    "notify.comment": {
        RU: "💬 {actor} к карте <b>{label}</b>: {text}",
        EN: "💬 {actor} on <b>{label}</b>: {text}",
    },
    "notify.expiring": {
        RU: "⏳ <b>{label}</b> {when}{caveat}",
        EN: "⏳ <b>{label}</b> {when}{caveat}",
    },
    "notify.expires_today": {RU: "истекает сегодня", EN: "expires today"},
    "notify.expires_in_day": {
        RU: "истекает через {days} дн.",
        EN: "expires in {days} day",
    },
    "notify.expires_in_days": {
        RU: "истекает через {days} дн.",
        EN: "expires in {days} days",
    },
    "notify.expiry_estimated": {
        RU: " (срок по правилу магазина)",
        EN: " (date from the shop's rule)",
    },
    # --- backup ---
    "error.no_chat_for_backup": {
        RU: "FAMILY_CHAT_ID не задан — некуда отправлять бэкап",
        EN: "FAMILY_CHAT_ID is not set — there is nowhere to send the backup",
    },
    "error.no_chat_for_digest": {
        RU: "FAMILY_CHAT_ID не задан — сводку отправлять некуда",
        EN: "FAMILY_CHAT_ID is not set — there is nowhere to send the digest",
    },
    "backup.images_dropped": {
        RU: (
            "\n⚠️ Картинки не влезли в лимит Telegram ({limit} МБ) "
            "— в архиве только база. Фото есть в этом чате выше."
        ),
        EN: (
            "\n⚠️ The images did not fit Telegram's limit ({limit} MB) "
            "— the archive holds the database only. The photos are in this chat above."
        ),
    },
    "backup.summary": {
        RU: "{size} МБ, картинок: {images}{note}",
        EN: "{size} MB, images: {images}{note}",
    },
    "backup.caption": {
        RU: "💾 Бэкап Sparschwein · {stamp}\n{summary}\n{reason}",
        EN: "💾 Sparschwein backup · {stamp}\n{summary}\n{reason}",
    },
    "backup.reason_manual": {RU: "по запросу от {name}", EN: "requested by {name}"},
    "backup.reason_scheduled": {RU: "по расписанию", EN: "scheduled"},
    # --- weekly digest ---
    "digest.title": {
        RU: "🐷 <b>Сводка за неделю</b>",
        EN: "🐷 <b>The week in cards</b>",
    },
    "digest.on_cards": {
        RU: "На картах: <b>{amount} {currency}</b> на {cards} шт.",
        EN: "On the cards: <b>{amount} {currency}</b> across {cards} of them",
    },
    "digest.on_cards_one": {
        RU: "На картах: <b>{amount} {currency}</b> на 1 шт.",
        EN: "On the cards: <b>{amount} {currency}</b> on a single one",
    },
    "digest.spent": {RU: "Потратили: {amount} {currency}", EN: "Spent: {amount} {currency}"},
    "digest.spent_delta": {
        RU: "Потратили: {amount} {currency} — на {diff} {direction}, чем неделей раньше",
        EN: "Spent: {amount} {currency} — {diff} {direction} than the week before",
    },
    "digest.more": {RU: "больше", EN: "more"},
    "digest.less": {RU: "меньше", EN: "less"},
    "digest.spent_nothing": {
        RU: "За неделю ничего не потратили",
        EN: "Nothing was spent this week",
    },
    "digest.expiring": {
        RU: "⏳ Истекает за {days} дней: <b>{amount} {currency}</b> — {names}",
        EN: "⏳ Expiring within {days} days: <b>{amount} {currency}</b> — {names}",
    },
    "digest.and_more": {RU: " и ещё {count}", EN: " and {count} more"},
    "digest.uncertain": {
        RU: "❔ Под вопросом: {amount} {currency} на {cards} карт(ах) — проверьте остаток",
        EN: "❔ In question: {amount} {currency} on {cards} cards — check the balance",
    },
    "digest.uncertain_one": {
        RU: "❔ Под вопросом: {amount} {currency} на одной карте — проверьте остаток",
        EN: "❔ In question: {amount} {currency} on one card — check the balance",
    },
    "digest.expired": {
        RU: "⚠️ Уже истекли, а деньги остались: <b>{amount} {currency}</b>",
        EN: "⚠️ Already expired with money left: <b>{amount} {currency}</b>",
    },
}


def language_for(code: str | None, default: str = RU) -> str:
    """Narrow anything ("ru-RU", "en-GB,en;q=0.9", None) to a language we speak."""
    if not code:
        return default
    first = code.split(",")[0].strip().lower()
    return EN if first.startswith("en") else RU if first.startswith("ru") else default


def t(key: str, language: str = RU, **params: Any) -> str:
    forms = MESSAGES.get(key)
    if forms is None:
        # A missing key must be obvious in testing, not silently blank in the UI.
        return key
    return forms.get(language, forms[RU]).format(**params)


class Message(str):
    """An error detail that remembers how to say itself in another language.

    It *is* a string (already rendered in the default language), so logs, tests
    and any handler we do not control keep working; the API boundary re-renders
    it in the reader's language before the response goes out.
    """

    key: str
    params: dict[str, Any]

    def __new__(cls, key: str, **params: Any) -> "Message":
        message = super().__new__(cls, t(key, default_language(), **params))
        message.key = key
        message.params = params
        return message

    def render(self, language: str) -> str:
        return t(self.key, language, **self.params)


def request_language(
    accept_language: Annotated[str | None, Header()] = None,
) -> str:
    """The language the app asked for, as a FastAPI dependency."""
    return language_for(accept_language, default_language())


def default_language() -> str:
    """The language for messages with no single reader — the family chat."""
    from app.config import settings

    return settings.default_language


def group_t(key: str, **params: Any) -> str:
    """A message for the family chat, where nobody's own language applies."""
    return t(key, default_language(), **params)
