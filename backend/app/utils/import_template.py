"""历史数据导入模板下载 (xlsx, 带示例行与填写说明)."""
import io
from datetime import datetime

from flask import Response

from ..domain.constants import DATA_SOURCE_LABELS, PERIOD_LABELS
from ..domain.standards import POLLUTANTS

TEMPLATE_HEADERS = ["监测点编码", "监测因子", "监测时间", "数值", "数据来源", "录入人", "备注"]


def template_response(period="hourly"):
    try:
        from openpyxl import Workbook
        from openpyxl.comments import Comment
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError:  # pragma: no cover - 依赖已声明
        return _csv_fallback()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "历史数据导入"

    header_fill = PatternFill("solid", fgColor="2563EB")
    header_font = Font(color="FFFFFF", bold=True)
    for column, header in enumerate(TEMPLATE_HEADERS, start=1):
        cell = sheet.cell(row=1, column=column, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    comments = {
        1: "与监测点台账中的站点编码一致, 必填",
        2: "支持因子代码(PM25/PM10/SO2/NO2/CO/O3)或名称(PM2.5/SO₂/臭氧), 必填",
        3: "格式 YYYY-MM-DD HH:MM, 如 2026-09-01 10:00; 日均值可只填日期, 必填",
        4: "监测浓度数值, 允许 0~10000, 必填; 单位由因子自动判定, 无需填写",
        5: "手工录入 / 设备上传 / 历史导入, 留空默认“历史导入”",
        6: "选填, 最长 64 字",
        7: "选填, 最长 500 字",
    }
    for column, text in comments.items():
        sheet.cell(row=1, column=column).comment = Comment(text, "系统")

    now = datetime(2026, 9, 1, 10, 0)
    samples = [
        ["TEST-001", "PM2.5", "2026-09-01 09:00", 58.0, "历史导入", "张三", "历史台账补录(示例, 导入前请删除)"],
        ["TEST-001", "SO₂", "2026-09-01 09:00", 640.0, "历史导入", "张三", ""],
        ["TEST-002", "O₃", "2026-09-01", 132.5, "历史导入", "李四", "日均值示例"],
    ]
    for row_index, values in enumerate(samples, start=2):
        for column, value in enumerate(values, start=1):
            sheet.cell(row=row_index, column=column, value=value)
    sheet.cell(row=2, column=3).number_format = "yyyy-mm-dd hh:mm"
    sheet.cell(row=4, column=3).number_format = "yyyy-mm-dd"

    pollutant_validation = DataValidation(
        type="list",
        formula1='"%s"' % ",".join(meta["label"] for meta in POLLUTANTS.values()),
        allow_blank=True,
    )
    pollutant_validation.error = "请选择标准中的监测因子"
    pollutant_validation.errorTitle = "监测因子不合法"
    sheet.add_data_validation(pollutant_validation)
    pollutant_validation.add("B2:B5000")

    source_validation = DataValidation(
        type="list",
        formula1='"%s"' % ",".join(DATA_SOURCE_LABELS.values()),
        allow_blank=True,
    )
    sheet.add_data_validation(source_validation)
    source_validation.add("E2:E5000")

    widths = (14, 12, 20, 12, 14, 12, 36)
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + column)].width = width
    sheet.freeze_panes = "A2"

    note = workbook.create_sheet("填写说明")
    period_label = PERIOD_LABELS.get(period, period)
    lines = [
        "历史监测数据批量导入模板",
        "",
        "1. 红色表头列为必填: 监测点编码、监测因子、监测时间、数值。",
        "2. 监测点编码必须与“监测点台账”中已有编码一致, 否则该行无法入库。",
        "3. 监测因子支持: PM2.5 / PM10 / SO₂ / NO₂ / CO / O₃, 也可填写代码 PM25/PM10/SO2/NO2/CO/O3。",
        "4. 监测时间支持 “2026-09-01 10:00”“2026/09/01 10:00” 等写法; 日均值允许只填日期。",
        "5. 数值单位由因子自动判定(μg/m³ 或 mg/m³), 超标按 GB 3095-2012 二级限值自动判定。",
        "6. 同一监测点 + 因子 + 周期 + 时刻在库中已存在时视为重复行,",
        "   可在导入时选择“跳过”或“合并覆盖(以新值为准并重新判定超标)”。",
        "7. 文件内不得出现完全相同的“站点+因子+时刻”行, 否则后一行判为文件内重复。",
        "8. 单次最多导入 5000 行; 当前导入的数据周期: %s。" % period_label,
        "9. 导入前请删除本示例数据(第 2~4 行)。",
    ]
    for row_index, line in enumerate(lines, start=1):
        note.cell(row=row_index, column=1, value=line)
    note.column_dimensions["A"].width = 90
    note.cell(row=1, column=1).font = Font(bold=True, size=13)

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    filename = "历史数据导入模板_%s.xlsx" % period
    return Response(
        buffer.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


def _csv_fallback():  # pragma: no cover - 仅在缺少 openpyxl 时使用
    import csv

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerow(["TEST-001", "PM2.5", "2026-09-01 09:00", 58.0, "历史导入", "张三", "示例行, 导入前删除"])
    payload = "﻿" + buffer.getvalue()
    return Response(
        payload,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": _content_disposition("历史数据导入模板.csv")},
    )


def _content_disposition(filename):
    from urllib.parse import quote

    return "attachment; filename*=UTF-8''%s" % quote(filename)
