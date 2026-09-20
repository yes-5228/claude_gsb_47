"""历史数据批量导入表格解析 (.xlsx / .csv).

仅负责把上传文件读成 "表头 + 字符串二维表", 业务校验统一在
``services.import_service`` 完成, 便于解析与规则解耦、单独测试。
"""
import csv
import io

from ..errors import ValidationError

XLSX_EXTENSIONS = (".xlsx",)
CSV_EXTENSIONS = (".csv", ".txt")
SUPPORTED_EXTENSIONS = XLSX_EXTENSIONS + CSV_EXTENSIONS

MAX_IMPORT_FILE_BYTES = 10 * 1024 * 1024  # 10 MB, 与 MAX_BATCH_SIZE 行数双重约束


class ImportSheet:
    """解析后的表格: headers 为表头字符串列表, rows 为 (行号, 单元格列表)."""

    def __init__(self, filename, headers, rows):
        self.filename = filename
        self.headers = headers
        self.rows = rows

    def __len__(self):
        return len(self.rows)


def parse_upload(file_storage, max_rows):
    """读取 werkzeug FileStorage 并返回 ImportSheet.

    表头之外的数据行不得超过 ``max_rows``; 完全空表头的文件直接拒绝。
    """
    filename = (getattr(file_storage, "filename", None) or "").strip()
    if not filename:
        raise ValidationError("上传文件缺少文件名", fields={"file": "no_filename"})
    lowered = filename.lower()
    if lowered.endswith(XLSX_EXTENSIONS):
        headers, rows = _parse_xlsx(file_storage)
    elif lowered.endswith(CSV_EXTENSIONS):
        headers, rows = _parse_csv(file_storage)
    else:
        raise ValidationError(
            "仅支持 .xlsx 或 .csv 格式的表格, 当前文件: %s" % filename,
            fields={"file": "unsupported_format"},
        )

    if not headers or not any(str(h).strip() for h in headers):
        raise ValidationError("表格缺少表头, 请下载模板按列填写", fields={"file": "empty_header"})
    if len(rows) > max_rows:
        raise ValidationError(
            "单次最多导入 %d 行数据, 当前 %d 行, 请拆分后上传" % (max_rows, len(rows)),
            fields={"file": "too_many_rows"},
        )
    return ImportSheet(filename, headers, rows)


def _parse_xlsx(file_storage):
    try:
        from openpyxl import load_workbook
    except ImportError:  # pragma: no cover - 依赖已在 requirements 中声明
        raise ValidationError("服务器缺少 openpyxl 依赖, 无法解析 Excel 文件")

    file_storage.stream.seek(0)
    try:
        workbook = load_workbook(filename=file_storage.stream, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl 对坏文件抛出多种异常, 统一提示
        raise ValidationError("Excel 文件无法解析, 请确认是有效的 .xlsx 文件: %s" % exc,
                              fields={"file": "invalid_xlsx"})
    try:
        worksheet = workbook.active
        matrix = [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()

    header_index = _first_nonempty_index(matrix)
    if header_index is None:
        return [], []
    headers = [_cell_text(cell) for cell in matrix[header_index]]
    data_rows = []
    for offset, raw in enumerate(matrix[header_index + 1 :], start=header_index + 2):
        cells = [_cell_text(cell) for cell in raw]
        if any(cell != "" for cell in cells):  # 跳过完全空白行, 行号沿用 Excel 行号
            data_rows.append((offset, _pad_or_trim(cells, len(headers))))
    return headers, data_rows


def _parse_csv(file_storage):
    file_storage.stream.seek(0)
    raw = file_storage.read()
    if isinstance(raw, bytes):
        for encoding in ("utf-8-sig", "gbk", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValidationError("CSV 文件编码无法识别, 请另存为 UTF-8 编码后上传",
                                  fields={"file": "bad_encoding"})
    else:  # pragma: no cover - 测试客户端通常给出 bytes
        text = raw

    reader = csv.reader(io.StringIO(text))
    matrix = [row for row in reader]
    header_index = _first_nonempty_index(matrix)
    if header_index is None:
        return [], []
    headers = [cell.strip() for cell in matrix[header_index]]
    data_rows = []
    for offset, raw_row in enumerate(matrix[header_index + 1 :], start=header_index + 2):
        cells = [cell.strip() for cell in raw_row]
        if any(cell for cell in cells):
            data_rows.append((offset, _pad_or_trim(cells, len(headers))))
    return headers, data_rows


def _first_nonempty_index(matrix):
    for index, row in enumerate(matrix):
        if row is not None and any(_cell_text(cell) for cell in row):
            return index
    return None


def _pad_or_trim(cells, width):
    if len(cells) < width:
        cells = cells + [""] * (width - len(cells))
    return cells[:width]


def _cell_text(value):
    """统一转成去空格字符串; Excel 读出的 datetime 保留其 isoformat 供时间列解析."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
