"""历史数据批量导入业务逻辑.

两阶段流程:

1. :func:`preview_import` 解析上传表格, 逐行给出 "因子 / 监测时间 / 数值 /
   重复行" 校验结论, 不写库;
2. :func:`commit_import` 依据预览回传的行数据重新校验后入库, 重复数据按
   ``skip``(跳过) 或 ``merge``(合并覆盖) 策略处理, 返回逐行成功/失败明细。

提交阶段不依赖任何服务端会话状态, 会重新解析与查重, 避免预览后数据被他人
改动或请求被篡改导致脏数据。
"""
from datetime import datetime

from sqlalchemy import func

from ..domain import exceedance_rules
from ..domain.constants import DATA_SOURCE_LABELS, PERIOD_LABELS
from ..domain.standards import POLLUTANTS, get_pollutant
from ..errors import ValidationError
from ..extensions import db
from ..models import Measurement, Station
from . import measurement_service

# ---- 策略与取值边界 ----------------------------------------------------
STRATEGY_SKIP = "skip"
STRATEGY_MERGE = "merge"
IMPORT_STRATEGIES = (STRATEGY_SKIP, STRATEGY_MERGE)

VALUE_MIN = 0.0
VALUE_MAX = 10000.0

# ---- 表头别名 ----------------------------------------------------------
HEADER_ALIASES = {
    "station_code": ("监测点编码", "站点编码", "监测点", "站点", "station_code", "code"),
    "pollutant": ("监测因子", "因子", "污染物", "污染因子", "pollutant", "factor"),
    "measured_at": ("监测时间", "时间", "数据时间", "采样时间", "measured_at", "time"),
    "value": ("数值", "监测值", "监测数值", "浓度", "浓度值", "value"),
    "data_source": ("数据来源", "来源", "data_source", "source"),
    "recorder": ("录入人", "记录人", "填表人", "recorder"),
    "remark": ("备注", "说明", "remark", "note"),
}
REQUIRED_FIELDS = ("station_code", "pollutant", "measured_at", "value")
OPTIONAL_FIELDS = ("data_source", "recorder", "remark")

_DATETIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y年%m月%d日 %H:%M",
    "%Y年%m月%d日 %H时%M分",
    "%Y年%m月%d日 %H时",
    "%Y年%m月%d日",
)


# ---- 表头与取值归一化 --------------------------------------------------
def build_column_index(headers):
    """把中文/英文表头映射为标准字段, 缺列时抛出 422 并指明缺失列."""
    normalized = {_normalize_header(h): index for index, h in enumerate(headers)}
    index = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            pos = normalized.get(_normalize_header(alias))
            if pos is not None:
                index[field] = pos
                break
    missing = [HEADER_ALIASES[field][0] for field in REQUIRED_FIELDS if field not in index]
    if missing:
        raise ValidationError(
            "表格缺少必需列: %s (请下载标准模板填写)" % "、".join(missing),
            fields={"missing_columns": missing},
        )
    return index


def _normalize_header(text):
    return "".join(str(text or "").strip().lower().split())


def _pollutant_aliases():
    """因子代码/中文名/化学式的可接受写法, 如 PM2.5、SO₂、臭氧."""
    aliases = {}
    for code, meta in POLLUTANTS.items():
        candidates = {code, code.lower(), meta["label"], meta["name"]}
        if code == "PM25":
            candidates.update({"pm2.5", "细粒子"})
        if code == "PM10":
            candidates.add("飘尘")
        for candidate in candidates:
            # 不同因子的别名理论上不重合, setdefault 保证先注册者不被意外覆盖
            aliases.setdefault(_normalize_header(candidate), code)
    return aliases


_POLLUTANT_ALIASES = _pollutant_aliases()

_DATASOURCE_ALIASES = {}
for _code, _label in DATA_SOURCE_LABELS.items():
    _DATASOURCE_ALIASES[_code] = _code
    _DATASOURCE_ALIASES[_normalize_header(_label)] = _code


def resolve_pollutant(raw):
    if raw is None or str(raw).strip() == "":
        return None
    return _POLLUTANT_ALIASES.get(_normalize_header(raw))


