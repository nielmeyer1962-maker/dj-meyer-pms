import openpyxl
import pytest

from app.services.clients.readers import _clean, read_rows


def _write_csv(tmp_path, rows):
    path = tmp_path / "src.csv"
    path.write_text("\n".join(",".join(r) for r in rows), encoding="utf-8")
    return path


def test_reads_csv_with_header_row_and_keys_by_header(tmp_path):
    path = _write_csv(tmp_path, [["Name", "Age"], ["Alice", "30"], ["Bob", "40"]])
    rows = read_rows(path, header_row=1)
    assert [r.values for r in rows] == [
        {"Name": "Alice", "Age": "30"},
        {"Name": "Bob", "Age": "40"},
    ]
    assert rows[0].number == 2  # 1-based sheet row


def test_header_row_skips_title_banner(tmp_path):
    path = _write_csv(tmp_path, [["TITLE", ""], ["Name", "Age"], ["Alice", "30"]])
    rows = read_rows(path, header_row=2)
    assert rows[0].values == {"Name": "Alice", "Age": "30"}
    assert rows[0].number == 3


def test_trims_and_blank_becomes_none(tmp_path):
    path = _write_csv(tmp_path, [["Name", "Note"], [" Alice ", "   "]])
    assert read_rows(path, header_row=1)[0].values == {"Name": "Alice", "Note": None}


def test_fully_empty_rows_skipped(tmp_path):
    path = _write_csv(tmp_path, [["Name", "Note"], ["", ""], ["Bob", "x"], ["", ""]])
    rows = read_rows(path, header_row=1)
    assert [r.values["Name"] for r in rows] == ["Bob"]


def test_unsupported_extension_raises(tmp_path):
    bad = tmp_path / "data.txt"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported source file type"):
        read_rows(bad)


@pytest.mark.parametrize(
    "raw, expected",
    [(None, None), ("  ", None), ("  hi ", "hi"), (2.0, "2"), (7, "7"), ("0012", "0012")],
)
def test_clean(raw, expected):
    assert _clean(raw) == expected


def test_xlsx_override_names_unlabelled_column(tmp_path):
    path = tmp_path / "src.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Surname", None, "ID"])  # col B has no header
    ws.append(["Smit", "Johan", "0012345"])  # leading-zero id preserved as text
    wb.save(path)
    rows = read_rows(path, sheet="Data", header_row=1, header_overrides={2: "full_name"})
    assert rows[0].values == {"Surname": "Smit", "full_name": "Johan", "ID": "0012345"}
