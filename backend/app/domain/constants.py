"""Enumerations shared by the API layer and the frontend."""

PERIOD_LABELS = {"hourly": "小时均值", "daily": "日均值"}

DATA_SOURCE_LABELS = {"manual": "手工录入", "device": "设备上传", "import": "历史导入"}

STATION_TYPE_LABELS = {
    "ambient": "环境空气",
    "traffic": "道路交通",
    "background": "区域背景",
    "industrial": "工业园区",
    "rural": "农村站点",
}

STATION_STATUS_LABELS = {"active": "运行中", "maintenance": "维护中", "offline": "停用"}

EXCEEDANCE_LEVEL_LABELS = {"light": "轻度超标", "moderate": "中度超标", "severe": "重度超标"}

EXCEEDANCE_STATUS_LABELS = {"pending": "待标注", "confirmed": "已确认", "ignored": "已忽略"}


def as_options(label_map):
    return [{"value": key, "label": label} for key, label in label_map.items()]


def options_payload():
    return {
        "station_type": as_options(STATION_TYPE_LABELS),
        "station_status": as_options(STATION_STATUS_LABELS),
        "period": as_options(PERIOD_LABELS),
        "data_source": as_options(DATA_SOURCE_LABELS),
        "exceedance_level": as_options(EXCEEDANCE_LEVEL_LABELS),
        "exceedance_status": as_options(EXCEEDANCE_STATUS_LABELS),
    }


def label_of(label_map, key):
    return label_map.get(key, key)


# 导入表格表头中可能出现的枚举写法
_PERIOD_ALIASES = {
    "hourly": "hourly",
    "hour": "hourly",
    "1h": "hourly",
    "小时": "hourly",
    "小时均值": "hourly",
    "小时平均": "hourly",
    "1小时": "hourly",
    "1小时均值": "hourly",
    "1小时平均": "hourly",
    "daily": "daily",
    "day": "daily",
    "24h": "daily",
    "日": "daily",
    "日均": "daily",
    "日均值": "daily",
    "日平均": "daily",
    "24小时": "daily",
    "24小时均值": "daily",
    "24小时平均": "daily",
}

_DATA_SOURCE_ALIASES = {
    "manual": "manual",
    "手工": "manual",
    "手工录入": "manual",
    "人工": "manual",
    "人工录入": "manual",
    "device": "device",
    "设备": "device",
    "设备上传": "device",
    "在线": "device",
    "在线设备": "device",
    "import": "import",
    "history": "import",
    "历史": "import",
    "历史导入": "import",
    "历史数据": "import",
    "批量导入": "import",
}


def resolve_period(text, default=None):
    """Normalise a spreadsheet period cell; returns ``default`` when empty."""
    if text is None or str(text).strip() == "":
        return default
    return _PERIOD_ALIASES.get(str(text).strip().lower())


def resolve_data_source(text, default="import"):
    """Normalise a spreadsheet data-source cell; returns ``default`` when empty/unknown."""
    if text is None or str(text).strip() == "":
        return default
    return _DATA_SOURCE_ALIASES.get(str(text).strip().lower(), default)
