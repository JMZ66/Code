import xlwt

from office_kit.parse import parse_path

from tests.factory import bill_xlsx


def test_xlsx_formula_cache_merge_hidden_validation_and_notes(tmp_path):
    path = bill_xlsx(tmp_path / "bill.xlsx")
    document = parse_path(path)
    assert document.status == "ok"
    sheet = document.excel.sheets[0]
    assert sheet.name == "清单"
    assert sheet.state == "visible"
    assert "A1:D1" in sheet.merged_ranges
    assert 4 in sheet.hidden_rows
    assert "E" in sheet.hidden_columns
    hidden = document.excel.sheets[1]
    assert hidden.state == "hidden"
    assert hidden.cells[0].cached_text == "仅供内部"
    by_coord = {cell.coordinate: cell for cell in sheet.cells}
    assert by_coord["D3"].cached_text == "250"
    assert by_coord["C3"].number_format == "¥#,##0.00"
    assert by_coord["C3"].font["bold"] is True
    assert by_coord["C3"].font["name"] == "宋体"
    assert by_coord["A1"].comment["text"] == "请复核合价"
    assert by_coord["A1"].comment["author"] == "审核人"
    assert by_coord["G3"].formula == "=B3*C3"
    assert by_coord["G3"].cached_value in {999, 999.0, "999"}
    assert any(item["type"] == "list" and "F3:F5" in item["sqref"] for item in sheet.data_validations)
    threaded = [item for item in sheet.comments if item["kind"] == "threaded"]
    assert threaded and threaded[0]["text"] == "数量待确认"
    assert threaded[0]["author"] == "造价员"
    hidden_install = by_coord["A4"]
    assert hidden_install.hidden_row is True
    assert "formulas" in document.features
    assert any(item["code"] == "formula_cache_only" for item in document.warnings)


def test_xls_values_merge_and_hidden(tmp_path):
    path = tmp_path / "legacy.xls"
    book = xlwt.Workbook()
    sheet = book.add_sheet("清单")
    sheet.write(0, 0, "名称")
    sheet.write(0, 1, "数量")
    sheet.write(1, 0, "泵")
    sheet.write(1, 1, 2)
    sheet.write_merge(2, 2, 0, 1, "合计")
    sheet.row(1).hidden = 1
    sheet.col(2).hidden = 1
    sheet.write(0, 2, "隐藏列")
    hidden = book.add_sheet("隐藏表")
    hidden.visibility = 1
    hidden.write(0, 0, "内部")
    book.save(str(path))
    document = parse_path(path)
    assert document.status == "ok"
    assert any(item["code"] == "xls_limited" for item in document.warnings)
    listing = document.excel.sheets[0]
    assert any(cell.cached_text == "泵" for cell in listing.cells)
    assert any(cell.cached_value == 2 for cell in listing.cells)
    assert listing.merged_ranges == ["A3:B3"]
    assert 2 in listing.hidden_rows
    assert "C" in listing.hidden_columns
    assert document.excel.sheets[1].state == "hidden"
    assert document.excel.sheets[1].cells[0].cached_text == "内部"
