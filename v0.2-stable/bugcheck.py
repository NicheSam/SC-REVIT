from pathlib import Path
import json
import tempfile

from classifier import classify
from library_validator import validate_library_root
from rfa_reader import RfaMetadata, RfaReaderError, read_metadata_from_json, validate_rfa_path


def run() -> None:
    cases = []

    cases.append(("valid_library_root", validate_library_root(r"E:\Desktop\Codex\族群庫")["valid"] is True))
    cases.append(("invalid_library_root", validate_library_root(r"E:\Desktop\Codex")["valid"] is False))

    try:
        validate_rfa_path("missing-file.rfa")
    except RfaReaderError:
        cases.append(("missing_rfa_rejected", True))
    else:
        cases.append(("missing_rfa_rejected", False))

    with tempfile.TemporaryDirectory() as temp_dir:
        json_path = Path(temp_dir) / "bad.json"
        json_path.write_text(json.dumps({"file_name": "x.rfa"}), encoding="utf-8")
        try:
            read_metadata_from_json(str(json_path))
        except RfaReaderError:
            cases.append(("invalid_metadata_rejected", True))
        else:
            cases.append(("invalid_metadata_rejected", False))

    smoke = classify(
        RfaMetadata(
            file_name="Smoke Detector Ceiling.rfa",
            family_name="煙霧偵測器",
            revit_category="Fire Alarm Devices",
            family_types=["天花型"],
            family_parameters=[],
            family_parameter_details=[],
        ).to_classifier_metadata()
    )
    cases.append(("smoke_detector_to_fp", smoke["path"].endswith("04 火警偵測\\01 煙霧偵測器")))

    emergency = classify(
        RfaMetadata(
            file_name="Emergency Light Wall.rfa",
            family_name="緊急照明",
            revit_category="Lighting Fixtures",
            family_types=["壁掛型"],
            family_parameters=[],
            family_parameter_details=[],
        ).to_classifier_metadata()
    )
    cases.append(("emergency_light_to_fp", emergency["path"].endswith("02 消防設備\\07 緊急照明")))

    for name, passed in cases:
        print(f"{name}={'PASS' if passed else 'FAIL'}")

    if not all(passed for _, passed in cases):
        raise SystemExit(1)


if __name__ == "__main__":
    run()
