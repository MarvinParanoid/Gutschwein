"""initData signature checks, signed exactly the way Telegram signs it."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.auth import verify_init_data

TOKEN = "8608107949:AAHtest-token-for-unit-tests"


def sign(fields: dict[str, str], token: str = TOKEN) -> str:
    """Build initData: the hash covers every field except `hash` itself."""
    check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signed = dict(fields)
    signed["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(signed)


def base_fields(**overrides: str) -> dict[str, str]:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHtest",
        "user": json.dumps({"id": 151724313, "first_name": "Аня"}, ensure_ascii=False),
    }
    fields.update(overrides)
    return fields


def test_accepts_init_data_with_signature_field() -> None:
    """Modern clients send `signature`; it belongs in the data-check-string.

    Excluding it made every real Mini App request fail with "invalid signature"
    while hand-built fixtures without the field still passed.
    """
    fields = base_fields(signature="9CFtRJMlBcpNFrpZTLLJfvKPa9lNXHtvJyJHTMEXAMPLE")
    assert verify_init_data(sign(fields), TOKEN, 3600).id == 151724313


def test_accepts_init_data_without_signature_field() -> None:
    assert verify_init_data(sign(base_fields()), TOKEN, 3600).id == 151724313


def test_rejects_tampered_payload() -> None:
    init_data = sign(base_fields(signature="abc"))
    tampered = init_data.replace("151724313", "999999999")
    with pytest.raises(ValueError, match="подпись"):
        verify_init_data(tampered, TOKEN, 3600)


def test_rejects_other_bots_token() -> None:
    with pytest.raises(ValueError, match="подпись"):
        verify_init_data(sign(base_fields()), "111:OTHER-TOKEN", 3600)


def test_rejects_stale_init_data() -> None:
    old = base_fields(auth_date=str(int(time.time()) - 99_999))
    with pytest.raises(ValueError, match="просрочен"):
        verify_init_data(sign(old), TOKEN, 3600)


def test_rejects_missing_hash() -> None:
    with pytest.raises(ValueError, match="без hash"):
        verify_init_data(urlencode(base_fields()), TOKEN, 3600)


def test_rejects_missing_user_block() -> None:
    fields = {"auth_date": str(int(time.time())), "query_id": "AAHtest"}
    with pytest.raises(ValueError, match="без блока user"):
        verify_init_data(sign(fields), TOKEN, 3600)
