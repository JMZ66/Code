"""Generate Excel import template. Run: python data/seed/chemicals_import_template.xlsx.py"""
from pathlib import Path
from openpyxl import Workbook

out = Path(__file__).with_suffix("").with_name("chemicals_import_template.xlsx")
wb = Workbook()
ws = wb.active
ws.title = "化学品"
ws.append(["名称", "CAS", "浓度", "规格", "生产厂家"])
ws.append(["硫酸", "7664-93-9", "98%", "500mL", "演示厂家"])
wb.save(out)
print(out)
