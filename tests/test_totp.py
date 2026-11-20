"""The TOTP helper, against the RFC 6238 SHA-1 test vectors.

RFC 6238 Appendix B lists eight-digit codes for the ASCII seed
"12345678901234567890". kvmd (pyotp's defaults) uses six digits, which is
the same HOTP value mod 10**6, zero-padded. Both forms are checked, so the
six-digit expectations are not just this implementation agreeing with
itself.
"""

from __future__ import annotations

import base64

import pytest

from tests.pure import load

totp = load("totp")

RFC_SEED = b"12345678901234567890"
RFC_SECRET = base64.b32encode(RFC_SEED).decode()  # GEZDGNBVGY3TQOJQ...

# (Unix time, eight-digit code from RFC 6238 Appendix B, SHA-1 column)
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("at", "code"), RFC_VECTORS)
def test_the_rfc_vectors_at_eight_digits(at, code):
    assert totp.totp(RFC_SECRET, at, digits=8) == code


@pytest.mark.parametrize(("at", "code"), RFC_VECTORS)
def test_six_digits_is_the_rfc_value_mod_a_million(at, code):
    expected = str(int(code) % 10**6).zfill(6)
    assert totp.totp(RFC_SECRET, at) == expected


def test_the_six_digit_codes_spelt_out():
    # 1111111109 -> 07081804 -> 081804: the leading zero is kept.
    assert totp.totp(RFC_SECRET, 59) == "287082"
    assert totp.totp(RFC_SECRET, 1111111109) == "081804"
    assert totp.totp(RFC_SECRET, 1234567890) == "005924"


def test_the_code_holds_for_one_thirty_second_step():
    # 1111111080 to 1111111109 is one step; 1111111110 starts the next.
    assert totp.totp(RFC_SECRET, 1111111080) == totp.totp(RFC_SECRET, 1111111109)
    assert totp.totp(RFC_SECRET, 1111111110) == totp.totp(RFC_SECRET, 1111111111)
    assert totp.totp(RFC_SECRET, 1111111110) != totp.totp(RFC_SECRET, 1111111109)


def test_without_a_time_it_uses_the_clock(monkeypatch):
    monkeypatch.setattr(totp.time, "time", lambda: 59.0)
    assert totp.totp(RFC_SECRET) == "287082"


@pytest.mark.parametrize(
    "written",
    [
        RFC_SECRET,
        RFC_SECRET.lower(),
        RFC_SECRET.rstrip("="),
        " ".join(RFC_SECRET[i : i + 4] for i in range(0, len(RFC_SECRET), 4)),
        "-".join(RFC_SECRET[i : i + 4] for i in range(0, len(RFC_SECRET), 4)),
        f"  {RFC_SECRET.lower()}\n",
    ],
)
def test_the_secret_is_accepted_however_it_was_copied(written):
    assert totp.normalise_secret(written) == RFC_SECRET.rstrip("=")
    assert totp.totp(written, 59) == "287082"


def test_a_secret_without_its_padding_decodes():
    # 10 bytes is 16 base32 characters with no padding; 11 bytes needs some.
    secret = base64.b32encode(b"\x01" * 11).decode().rstrip("=")
    assert len(secret) % 8 != 0
    assert totp.normalise_secret(secret) == secret
    assert len(totp.totp(secret, 0)) == 6


@pytest.mark.parametrize("bad", ["", "   ", "====", "not base32!", "ABC1", "A"])
def test_a_secret_that_is_not_base32_is_refused(bad):
    with pytest.raises(ValueError):
        totp.normalise_secret(bad)
    with pytest.raises(ValueError):
        totp.totp(bad, 0)


def test_hotp_matches_rfc_4226():
    # RFC 4226 Appendix D, the same seed, counters 0 and 9.
    assert totp.hotp(RFC_SEED, 0) == "755224"
    assert totp.hotp(RFC_SEED, 9) == "520489"
