"""历史数据批量导入接口测试."""
import io

import pytest

from app.models import Exceedance, Measurement


CSV_HEADER = "监测点编码,监测因子,监测时间,数值,数据来源,录入人,备注\n"


def csv_file(rows, name="history.csv"):
    content = CSV_HEADER + "".join(rows)
    return io.BytesIO(content.encode("utf-8-sig")), name


def xlsx_file(rows, name="history.xlsx"):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["监测点编码", "监测因子", "监测时间", "数值", "数据来源", "录入人", "备注"])
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer, name


def upload(client, path, fileobj, **form):
    return client.post(
        path,
        data={"file": (fileobj[0], fileobj[1]), **form},
        content_type="multipart/form-data",
    )


@pytest.fixture
def seed_measurement(client, station):
    client.post(
        "/api/measurements/entries",
        json={
            "station_id": station.id,
            "measured_at": "2026-09-01 10:00",
            "period": "hourly",
            "entries": [{"pollutant": "SO2", "value": 300.0}],
        },
    )


# ---- 预览 ---------------------------------------------------------------
def test_preview_reports_valid_exceeded_and_duplicate_rows(client, station, seed_measurement):
    rows = [
        "TEST-001,PM2.5,2026-09-01 09:00,58,历史导入,张三,\n",
        "TEST-001,SO₂,2026/09/01 10:00,640,历史导入,张三,\n",   # 库中已有 -> 重复且超标
        "TEST-001,CO,2026-09-01 09:00,1.2,,,\n",
    ]
    response = upload(client, "/api/measurements/import-preview", csv_file(rows), period="hourly")
    assert response.status_code == 200
    body = response.get_json()
    assert body["filename"] == "history.csv"
    assert body["summary"] == {
        "total": 3, "valid_count": 2, "duplicate_count": 1, "invalid_count": 0,
        "exceeded_count": 1,
    }
    statuses = {row["row_number"]: row["status"] for row in body["rows"]}
    assert statuses == {2: "valid", 3: "duplicate", 4: "valid"}
    duplicate = body["rows"][1]
    assert duplicate["existing"]["value"] == 300.0
    assert duplicate["evaluation"]["exceeded"] is True
    assert duplicate["evaluation"]["level"] == "light"
    assert Measurement.query.count() == 1  # 预览不写库


def test_preview_flags_field_level_errors_and_in_file_duplicate(client, station):
    rows = [
        "TEST-001,PM2.5,2026-09-01 09:00,58,,,\n",
        "NO-SUCH,PM10,2026-09-01 09:00,80,,,\n",
        "TEST-001,XXX,2026-09-01 09:00,80,,,\n",
        "TEST-001,PM2.5,not-a-time,80,,,\n",
        "TEST-001,PM2.5,2026-09-01 09:00,abc,,,\n",
        "TEST-001,PM2.5,2026-09-01 09:00,58,,,\n",   # 与第 2 行文件内重复
        "TEST-001,PM2.5,2026-09-01 09:00,-3,,,\n",    # 负数
    ]
    response = upload(client, "/api/measurements/import-preview", csv_file(rows))
    body = response.get_json()
    assert response.status_code == 200
    assert body["summary"]["valid_count"] == 1
    assert body["summary"]["invalid_count"] == 6
    by_number = {row["row_number"]: row for row in body["rows"]}
    assert "未知监测点编码" in by_number[3]["field_errors"]["station_code"]
    assert "未知监测因子" in by_number[4]["field_errors"]["pollutant"]
    assert "时间格式" in by_number[5]["field_errors"]["measured_at"]
    assert "数字" in by_number[6]["field_errors"]["value"]
    assert "文件第 2 行" in by_number[7]["message"]
    assert "数字" in by_number[8]["field_errors"]["value"]


