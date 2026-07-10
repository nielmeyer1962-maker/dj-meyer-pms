from types import SimpleNamespace

import pytest

from app.models.client import EntityType, VatCategory
from app.services.clients import importer as im
from app.services.clients.readers import SourceRow


def _staff():
    return [
        SimpleNamespace(id=1, code="NIEL", full_name="Niel Meyer"),
        SimpleNamespace(id=3, code="CANDI", full_name="Candice van der Merwe"),
        SimpleNamespace(id=8, code="TSEGO", full_name="Tsego Mogale"),
    ]


# --- entity-type derivation ---


@pytest.mark.parametrize(
    "reg, expected",
    [
        ("2015/123456/07", EntityType.PTY_LTD),
        ("1994/000403/23", EntityType.CC),
        ("2010/000111/08", EntityType.NPC),
        ("2020/000222/21", EntityType.INC),
        ("2019/000333/06", EntityType.NPC),
    ],
)
def test_entity_type_from_suffix(reg, expected):
    entity_type, issue = im.derive_entity_type(reg)
    assert entity_type is expected
    assert issue is None


def test_entity_type_unknown_suffix_flagged():
    entity_type, issue = im.derive_entity_type("2015/123456/99")
    assert entity_type is None
    assert "unknown registration suffix" in issue


# --- reg normalisation ---


def test_reg_normalisation_pads():
    assert im.normalize_reg_number("2015/123/7") == ("2015/000123/07", None)


def test_reg_normalisation_malformed_keeps_raw_and_flags():
    value, issue = im.normalize_reg_number("not-a-reg")
    assert value == "not-a-reg"
    assert "malformed" in issue


# --- id validation ---


def test_id_thirteen_digits_accepted():
    assert im.classify_id_number("8001015009087") == ("8001015009087", None)


def test_id_passport_accepted_as_is():
    assert im.classify_id_number("A1234567") == ("A1234567", None)


def test_id_registration_shaped_flagged():
    value, issue = im.classify_id_number("2017/006059/07")
    assert value == "2017/006059/07"
    assert "registration-shaped" in issue


def test_id_missing_flagged():
    assert im.classify_id_number(None)[0] is None
    assert im.classify_id_number("  ")[1] == "missing ID number"


# --- year-end, vat, flags ---


@pytest.mark.parametrize(
    "text, month, day", [("February", 2, 28), ("June", 6, 30), ("Dec", 12, 31)]
)
def test_year_end_month_end_day(text, month, day):
    assert im.derive_year_end(text) == (month, day, None)


def test_year_end_unknown_month_flagged():
    month, day, issue = im.derive_year_end("Smarch")
    assert (month, day) == (None, None)
    assert "unrecognised year-end month" in issue


@pytest.mark.parametrize(
    "value, has_vat, category, note, has_issue",
    [
        ("A", True, VatCategory.A, None, False),
        ("c", True, VatCategory.C, None, False),
        ("Not registered", False, None, None, False),
        ("", False, None, None, False),
        (None, False, None, None, False),
        ("Own", False, None, "handles own VAT", False),
        ("weird", False, None, None, True),
    ],
)
def test_derive_vat(value, has_vat, category, note, has_issue):
    result_has_vat, result_category, result_note, result_issue = im.derive_vat(value)
    assert result_has_vat is has_vat
    assert result_category is category
    assert result_note == note
    assert (result_issue is not None) is has_issue


@pytest.mark.parametrize(
    "value, expected",
    [(" Y", True), ("yes", True), ("TRUE", True), ("No", False), ("", False), (None, False)],
)
def test_parse_flag(value, expected):
    assert im.parse_flag(value) is expected


# --- staff mapping ---


def test_staff_lookup_by_first_name_full_name_and_code():
    index = im.build_staff_index(_staff())
    assert im.lookup_staff("Niel", index) == (1, None)  # first name
    assert im.lookup_staff("niel meyer", index) == (1, None)  # full name, case-insensitive
    assert im.lookup_staff("CANDI", index) == (3, None)  # code
    assert im.lookup_staff(" Candice ", index) == (3, None)  # trimmed first name


def test_staff_lookup_unknown_and_blank_flagged():
    index = im.build_staff_index(_staff())
    sid, issue = im.lookup_staff("Nobody", index)
    assert sid is None and "unknown staff member" in issue
    sid, issue = im.lookup_staff("   ", index)
    assert sid is None and "no staff member specified" in issue


def test_staff_lookup_ambiguous_first_name_left_unallocated():
    staff = [
        SimpleNamespace(id=1, code="SAMA", full_name="Sam Alpha"),
        SimpleNamespace(id=2, code="SAMB", full_name="Sam Beta"),
    ]
    index = im.build_staff_index(staff)
    sid, issue = im.lookup_staff("Sam", index)
    assert sid is None and "ambiguous" in issue
    # Unambiguous full name still resolves.
    assert im.lookup_staff("Sam Alpha", index) == (1, None)


# --- mappers ---