def _resolve_data_source(raw, default):
    text = str(raw or "").strip()
    if text == "":
        return default, None
    code = _DATASOURCE_ALIASES.get(_normalize_header(text))
    if code is None:
        return default, "数据来源不合法, 可选: %s" % "、".join(DATA_SOURCE_LABELS.values())
    return code, None


def parse_import_datetime(raw):
    """支持 'YYYY-MM-DD HH:MM'、'YYYY/MM/DD HH:MM'、中文日期及纯日期."""
    if isinstance(raw, datetime):
        return raw
    text = str(raw or "").strip().replace("Z", "")
    if not text:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# ---- 行抽取 ------------------------------------------------------------
def rows_from_sheet(sheet, column_index):
    rows = []
    for row_number, cells in sheet.rows:
        raw = {field: cells[pos] if pos < len(cells) else "" for field, pos in column_index.items()}
        raw["row_number"] = row_number
        rows.append(raw)
    return rows


def rows_from_payload(payload_rows):
    """提交接口回传的 JSON 行 -> 与表格解析后一致的原始行结构.

    优先使用预览阶段回传的 ``raw`` 原始单元格, 缺省时退回顶层字段,
    保证服务端基于原始文本重新校验。
    """
    rows = []
    for pos, item in enumerate(payload_rows, start=2):
        raw = dict(item.get("raw") or {})
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            raw.setdefault(field, item.get(field, ""))
        raw["row_number"] = item.get("row_number") or pos
        rows.append(raw)
    return rows


# ---- 预校验 (不写库) ---------------------------------------------------
def preview_import(raw_rows, period, default_source="import", default_recorder=None):
    stations = _load_station_map(raw_rows)
    existing = _load_existing_map(raw_rows, stations, period)
    seen = {}
    results = [
        _validate_row(raw, period, stations, existing, seen, default_source, default_recorder)
        for raw in raw_rows
    ]
    return _build_preview_payload(results, period, default_source, default_recorder)


def _validate_row(raw, period, stations, existing, seen, default_source, default_recorder):
    row_number = raw["row_number"]
    station_code = str(raw.get("station_code") or "").strip()
    pollutant_text = str(raw.get("pollutant") or "").strip()
    time_text = str(raw.get("measured_at") or "").strip()
    value_text = str(raw.get("value") or "").strip()

    result = {
        "row_number": row_number,
        "station_code": station_code,
        "station_id": None,
        "station_name": None,
        "pollutant": None,
        "pollutant_label": pollutant_text or None,
        "period": period,
        "measured_at": None,
        "value": None,
        "unit": None,
        "data_source": default_source,
        "recorder": str(raw.get("recorder") or "").strip() or default_recorder,
        "remark": str(raw.get("remark") or "").strip() or None,
        "raw": {
            # 确认入库时原样回传, 服务端重新校验, 避免归一化值与原值不一致
            "station_code": station_code,
            "pollutant": pollutant_text,
            "measured_at": time_text,
            "value": value_text,
            "data_source": str(raw.get("data_source") or "").strip(),
            "recorder": str(raw.get("recorder") or "").strip(),
            "remark": str(raw.get("remark") or "").strip(),
        },
        "status": "valid",
        "field_errors": {},
        "message": None,
        "evaluation": None,
        "existing": None,
    }
    errors = result["field_errors"]

    station = stations.get(station_code.lower()) if station_code else None
    if not station_code:
        errors["station_code"] = "监测点编码不能为空"
    elif station is None:
        errors["station_code"] = "未知监测点编码: %s" % station_code
    else:
        result["station_id"] = station.id
        result["station_name"] = station.name

    pollutant = resolve_pollutant(pollutant_text)
    meta = get_pollutant(pollutant) if pollutant else None
    if not pollutant_text:
        errors["pollutant"] = "监测因子不能为空"
    elif meta is None:
        errors["pollutant"] = "未知监测因子: %s" % pollutant_text
    else:
        result["pollutant"] = pollutant
        result["pollutant_label"] = meta["label"]
        result["unit"] = meta["unit"]

    measured_at = parse_import_datetime(time_text)
    if not time_text:
        errors["measured_at"] = "监测时间不能为空"
    elif measured_at is None:
        errors["measured_at"] = "时间格式不合法, 应为 YYYY-MM-DD HH:MM"
    else:
        result["measured_at"] = measured_at.isoformat(timespec="seconds")

    value = _parse_value(value_text)
    if value_text == "":
        errors["value"] = "监测数值不能为空"
    elif value is None:
        errors["value"] = "监测值必须是数字"
    else:
        result["value"] = value

    source, source_error = _resolve_data_source(raw.get("data_source"), default_source)
    result["data_source"] = source
    if source_error:
        errors["data_source"] = source_error

    # 基础字段未通过时不再做限值判定 / 查重
    if errors:
        result["status"] = "invalid"
        result["message"] = "；".join(errors.values())
        return result

    evaluation = exceedance_rules.evaluate(pollutant, period, value)
    result["evaluation"] = evaluation

    key = (station.id, pollutant, period, measured_at)
    if key in seen:
        first_row = seen[key]
        errors["_row"] = "与文件第 %d 行数据重复" % first_row
        result["status"] = "invalid"
        result["message"] = errors["_row"]
        return result
    seen[key] = row_number

    record = existing.get(key)
    if record is not None:
        result["status"] = "duplicate"
        result["existing"] = {
            "id": record.id,
            "value": record.value,
            "measured_at": record.measured_at.isoformat(timespec="seconds"),
        }
        result["message"] = "库中已存在该时刻 %s 数据(原值 %s)" % (
            meta["label"], _format_existing_value(record.value),
        )
    return result