def test_preview_supports_english_headers_and_aliases(client, station):
    content = (
        "code,factor,time,value\n"
        "test-001,pm25,2026-09-01 10:00,58\n"   # 编码大小写不敏感、因子小写代码
    )
    response = client.post(
        "/api/measurements/import-preview",
        data={"file": (io.BytesIO(content.encode()), "en.csv")},
        content_type="multipart/form-data",
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["rows"][0]["status"] == "valid"
    assert body["rows"][0]["pollutant"] == "PM25"


def test_preview_parses_xlsx(client, station, seed_measurement):
    rows = [
        ["TEST-001", "臭氧", "2026-09-01 11:00", 210.0, "设备上传", "王五", "xlsx 解析"],
        ["TEST-001", "SO2", "2026-09-01 10:00", 280.0, None, None, None],  # 库中已有
    ]
    response = upload(client, "/api/measurements/import-preview", xlsx_file(rows))
    assert response.status_code == 200
    body = response.get_json()
    assert body["summary"]["valid_count"] == 1
    assert body["summary"]["duplicate_count"] == 1
    assert body["rows"][0]["data_source"] == "device"
    assert body["rows"][0]["pollutant_label"] == "O₃"


def test_preview_rejects_bad_format_and_missing_columns(client, station):
    bad_ext = client.post(
        "/api/measurements/import-preview",
        data={"file": (io.BytesIO(b"x"), "data.xls")},
        content_type="multipart/form-data",
    )
    assert bad_ext.status_code == 422
    assert bad_ext.get_json()["error"]["fields"]["file"] == "unsupported_format"

    missing = client.post(
        "/api/measurements/import-preview",
        data={"file": (io.BytesIO("监测点编码,监测时间,数值\nX,2026-09-01,1".encode()), "h.csv")},
        content_type="multipart/form-data",
    )
    assert missing.status_code == 422
    assert "监测因子" in missing.get_json()["error"]["fields"]["missing_columns"]


# ---- 入库: 跳过策略 -----------------------------------------------------
def test_commit_skip_strategy_creates_valid_and_skips_duplicates(client, station, seed_measurement):
    rows = [
        {"station_code": "TEST-001", "pollutant": "PM2.5", "measured_at": "2026-09-01 09:00",
         "value": 58.0, "data_source": "import"},
        {"station_code": "TEST-001", "pollutant": "SO2", "measured_at": "2026-09-01 10:00",
         "value": 640.0, "data_source": "import"},
        {"station_code": "NO-SUCH", "pollutant": "CO", "measured_at": "2026-09-01 09:00",
         "value": 1.2},
    ]
    response = client.post("/api/measurements/import-commit", json={
        "period": "hourly", "strategy": "skip", "rows": rows,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["summary"] == {
        "total": 3, "created_count": 1, "updated_count": 0,
        "skipped_count": 1, "failed_count": 1, "exceeded_count": 0,
    }
    statuses = {row["row_number"]: row["status"] for row in body["details"]}
    assert statuses == {2: "created", 3: "skipped", 4: "failed"}
    skipped = body["details"][1]
    assert "重复数据已跳过" in skipped["message"]
    assert Measurement.query.count() == 2  # 原 SO2(300) + 新增 PM25
    assert Measurement.query.filter_by(pollutant="SO2").one().value == 300.0
    assert Exceedance.query.count() == 0   # 跳过的超标行不生成新记录


# ---- 入库: 合并策略 -----------------------------------------------------
def test_commit_merge_strategy_updates_and_syncs_exceedance(client, station, seed_measurement):
    # 原值 300 (未超标); 合并为 120 (仍不超标) 后再合并为 640 (超标)
    rows = [
        {"station_code": "TEST-001", "pollutant": "SO2", "measured_at": "2026-09-01 10:00",
         "value": 640.0, "data_source": "import", "recorder": "导入员"},
        {"station_code": "TEST-001", "pollutant": "PM25", "measured_at": "2026-09-01 10:00",
         "value": 90.0, "data_source": "import"},
    ]
    response = client.post("/api/measurements/import-commit", json={
        "period": "hourly", "strategy": "merge", "rows": rows, "recorder": "默认录入人",
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["summary"]["created_count"] == 1
    assert body["summary"]["updated_count"] == 1
    assert body["summary"]["skipped_count"] == 0
    assert body["summary"]["failed_count"] == 0
    assert body["summary"]["exceeded_count"] == 1

    so2 = Measurement.query.filter_by(pollutant="SO2").one()
    assert so2.value == 640.0
    assert so2.is_exceeded is True
    assert so2.exceed_ratio == 1.28
    assert so2.recorder == "导入员"
    assert so2.data_source == "import"
    assert Exceedance.query.count() == 1
    assert Exceedance.query.one().status == "pending"

    # 再次合并: 降回限值以下, 超标记录应撤销
    response2 = client.post("/api/measurements/import-commit", json={
        "period": "hourly", "strategy": "merge",
        "rows": [{"station_code": "TEST-001", "pollutant": "SO2",
                  "measured_at": "2026-09-01 10:00", "value": 120.0}],
    })
    assert response2.status_code == 200
    assert Measurement.query.filter_by(pollutant="SO2").one().value == 120.0
    assert Exceedance.query.count() == 0


def test_commit_in_file_duplicate_is_failed_even_in_merge_mode(client, station):
    rows = [
        {"station_code": "TEST-001", "pollutant": "PM25", "measured_at": "2026-09-01 09:00",
         "value": 50.0},
        {"station_code": "TEST-001", "pollutant": "PM25", "measured_at": "2026-09-01 09:00",
         "value": 60.0},
    ]
    response = client.post("/api/measurements/import-commit", json={
        "period": "hourly", "strategy": "merge", "rows": rows,
    })
    body = response.get_json()
    assert body["summary"]["created_count"] == 1
    assert body["summary"]["failed_count"] == 1
    assert body["details"][1]["message"] == "与文件第 2 行数据重复"


def test_commit_daily_period_and_date_only_time(client, station):
    rows = [
        {"station_code": "TEST-001", "pollutant": "PM25", "measured_at": "2026-09-01",
         "value": 90.0},  # 日均值 90 > 75, 超标
        {"station_code": "TEST-001", "pollutant": "PM25", "measured_at": "2026-09-02",
         "value": 30.0},
    ]
    response = client.post("/api/measurements/import-commit", json={
        "period": "daily", "strategy": "skip", "rows": rows,
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["summary"]["created_count"] == 2
    assert body["summary"]["exceeded_count"] == 1
    records = Measurement.query.filter_by(period="daily").order_by(Measurement.measured_at).all()
    assert records[0].measured_at.strftime("%Y-%m-%d %H:%M") == "2026-09-01 00:00"


def test_commit_rejects_bad_strategy_and_empty_rows(client, station):
    bad = client.post("/api/measurements/import-commit",
                      json={"period": "hourly", "strategy": "overwrite",
                            "rows": [{"station_code": "X", "pollutant": "CO",
                                      "measured_at": "2026-09-01", "value": 1}]})
    assert bad.status_code == 422

    empty = client.post("/api/measurements/import-commit",
                        json={"period": "hourly", "strategy": "skip", "rows": []})
    assert empty.status_code == 422


# ---- 模板 ---------------------------------------------------------------
def test_import_template_is_xlsx_with_headers(client):
    response = client.get("/api/measurements/import-template?period=daily")
    assert response.status_code == 200
    assert "spreadsheetml" in response.mimetype
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(response.data))
    sheet = workbook["历史数据导入"]
    headers = [cell.value for cell in sheet[1]]
    assert headers == ["监测点编码", "监测因子", "监测时间", "数值", "数据来源", "录入人", "备注"]
    assert sheet.max_row >= 2
    assert "填写说明" in workbook.sheetnames


# ---- 边界 ---------------------------------------------------------------
def test_preview_accepts_gbk_encoded_csv(client, station):
    content = ("监测点编码,监测因子,监测时间,数值\n" "TEST-001,PM10,2026-09-01 09:00,72\n").encode("gbk")
    response = client.post(
        "/api/measurements/import-preview",
        data={"file": (io.BytesIO(content), "gbk.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["summary"]["valid_count"] == 1


def test_commit_revalidates_and_rejects_tampered_rows(client, station):
    """提交时不能信任预览结论: 篡改后的行必须重新校验."""
    response = client.post("/api/measurements/import-commit", json={
        "period": "hourly", "strategy": "skip",
        "rows": [{"raw": {"station_code": "HACK", "pollutant": "NOPE",
                          "measured_at": "", "value": "x"}}],
    })
    body = response.get_json()
    assert response.status_code == 200
    assert body["summary"]["failed_count"] == 1
    assert Measurement.query.count() == 0


def test_commit_without_file_field_and_empty_file(client):
    no_file = client.post("/api/measurements/import-preview", data={},
                          content_type="multipart/form-data")
    assert no_file.status_code == 422
    assert no_file.get_json()["error"]["fields"]["file"] == "required"

    empty = client.post(
        "/api/measurements/import-preview",
        data={"file": (io.BytesIO("监测点编码,监测因子,监测时间,数值\n".encode()), "empty.csv")},
        content_type="multipart/form-data",
    )
    assert empty.status_code == 422
    assert empty.get_json()["error"]["fields"]["file"] == "empty_rows"


def test_row_level_persistence_failure_does_not_block_other_rows(client, station, monkeypatch):
    from app.services import import_service

    real_validate = import_service._validate_row
    call_count = {"n": 0}

    def flushing_validate(raw, period, stations, existing, seen, default_source, default_recorder):
        checked = real_validate(raw, period, stations, existing, seen,
                                default_source, default_recorder)
        call_count["n"] += 1
        if call_count["n"] == 2 and checked["status"] == "valid":
            # 模拟第二行落库时触发一次数据库异常, 随后恢复
            original_flush = import_service.db.session.flush

            def boom(*args, **kwargs):
                monkeypatch.setattr(import_service.db.session, "flush", original_flush)
                raise RuntimeError("模拟存储故障")

            monkeypatch.setattr(import_service.db.session, "flush", boom)
        return checked

    monkeypatch.setattr(import_service, "_validate_row", flushing_validate)
    rows = [
        {"station_code": "TEST-001", "pollutant": "CO", "measured_at": "2026-09-01 09:00",
         "value": 1.1},
        {"station_code": "TEST-001", "pollutant": "NO2", "measured_at": "2026-09-01 09:00",
         "value": 40.0},
        {"station_code": "TEST-001", "pollutant": "O3", "measured_at": "2026-09-01 09:00",
         "value": 80.0},
    ]
    response = client.post("/api/measurements/import-commit", json={
        "period": "hourly", "strategy": "skip", "rows": rows,
    })
    body = response.get_json()
    assert response.status_code == 200
    statuses = {row["row_number"]: row["status"] for row in body["details"]}
    assert statuses[2] == "created"
    assert statuses[3] == "failed"
    assert "模拟存储故障" in body["details"][1]["message"]
    assert statuses[4] == "created"
    assert body["summary"]["created_count"] == 2
    assert body["summary"]["failed_count"] == 1
    assert Measurement.query.filter_by(pollutant="O3").count() == 1
