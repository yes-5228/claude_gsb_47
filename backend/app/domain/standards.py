"""污染物监测因子与限值定义 (GB 3095-2012 环境空气质量标准, 二级浓度限值)."""

# period 取值: hourly = 1 小时平均, daily = 24 小时平均
POLLUTANTS = {
    "PM25": {
        "code": "PM25",
        "label": "PM2.5",
        "name": "细颗粒物",
        "unit": "μg/m³",
        "precision": 1,
        "limits": {"daily": 75.0, "hourly": None},
    },
    "PM10": {
        "code": "PM10",
        "label": "PM10",
        "name": "可吸入颗粒物",
        "unit": "μg/m³",
        "precision": 1,
        "limits": {"daily": 150.0, "hourly": None},
    },
    "SO2": {
        "code": "SO2",
        "label": "SO₂",
        "name": "二氧化硫",
        "unit": "μg/m³",
        "precision": 1,
        "limits": {"daily": 150.0, "hourly": 500.0},
    },
    "NO2": {
        "code": "NO2",
        "label": "NO₂",
        "name": "二氧化氮",
        "unit": "μg/m³",
        "precision": 1,
        "limits": {"daily": 80.0, "hourly": 200.0},
    },
    "CO": {
        "code": "CO",
        "label": "CO",
        "name": "一氧化碳",
        "unit": "mg/m³",
        "precision": 2,
        "limits": {"daily": 4.0, "hourly": 10.0},
    },
    "O3": {
        "code": "O3",
        "label": "O₃",
        "name": "臭氧",
        "unit": "μg/m³",
        "precision": 1,
        "limits": {"daily": 160.0, "hourly": 200.0},
    },
}

POLLUTANT_CODES = tuple(POLLUTANTS.keys())

# 历史导入表格中可能出现的因子写法 (编码/中文名/带角标的化学式)
POLLUTANT_ALIASES = {
    "PM25": "PM25",
    "PM2.5": "PM25",
    "细颗粒物": "PM25",
    "PM10": "PM10",
    "可吸入颗粒物": "PM10",
    "SO2": "SO2",
    "SO₂": "SO2",
    "二氧化硫": "SO2",
    "NO2": "NO2",
    "NO₂": "NO2",
    "二氧化氮": "NO2",
    "CO": "CO",
    "一氧化碳": "CO",
    "O3": "O3",
    "O₃": "O3",
    "臭氧": "O3",
}


def get_pollutant(code):
    """Return the pollutant definition or None when unknown."""
    return POLLUTANTS.get(str(code or "").upper())


def resolve_pollutant(text):
    """Map a spreadsheet cell (code / Chinese name / subscript formula) to a canonical code."""
    key = str(text or "").strip().upper()
    if not key:
        return None
    canonical = POLLUTANT_ALIASES.get(key)
    return canonical if canonical in POLLUTANTS else None


def get_limit(code, period):
    """Return the concentration limit for a pollutant/period pair (None if undefined)."""
    pollutant = get_pollutant(code)
    if not pollutant:
        return None
    return pollutant["limits"].get(period)


def pollutant_options():
    """Serialisable list used by the frontend dropdowns."""
    return [dict(item) for item in POLLUTANTS.values()]
