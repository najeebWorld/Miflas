"""Hebrew charset detection for OPENFRMT files.

The spec allows ISO-8859-8-i (Windows) or CP-862 (DOS) and declares the choice
in A000 field 1029. We detect from the bytes and only cross-check the
declaration, because the declaration itself may be wrong.
"""
from __future__ import annotations

# Hebrew letters alef..tav in each single-byte code page.
_WINDOWS_HEBREW = range(0xE0, 0xFB)
_DOS_HEBREW = range(0x80, 0x9B)

_DECLARED = {"1": "cp1255", "2": "cp862"}


def detect_encoding(data: bytes) -> str:
    """Return a Python codec name: utf-8, utf-8-sig, cp1255 or cp862.

    cp1255 is used for ISO-8859-8 input: the Hebrew letters share the same
    code points and cp1255 also covers the punctuation Windows software emits.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if all(b < 0x80 for b in data):
        return "cp1255"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    windows = sum(1 for b in data if b in _WINDOWS_HEBREW)
    dos = sum(1 for b in data if b in _DOS_HEBREW)
    return "cp862" if dos > windows else "cp1255"


def declared_codec(charset_flag: str) -> str | None:
    """Codec declared in A000 field 1029 (1 = ISO-8859-8-i, 2 = CP-862)."""
    return _DECLARED.get(charset_flag.strip())
