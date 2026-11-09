from mabat.sampledata import write_sample


def test_sample_is_deterministic(tmp_path, fm):
    a = write_sample(tmp_path / "a", fm=fm)
    b = write_sample(tmp_path / "b", fm=fm)
    for name in ("INI.TXT", "BKMVDATA.TXT"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_sample_follows_spec_folder_layout(tmp_path, fm):
    folder = write_sample(tmp_path, fm=fm)
    assert folder.relative_to(tmp_path).as_posix() == "OPENFRMT/51400001.26/07011000"


def test_every_line_has_the_official_length_and_crlf(sample_dir, fm):
    raw = (sample_dir / "BKMVDATA.TXT").read_bytes()
    assert raw.endswith(b"\r\n")
    lines = raw.decode("iso8859_8").split("\r\n")[:-1]
    assert fm.record_code(lines[0]) == "A100"
    assert fm.record_code(lines[-1]) == "Z900"
    for line in lines:
        assert len(line) == fm.length(fm.record_code(line))


def test_ini_has_header_and_summary_lines(sample_dir, fm):
    lines = (sample_dir / "INI.TXT").read_bytes().decode("iso8859_8").split("\r\n")[:-1]
    assert len(lines[0]) == 466
    assert [line[:4] for line in lines[1:]] == ["B100", "B110", "C100", "D110"]
    assert all(len(line) == 19 for line in lines[1:])


def test_every_journal_entry_balances(sample_dir, fm):
    lines = (sample_dir / "BKMVDATA.TXT").read_bytes().decode("iso8859_8").split("\r\n")[:-1]
    balance: dict[str, int] = {}
    for line in lines:
        if fm.record_code(line) != "B100":
            continue
        v = fm.slice_record("B100", line)
        signed = int(v["amount"]) * (1 if v["debit_credit"] == "1" else -1)
        balance[v["transaction_number"]] = balance.get(v["transaction_number"], 0) + signed
    assert balance and all(total == 0 for total in balance.values())