def _parse_value(text):
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    if value < VALUE_MIN or value > VALUE_MAX:
        return None
    return value


def _format_existing_value(value):
    if value is None:
        return "-"
    return ("%s" % value).rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _load_station_map(raw_rows):
    codes = {str(raw.get("station_code") or "").strip().lower()
             for raw in raw_rows if str(raw.get("station_code") or "").strip()}
    if not codes:
        return {}
    stations = Station.query.filter(func.lower(Station.code).in_(codes)).all()
    return {station.code.lower(): station for station in stations}


def _load_existing_map(raw_rows, stations, period):
    """按 (站点, 时刻) 批量取库中已有记录, 再按完整唯一键建索引."""
    station_ids = {station.id for station in stations.values()}
    times = set()
    for raw in raw_rows:
        parsed = parse_import_datetime(raw.get("measured_at"))
        if parsed is not None:
            times.add(parsed)
    if not station_ids or not times:
        return {}
    records = (
        Measurement.query.filter(
            Measurement.period == period,
            Measurement.station_id.in_(station_ids),
            Measurement.measured_at.in_(times),
        ).all()
    )
    return {
        (record.station_id, record.pollutant, record.period, record.measured_at): record
        for record in records
    }


def _build_preview_payload(results, period, default_source, default_recorder):
    valid = [row for row in results if row["status"] == "valid"]
    duplicates = [row for row in results if row["status"] == "duplicate"]
    invalid = [row for row in results if row["status"] == "invalid"]
    # 重复行也会给出本次新值的超标结论, 因此统计纳入 valid + duplicate
    evaluable = valid + duplicates
    exceeded_rows = [row for row in evaluable if row["evaluation"] and row["evaluation"]["exceeded"]]
    return {
        "period": period,
        "period_label": PERIOD_LABELS.get(period, period),
        "defaults": {"data_source": default_source, "recorder": default_recorder},
        "rows": results,
        "summary": {
            "total": len(results),
            "valid_count": len(valid),
            "duplicate_count": len(duplicates),
            "invalid_count": len(invalid),
            "exceeded_count": len(exceeded_rows),
        },
    }


