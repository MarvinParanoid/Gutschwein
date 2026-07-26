"""Localization: the dictionary itself, and the two ways a language is chosen."""

import re

import pytest
from fastapi.testclient import TestClient

from app.i18n import EN, LANGUAGES, MESSAGES, RU, Message, language_for, t

PLACEHOLDER = re.compile(r"{(\w+)}")


def test_every_message_exists_in_every_language():
    missing = [
        (key, language)
        for key, forms in MESSAGES.items()
        for language in LANGUAGES
        if language not in forms
    ]
    assert missing == []


def test_translations_take_the_same_placeholders():
    """A typo in a placeholder only shows up as a KeyError in production."""
    mismatched = [
        key
        for key, forms in MESSAGES.items()
        if len({frozenset(PLACEHOLDER.findall(text)) for text in forms.values()}) > 1
    ]
    assert mismatched == []


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("ru", RU),
        ("ru-RU", RU),
        ("en", EN),
        ("en-GB,en;q=0.9,ru;q=0.8", EN),
        ("de-DE", RU),  # nothing we speak: fall back to the default
        ("", RU),
        (None, RU),
    ],
)
def test_language_for(header, expected):
    assert language_for(header, RU) == expected


def test_unknown_key_is_visible_rather_than_blank():
    assert t("error.no_such_key", EN) == "error.no_such_key"


def test_message_reads_as_text_but_keeps_its_key():
    message = Message("error.file_too_big", limit=12)
    assert message == "Файл больше 12 МБ"
    assert message.render(EN) == "The file is larger than 12 MB"


def test_error_follows_accept_language(client: TestClient):
    response = client.get("/api/vouchers/999999", headers={"Accept-Language": "en-US"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Card not found"


def test_error_defaults_to_russian(client: TestClient):
    assert client.get("/api/vouchers/999999").json()["detail"] == "Купон не найден"


def test_parametrized_error_is_rendered_with_its_values(client: TestClient):
    card = client.post(
        "/api/vouchers",
        json={"merchant": "Rewe", "value_kind": "amount", "value_amount": "10"},
    ).json()
    response = client.post(
        f"/api/vouchers/{card['id']}/balance",
        json={"spent": "25"},
        headers={"Accept-Language": "en"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot spend 25 — the card holds 10 EUR"


def test_validation_error_is_localized(client: TestClient):
    response = client.post(
        "/api/vouchers/1/comments", json={"text": "   "}, headers={"Accept-Language": "en"}
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"].endswith("Empty comment")


async def test_user_language_comes_from_telegram():
    """The stored language is what background jobs read; see upsert_user."""
    from app.auth import TelegramUser, upsert_user
    from app.db import SessionLocal

    async with SessionLocal() as session:
        user = await upsert_user(
            session, TelegramUser({"id": 777, "first_name": "Ann", "language_code": "en-GB"})
        )
        assert user.language == EN
        # Switching the phone's language switches the bot's, too.
        user = await upsert_user(
            session, TelegramUser({"id": 777, "first_name": "Ann", "language_code": "ru"})
        )
        assert user.language == RU


def test_group_messages_ignore_the_reader(monkeypatch):
    """The family chat has no single reader, so it always uses DEFAULT_LANGUAGE."""
    from app.config import settings
    from app.i18n import group_t

    assert group_t("digest.title") == "🐷 <b>Сводка за неделю</b>"
    monkeypatch.setattr(settings, "default_language", EN)
    assert group_t("digest.title") == "🐷 <b>The week in cards</b>"
