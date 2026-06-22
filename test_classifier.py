from classifier import classify
from library_validator import validate_library_root
from rfa_reader import RfaMetadata, RfaReaderError, validate_rfa_path
from rfa_reader import read_metadata_from_json
from queue_protocol import create_request, REQUEST_DIR
from addin_installer import SOURCE_DLL, get_ascii_deploy_dir, render_manifest, versioned_dll_name
from listener_status import get_listener_status
from naming_rules import analyze_source_name, generate_planned_name
from duplicate_checker import build_available_copy_name, find_duplicate_names
from ingest_service import ingest_copy_only
from library_index import fetch_recent_records, record_ingest
from xlsx_exporter import export_library_index_xlsx
from parameter_standardizer import build_parameter_preview
from parameter_values import build_safe_text_values
from settings_store import get_settings_path, load_settings, save_library_root


def test_smoke_detector_goes_to_fire_protection() -> None:
    result = classify(
        {
            "file_name": "Smoke Detector Ceiling.rfa",
            "family_name": "煙霧偵測器",
            "type_name": "天花型",
            "revit_category": "Fire Alarm Devices",
        }
    )
    assert result["status"] == "classified"
    assert result["path"].endswith("04 火警偵測\\01 煙霧偵測器")


def test_emergency_light_goes_to_fire_protection() -> None:
    result = classify(
        {
            "file_name": "Emergency Light Wall.rfa",
            "family_name": "緊急照明",
            "type_name": "壁掛型",
            "revit_category": "Lighting Fixtures",
        }
    )
    assert result["status"] == "classified"
    assert result["path"].endswith("02 消防設備\\07 緊急照明")


def test_unknown_family_needs_review() -> None:
    result = classify(
        {
            "file_name": "Unknown Device.rfa",
            "family_name": "未知設備",
            "type_name": "",
            "revit_category": "Generic Models",
        }
    )
    assert result["status"] == "needs_review"


def test_library_root_validation() -> None:
    result = validate_library_root(r"E:\Desktop\Codex\族群庫")
    assert result["valid"] is True


def test_fire_pump_beats_generic_pump() -> None:
    result = classify(
        {
            "file_name": "Fire Pump 80HP.rfa",
            "family_name": "消防泵",
            "type_name": "80HP",
            "revit_category": "Mechanical Equipment",
        }
    )
    assert result["path"].endswith("02 消防設備\\01 消防泵")


def test_exit_sign_beats_general_lighting() -> None:
    result = classify(
        {
            "file_name": "Exit Sign.rfa",
            "family_name": "出口指示燈",
            "type_name": "雙面",
            "revit_category": "Lighting Fixtures",
        }
    )
    assert result["path"].endswith("02 消防設備\\06 出口指示燈")


def test_conduit_fitting_beats_generic_plumbing_fitting_terms() -> None:
    result = classify(
        {
            "file_name": "M_電管管接頭 - 壓縮 - 鋼.rfa",
            "family_name": "M_電管管接頭 - 壓縮 - 鋼",
            "type_name": "標準",
            "revit_category": "電管配件",
        }
    )
    assert result["status"] == "classified"
    assert result["system"] == "PWR"
    assert result["path"].endswith("04 PWR 動力\\02 配線系統\\04 配件")


def test_cable_tray_fitting_routes_before_generic_cross_term() -> None:
    result = classify(
        {
            "file_name": "M_梯水平交叉.rfa",
            "family_name": "M_梯水平交叉",
            "type_name": "300mm 半徑",
            "revit_category": "電纜架配件",
        }
    )
    assert result["status"] == "classified"
    assert result["system"] == "PWR"
    assert result["path"].endswith("04 PWR 動力\\02 配線系統\\04 配件")


def test_fire_alarm_device_routes_to_fire_protection_before_door_term() -> None:
    result = classify(
        {
            "file_name": "M_火警門擋 - 磁性 - 落地式.rfa",
            "family_name": "M_火警門擋 - 磁性 - 落地式",
            "type_name": "正常",
            "revit_category": "火警裝置",
        }
    )
    assert result["status"] == "classified"
    assert result["system"] == "FP"
    assert result["path"].endswith("03 FP 消防")


def test_unknown_structured_category_does_not_fall_back_to_global_keywords() -> None:
    result = classify(
        {
            "file_name": "M_特殊門元件.rfa",
            "family_name": "M_特殊門元件",
            "type_name": "",
            "revit_category": "未收錄主類別",
        }
    )
    assert result["status"] == "needs_review"
    assert result["matches"] == []