# ---- 正式入库 ----------------------------------------------------------
def commit_import(raw_rows, period, strategy, default_source="import", default_recorder=None):
    if strategy not in IMPORT_STRATEGIES:
        raise ValidationError(
            "重复处理策略不合法, 可选: %s、%s" % (STRATEGY_SKIP, STRATEGY_MERGE),
            fields={"strategy": "invalid"},
        )
    if not raw_rows:
        raise ValidationError("没有需要导入的数据行", fields={"rows": "empty"})

    stations = _load_station_map(raw_rows)
    existing = _load_existing_map(raw_rows, stations, period)
    seen = {}
    details = []
    exceeded_count = 0

    for raw in raw_rows:
        checked = _validate_row(raw, period, stations, existing, seen, default_source, default_recorder)
        details.append(_persist_row(checked, existing, strategy))
        if details[-1]["status"] in ("created", "updated") and details[-1]["is_exceeded"]:
            exceeded_count += 1

    created = [row for row in details if row["status"] == "created"]
    updated = [row for row in details if row["status"] == "updated"]
    skipped = [row for row in details if row["status"] == "skipped"]
    failed = [row for row in details if row["status"] == "failed"]

    # 有效行全部落盘后统一提交; 失败行已在保存点回滚, 不影响其它行
    if created or updated:
        db.session.commit()
    else:
        db.session.rollback()

    return {
        "period": period,
        "strategy": strategy,
        "details": details,
        "exceedances_created": exceeded_count,
        "summary": {
            "total": len(details),
            "created_count": len(created),
            "updated_count": len(updated),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "exceeded_count": exceeded_count,
        },
    }


def _persist_row(checked, existing, strategy):
    """单行入库结果; 任何异常只回滚该行所在的保存点."""
    detail = {
        "row_number": checked["row_number"],
        "station_code": checked["station_code"],
        "station_name": checked["station_name"],
        "pollutant": checked["pollutant"],
        "pollutant_label": checked["pollutant_label"],
        "measured_at": checked["measured_at"],
        "value": checked["value"],
        "unit": checked["unit"],
        "status": "failed",
        "measurement_id": None,
        "is_exceeded": False,
        "exceedance_level": None,
        "message": checked["message"],
    }

    if checked["status"] == "invalid":
        return detail  # 默认 status=failed, message 已带校验结论

    station_id = checked["station_id"]
    measured_at = datetime.fromisoformat(checked["measured_at"])
    key = (station_id, checked["pollutant"], checked["period"], measured_at)
    record = existing.get(key)

    if record is not None and strategy == STRATEGY_SKIP:
        detail["status"] = "skipped"
        detail["measurement_id"] = record.id
        detail["is_exceeded"] = bool(record.is_exceeded)
        detail["exceedance_level"] = record.exceedance.level if record.exceedance else None
        detail["message"] = "重复数据已跳过(库中记录 id=%s)" % record.id
        return detail

    evaluation = checked["evaluation"]
    try:
        is_new = record is None
        with db.session.begin_nested():  # 保存点: 单行失败仅回滚该行
            if is_new:
                record = Measurement(
                    station_id=station_id,
                    pollutant=checked["pollutant"],
                    period=checked["period"],
                    measured_at=measured_at,
                )
                db.session.add(record)

            record.value = checked["value"]
            record.unit = checked["unit"]
            record.limit_value = evaluation["limit"]
            record.exceed_ratio = evaluation["ratio"]
            record.is_exceeded = evaluation["exceeded"]
            record.data_source = checked["data_source"]
            record.recorder = checked["recorder"]
            record.remark = checked["remark"]
            measurement_service._sync_exceedance(record, get_pollutant(checked["pollutant"]), evaluation)
            db.session.flush()

        existing[key] = record  # 后续同键行以最新记录为准
        detail["status"] = "created" if is_new else "updated"
        detail["measurement_id"] = record.id
        detail["is_exceeded"] = bool(evaluation["exceeded"])
        detail["exceedance_level"] = evaluation["level"]
        detail["message"] = "新增成功" if is_new else "重复数据已合并覆盖(记录 id=%s)" % record.id
    except Exception as exc:  # 单行失败不拖垮整批
        detail["message"] = "入库失败: %s" % _safe_error(exc)
    return detail


def _safe_error(exc):
    from sqlalchemy.exc import IntegrityError

    if isinstance(exc, IntegrityError):
        return "数据冲突, 唯一键可能已被其它事务占用"
    return str(exc) or exc.__class__.__name__