def test_map_company_row_clean():
    index = im.build_staff_index(_staff())
    values = {
        im.CO_NAME: "Acme (Pty) Ltd",
        im.CO_REG: "2015/123456/07",
        im.CO_MONTH: "March",
        im.CO_DUE_DAY: "15",
        im.CO_CONTACT: "Jane Doe",
        im.CO_EMAIL: "jane@acme.co.za",
        im.CO_STAFF: "Niel",
        im.CO_VAT: "B",
        im.CO_PAYE: "Yes",
        im.CO_PROVISIONAL: "Yes",
        im.CO_YEAR_END: "February",
    }
    row = im.map_company_row(5, values, index)
    assert row.entity_type is EntityType.PTY_LTD
    assert row.natural_key == "2015/123456/07"
    assert row.issues == []
    assert row.fields["legal_name"] == "Acme (Pty) Ltd"
    assert row.fields["cipc_anniversary_month"] == 3
    assert row.fields["cipc_anniversary_day"] == 15
    assert row.fields["year_end_month"] == 2
    assert row.fields["year_end_day"] == 28
    assert row.fields["has_vat"] is True
    assert row.fields["vat_category"] is VatCategory.B
    assert row.fields["has_paye"] is True
    assert row.fields["has_provisional_tax"] is True
    assert row.fields["has_income_tax"] is True
    assert row.fields["contact_person"] == "Jane Doe"
    assert row.fields["allocated_staff_id"] == 1


def test_map_company_row_lone_cipc_month_flagged():
    index = im.build_staff_index(_staff())
    values = {im.CO_NAME: "X CC", im.CO_REG: "2000/000001/23", im.CO_MONTH: "March"}
    row = im.map_company_row(2, values, index)
    assert row.fields["cipc_anniversary_month"] is None
    assert row.fields["cipc_anniversary_day"] is None
    assert any("both be present" in issue for issue in row.issues)


def test_map_individual_row_sole_prop():
    index = im.build_staff_index(_staff())
    values = {
        im.IN_NAME: "Smit, J",
        im.IN_FULLNAME: "Johan Smit",
        im.IN_ID: "8001015009087",
        im.IN_TAXREF: "0001234567",
        im.IN_EMAIL: "johan@x.co.za",
        im.IN_STAFF: "Candice",
        im.IN_SOLEPROP: "Joe's Welding",
        im.IN_PROVISIONAL: "Y",
    }
    row = im.map_individual_row(3, values, index)
    assert row.entity_type is EntityType.SOLE_PROP
    assert row.fields["trading_name"] == "Joe's Welding"
    assert row.natural_key == "8001015009087"
    assert row.fields["known_as"] == "Johan Smit"
    assert row.fields["tax_ref"] == "0001234567"
    assert row.fields["has_income_tax"] is True
    assert row.fields["has_provisional_tax"] is True
    assert row.fields["allocated_staff_id"] == 3


def test_map_individual_row_plain_no_taxref():
    index = im.build_staff_index(_staff())
    values = {im.IN_NAME: "Alone, A", im.IN_ID: "9002026009088"}
    row = im.map_individual_row(4, values, index)
    assert row.entity_type is EntityType.INDIVIDUAL
    assert "trading_name" not in row.fields
    assert row.fields["has_income_tax"] is False  # no tax_ref
    assert row.fields["allocated_staff_id"] is None  # blank staff
    assert any("no staff member specified" in issue for issue in row.issues)


# --- orchestration ---


def _individual_rows():
    return [
        SourceRow(2, {im.IN_NAME: "A, A", im.IN_ID: "111", im.IN_STAFF: "Niel"}),
        SourceRow(3, {im.IN_NAME: "B, B", im.IN_ID: "222", im.IN_STAFF: "Niel"}),
        SourceRow(4, {im.IN_NAME: "C, C", im.IN_ID: "111", im.IN_STAFF: "Niel"}),  # dup of row 2
        SourceRow(5, {im.IN_NAME: "", im.IN_ID: "999"}),  # junk: no name
    ]


def test_parse_file_skips_junk_and_reconciles_counts():
    report = im.parse_file(_individual_rows(), im.INDIVIDUALS, _staff())
    assert report.source_rows == 4
    assert report.real_rows == 3  # blank-name row dropped
    assert len(report.to_insert) == 2  # 111 (first) + 222
    assert len(report.duplicates) == 1  # second 111 skipped
    assert (
        len(report.to_insert) + len(report.to_update) + len(report.duplicates) == report.real_rows
    )


def test_parse_file_duplicate_flags_first_row():
    report = im.parse_file(_individual_rows(), im.INDIVIDUALS, _staff())
    first = next(r for r in report.to_insert if r.natural_key == "111")
    assert any("shares natural key 111 with row 4" in issue for issue in first.issues)
    assert first.fields["data_quality_note"]  # composed from issues
    assert report.duplicates[0][2] == "111"


def test_parse_file_existing_key_classified_as_update():
    report = im.parse_file(
        _individual_rows(), im.INDIVIDUALS, _staff(), existing_keys=frozenset({"222"})
    )
    assert [r.natural_key for r in report.to_update] == ["222"]
    assert "222" not in [r.natural_key for r in report.to_insert]


def test_parse_file_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown import kind"):
        im.parse_file([], "trusts", _staff())