def test_pipe_accessory_check_valve_routes_to_plumbing() -> None:
    result = classify(
        {
            "file_name": "M_逆止閥 - 10-100 mm - 螺紋.rfa",
            "family_name": "M_逆止閥 - 10-100 mm - 螺紋",
            "type_name": "閥 - 斷閥",
            "revit_category": "管附件",
        }
    )
    assert result["status"] == "classified"
    assert result["system"] == "PLB"
    assert result["path"].endswith("04 閥件\\03 止回閥")


def test_rfa_metadata_maps_to_classifier_shape() -> None:
    metadata = RfaMetadata(
        file_name="Smoke Detector Ceiling.rfa",
        family_name="煙霧偵測器",
        revit_category="Fire Alarm Devices",
        family_types=["天花型"],
        family_parameters=["Manufacturer", "Model"],
        family_parameter_details=[],
    )
    payload = metadata.to_classifier_metadata()
    assert payload["family_name"] == "煙霧偵測器"
    assert payload["type_name"] == "天花型"
    assert payload["notes"] == "Manufacturer Model"


def test_validate_rfa_path_rejects_non_rfa() -> None:
    try:
        validate_rfa_path(__file__)
    except RfaReaderError as exc:
        assert ".rfa" in str(exc)
    else:
        raise AssertionError("應拒絕非 RFA 檔案")


