from classifier import classify
from rfa_reader import RfaMetadata, request_metadata_from_revit


def classify_rfa_via_revit(rfa_path: str, timeout_seconds: int = 180) -> dict:
    metadata: RfaMetadata = request_metadata_from_revit(
        rfa_path,
        timeout_seconds=timeout_seconds,
    )
    result = classify(metadata.to_classifier_metadata())
    result["source_metadata"] = {
        "file_name": metadata.file_name,
        "family_name": metadata.family_name,
        "revit_category": metadata.revit_category,
        "family_types": metadata.family_types,
        "family_parameters": metadata.family_parameters,
        "family_parameter_details": metadata.family_parameter_details,
    }
    return result


def refresh_result_metadata_via_revit(
    existing_result: dict,
    rfa_path: str,
    timeout_seconds: int = 180,
) -> dict:
    metadata: RfaMetadata = request_metadata_from_revit(
        rfa_path,
        timeout_seconds=timeout_seconds,
    )
    refreshed = dict(existing_result)
    refreshed["source_metadata"] = {
        "file_name": metadata.file_name,
        "family_name": metadata.family_name,
        "revit_category": metadata.revit_category,
        "family_types": metadata.family_types,
        "family_parameters": metadata.family_parameters,
        "family_parameter_details": metadata.family_parameter_details,
    }
    return refreshed
