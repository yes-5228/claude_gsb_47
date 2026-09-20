"""历史数据导入表格解析 (支持 .xlsx / .csv).

表头兼容中英文与常见别名, 解析结果为统一的字典行, 由导入服务做逐行校验。
"""
import csv
import io
from datetime import date, datetime

from ..errors import ValidationError

# 逻辑字段 -> 可接受的表头写法
HEADER_ALIASES = {
    "station": ("站点", "监测点", "站点编码", "监测点编码", "站点代码", "监测点代码",
                "点号", "点位", "点位编码", "station", "station_code", "code"),
    "station_name": ("站点名称", "监测点名称", "station_name", "name"),
    "pollutant": ("因子", "监测因子", "污染物", "污染因子", "因子编码", "指标",
                  "pollutant", "factor", "item"),
    "measured_at": ("监测时间", "时间", "数据时间", "采样时间", "观测时间", "时刻",
                    "measured_at", "time", "datetime", "date", "monitor_time"),
    "value": ("数值", "监测值", "监测数值", "浓度", "浓度值", "值",
              "value", "val", "result"),
    "period": ("周期", "数据周期", "统计周期", "均值类型", "period"),
    "data_source": ("数据来源", "来源", "source", "data_source"),
    "recorder": ("录入人", "记录人", "填报人", "上报人", "recorder", "operator"),
    "remark": ("备注", "说明", "remark", "note", "comment"),
}


def read_spreadsheet(file_storage, max_rows):
    """Parse an uploaded werkzeug FileStorage into ``(headers, rows)``.

    ``rows`` is a list of ``{"row_number": int, "data": {field: raw_cell}}``;
    blank rows are dropped. Raises :class:`ValidationError` on bad files.
    """
    filename = (file_storage.filename or "").strip()
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in ("xlsx", "csv"):
        if suffix == "xls":
            raise ValidationError("旧版 .xls 格式不受支持, 请另存为 .xlsx 或 .csv 后重新上传")
        raise ValidationError("仅支持 .xlsx (Excel) 或 .csv 格式的表格文件")

    try:
        raw = file_storage.read()
    except Exception as exc:  # pragma: no cover - defensive read guard
        raise ValidationError("文件读取失败: %s" % exc)
    if not raw:
        raise ValidationError("上传文件为空")

    if suffix == "csv":
        headers, records = _read_csv(raw)
    else:
        headers, records = _read_xlsx(raw)

    if not headers:
        raise ValidationError("表格缺少表头, 请先下载导入模板按要求填写")

    mapping = _map_headers(headers)
    required = ("station", "pollutant", "measured_at", "value")
    missing = [_field_label(field) for field in required if field not in mapping]
    if missing:
        raise ValidationError(
            "表格缺少必需列: %s, 请下载导入模板按要求填写" % "、".join(missing),
            fields={field: "missing_column" for field in missing},
        )

    rows = []
    for index, record in enumerate(records, start=2):  # 表头占第 1 行, 数据从第 2 行起
        data = {}
        for field, column in mapping.items():
            value = _normalize_cell(record[column]) if column < len(record) else ""
            if value != "":
                data[field] = value
        if data:
            rows.append({"row_number": index, "data": data})

    if not rows:
        raise ValidationError("表格中没有可导入的数据行")
    if len(rows) > max_rows:
        raise ValidationError("单次最多导入 %d 行, 当前 %d 行, 请拆分后上传" % (max_rows, len(rows)))
    return headers, rows


def _field_label(field):
    return {
        "station": "站点编码",
        "pollutant": "监测因子",
        "measured_at": "监测时间",
        "value": "监测值",
    }.get(field, field)


def _normalize_cell(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _map_headers(headers):
    lookup = []
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            lookup.append((alias.lower().replace(" ", ""), field))
    mapping = {}
    for index, header in enumerate(headers):
        normalized = str(header or "").strip().lower().replace(" ", "")
        if not normalized:
            continue
        for alias, field in lookup:
            if normalized == alias and field not in mapping:
                mapping[field] = index
                break
    return mapping


def _read_xlsx(raw):
    try:
        from openpyxl import load_workbook
    except ImportError:  # pragma: no cover - dependency is pinned
        raise ValidationError("服务器缺少 Excel 解析依赖 (openpyxl)")
    try:
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise ValidationError("Excel 文件解析失败, 请确认文件未损坏: %s" % exc)
    try:
        sheet = workbook.active
        values = [
            [_clean_text(cell) for cell in row]
            for row in sheet.iter_rows(values_only=True)
        ]
    finally:
        workbook.close()

    header_index = _first_nonempty_index(values)
    if header_index is None:
        return [], []
    headers = values[header_index]
    records = [
        row for row in values[header_index + 1:]
        if any(cell.strip() for cell in row)
    ]
    return headers, records


def _read_csv(raw):
    text = None
    for encoding in ("utf-8-sig", "gbk", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValidationError("CSV 文件编码无法识别, 请使用 UTF-8 编码保存")

    reader = csv.reader(io.StringIO(text))
    values = [[_clean_text(cell) for cell in row] for row in reader]
    header_index = _first_nonempty_index(values)
    if header_index is None:
        return [], []
    headers = values[header_index]
    records = [
        row for row in values[header_index + 1:]
        if any(cell.strip() for cell in row)
    ]
    return headers, records


def _first_nonempty_index(values):
    for index, row in enumerate(values):
        if any(str(cell or "").strip() for cell in row):
            return index
    return None


def _clean_text(value):
    if value is None:
        return ""
    return str(value).strip()