def test_read_metadata_from_json(tmp_path=None) -> None:
    from pathlib import Path
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "metadata.json"
        path.write_text(
            json.dumps(
                {
                    "file_name": "sample.rfa",
                    "family_name": "sample",
                    "revit_category": "Mechanical Equipment",
                    "family_types": ["A"],
                    "family_parameters": ["Manufacturer"],
                    "family_parameter_details": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        metadata = read_metadata_from_json(str(path))
        assert metadata.revit_category == "Mechanical Equipment"


def test_invalid_rfa_path_is_rejected() -> None:
    try:
        validate_rfa_path("missing-file.rfa")
    except RfaReaderError as exc:
        assert "不存在" in str(exc)
    else:
        raise AssertionError("應拒絕不存在的 RFA")


def test_create_request_writes_queue_file() -> None:
    request = create_request(r"E:\Desktop\Codex\dummy.rfa")
    path = REQUEST_DIR / f"{request.request_id}.json"
    assert path.exists()
    path.unlink()


def test_addin_sources_exist() -> None:
    assert SOURCE_DLL.exists()


def test_manifest_uses_dynamic_dll_path() -> None:
    deploy_dll = get_ascii_deploy_dir() / versioned_dll_name(SOURCE_DLL)
    manifest = render_manifest(deploy_dll)
    assert str(deploy_dll.resolve()) in manifest


def test_listener_status_shape() -> None:
    status = get_listener_status()
    assert "connected" in status
    assert "label" in status


def test_settings_roundtrip(tmp_path=None) -> None:
    from tempfile import TemporaryDirectory
    import os

    original_appdata = os.environ.get("APPDATA")
    with TemporaryDirectory() as temp_dir:
        os.environ["APPDATA"] = temp_dir
        save_library_root(r"E:\Desktop\Codex\族群庫")
        assert get_settings_path().exists()
        assert load_settings()["library_root"] == r"E:\Desktop\Codex\族群庫"
    if original_appdata is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = original_appdata


def test_planned_name_uses_company_format() -> None:
    result = generate_planned_name(
        r"E:\Desktop\Codex\input\M_火警門擋 - 磁性 - 落地式.rfa",
        system="FP",
        family_name="M_火警門擋 - 磁性 - 落地式",
        editable_name="火警門擋",
        suffixes=["落地式"],
    )
    assert result == "SC-消防-火警門擋-落地式.rfa"


def test_name_analysis_extracts_suffixes() -> None:
    analysis = analyze_source_name("M_逆止閥 - 10-100 mm - 螺紋.rfa")
    assert analysis.base_name == "逆止閥"
    assert [(item.category, item.value) for item in analysis.suffixes] == [
        ("尺寸", "10-100 mm"),
        ("接合方式", "螺紋"),
    ]


def test_duplicate_checker_and_copy_name(tmp_path) -> None:
    existing = tmp_path / "SC-消防-火警門擋.rfa"
    existing.write_text("x", encoding="utf-8")
    duplicate = find_duplicate_names(
        str(tmp_path),
        "原始檔.rfa",
        "SC-消防-火警門擋.rfa",
    )
    assert duplicate["planned_name_exists"] is True
    assert build_available_copy_name(str(tmp_path), "SC-消防-火警門擋.rfa") == "SC-消防-火警門擋-複製.rfa"
    assert build_available_copy_name(
        str(tmp_path),
        "SC-消防-另一顆族群.rfa",
        force_copy=True,
    ) == "SC-消防-另一顆族群-複製.rfa"


def test_ingest_copies_without_modifying_source(tmp_path) -> None:
    source = tmp_path / "source.rfa"
    source.write_text("original", encoding="utf-8")
    library_root = tmp_path / "library"
    target_dir = library_root / "01 機電" / "03 FP 消防"
    target_dir.mkdir(parents=True)

    result = ingest_copy_only(
        str(source),
        str(library_root),
        r"01 機電\03 FP 消防",
        "SC-消防-火警門擋.rfa",
    )

    assert source.read_text(encoding="utf-8") == "original"
    assert result.destination_path.exists()
    assert result.destination_path.read_text(encoding="utf-8") == "original"


def test_record_ingest_writes_sqlite_index(tmp_path) -> None:
    library_root = tmp_path / "library"
    final = library_root / "01 機電" / "03 FP 消防" / "SC-消防-火警門擋.rfa"
    final.parent.mkdir(parents=True)
    final.write_text("x", encoding="utf-8")
    source = tmp_path / "source.rfa"
    source.write_text("x", encoding="utf-8")
    record_ingest(
        library_root=str(library_root),
        source_path=str(source),
        final_path=str(final),
        result={
            "system": "FP",
            "path": r"01 機電\03 FP 消防",
            "score": 70,
            "status": "classified",
            "source_metadata": {
                "revit_category": "火警裝置",
                "family_name": "M_火警門擋",
            },
        },
        base_name="火警門擋",
        suffix_options=[{"category": "安裝方式", "value": "落地式", "selected": True}],
        approved_path=None,
        planned_name_manual=False,
        duplicate_result=None,
    )
    records = fetch_recent_records(str(library_root))
    assert records[0]["system_name"] == "消防"
    assert records[0]["base_name"] == "火警門擋"


def test_export_library_index_xlsx(tmp_path) -> None:
    library_root = tmp_path / "library"
    final = library_root / "01 機電" / "03 FP 消防" / "SC-消防-火警門擋.rfa"
    final.parent.mkdir(parents=True)
    final.write_text("x", encoding="utf-8")
    source = tmp_path / "source.rfa"
    source.write_text("x", encoding="utf-8")
    record_ingest(
        library_root=str(library_root),
        source_path=str(source),
        final_path=str(final),
        result={
            "system": "FP",
            "path": r"01 機電\03 FP 消防",
            "score": 70,
            "status": "classified",
            "source_metadata": {
                "revit_category": "火警裝置",
                "family_name": "M_火警門擋",
            },
        },
        base_name="火警門擋",
        suffix_options=[],
        approved_path=None,
        planned_name_manual=False,
        duplicate_result=None,
    )
    path = export_library_index_xlsx(str(library_root))
    assert path.exists()


def test_parameter_preview_reports_missing_standard_fields() -> None:
    preview = build_parameter_preview(["SC_系統別"], "FP")
    missing_names = {item["name"] for item in preview["missing"]}
    assert "SC_主名" in missing_names
    assert "SC_消防設備類型" in missing_names


def test_parameter_preview_reports_attribute_mismatch() -> None:
    preview = build_parameter_preview(
        ["SC_系統別"],
        "FP",
        [{"name": "SC_系統別", "is_instance": True, "storage_type": "Integer"}],
    )
    issues = {(item["issue"], item["expected"], item["actual"]) for item in preview["mismatches"]}
    assert ("參數層級", "type", "instance") in issues
    assert ("儲存型別", "String", "Integer") in issues
    assert any(item["name"] == "SC_主名" for item in preview["actions"]["add"])
    assert any(item["name"] == "SC_系統別" for item in preview["actions"]["modify"])
    assert any(item["name"] == "SC_主名" for item in preview["actions"]["safe_add"])


def test_build_safe_text_values() -> None:
    values = build_safe_text_values(
        system="FP",
        base_name="火警門擋",
        source_file_name="M_火警門擋.rfa",
    )
    assert values == {
        "SC_原始檔名": "M_火警門擋.rfa",
        "SC_維護狀態": "使用中",
        "SC_系統別": "消防",
        "SC_主名": "火警門擋",
    }
