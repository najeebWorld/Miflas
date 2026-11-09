from mabat.ingest.encoding import declared_codec, detect_encoding

HEBREW = 'B110 סטודיו אלון עיצוב בע"מ הכנסות ממכירות'


def test_detects_windows_hebrew():
    assert detect_encoding(HEBREW.encode("iso8859_8")) == "cp1255"
    assert detect_encoding(HEBREW.encode("cp1255")) == "cp1255"


def test_detects_dos_hebrew():
    assert detect_encoding(HEBREW.encode("cp862")) == "cp862"


def test_detects_utf8():
    assert detect_encoding(HEBREW.encode("utf-8")) == "utf-8"


def test_detects_utf8_with_bom():
    assert detect_encoding(b"\xef\xbb\xbf" + HEBREW.encode("utf-8")) == "utf-8-sig"


def test_ascii_only_defaults_to_windows():
    assert detect_encoding(b"A100000000001514000017") == "cp1255"


def test_declared_codec():
    assert declared_codec("1") == "cp1255"
    assert declared_codec("2") == "cp862"
    assert declared_codec("0") is None
    assert declared_codec("") is None
