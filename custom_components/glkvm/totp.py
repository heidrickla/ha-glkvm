"""RFC 6238 time-based one-time passwords, for kvmd's two-factor login.

GL.iNet's kvmd checks a second factor when its TOTP secret file is not empty:
it takes the last six characters of the supplied password as the code
(`pyotp.TOTP(secret).verify(code, valid_window=1)`) and the rest as the
password. That applies to the `X-KVMD-Passwd` header this integration sends
on every request, so the client appends a fresh code to each one.

kvmd uses pyotp's defaults: HMAC-SHA1, a 30-second step from the Unix epoch
and six digits. Standard library only, and no Home Assistant import, so the
client can keep running on a bare interpreter.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import time

DIGITS = 6
STEP = 30


def normalise_secret(secret: str) -> str:
    """The base32 secret as kvmd's setup screen shows it, cleaned up.

    Authenticator apps and setup pages group the secret in blocks, print it
    in lower case and drop the `=` padding; all three are accepted. Raises
    ValueError when what is left is not base32 or decodes to nothing.
    """
    cleaned = "".join(secret.split()).replace("-", "").upper().rstrip("=")
    if not cleaned:
        raise ValueError("empty TOTP secret")
    padded = cleaned + "=" * (-len(cleaned) % 8)
    try:
        key = base64.b32decode(padded, casefold=False)
    except (binascii.Error, ValueError) as err:
        raise ValueError("TOTP secret is not base32") from err
    if not key:
        raise ValueError("TOTP secret decodes to nothing")
    return cleaned


def _key(secret: str) -> bytes:
    cleaned = normalise_secret(secret)
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def hotp(key: bytes, counter: int, *, digits: int = DIGITS) -> str:
    """RFC 4226 HOTP over HMAC-SHA1: the code for one counter value."""
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    (value,) = struct.unpack(">I", digest[offset : offset + 4])
    return str((value & 0x7FFFFFFF) % 10**digits).zfill(digits)


def totp(secret: str, at: float | None = None, *, digits: int = DIGITS) -> str:
    """The code valid at `at` (Unix seconds; now when omitted)."""
    now = time.time() if at is None else at
    return hotp(_key(secret), int(now // STEP), digits=digits)
