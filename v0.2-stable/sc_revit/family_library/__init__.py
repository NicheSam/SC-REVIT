"""Family library governance API boundary."""

from classifier import classify as classify_family
from duplicate_checker import build_available_copy_name, find_duplicate_names
from ingest_service import IngestError, ingest_copy_only
from library_index import record_ingest
from library_validator import validate_library_root
from naming_rules import SUFFIX_ORDER, analyze_source_name, generate_planned_name
from rfa_reader import RfaReaderError, read_rfa_metadata
from workflow import classify_rfa_via_revit, refresh_result_metadata_via_revit

__all__ = [
    "classify_family",
    "build_available_copy_name",
    "find_duplicate_names",
    "IngestError",
    "ingest_copy_only",
    "record_ingest",
    "validate_library_root",
    "SUFFIX_ORDER",
    "analyze_source_name",
    "generate_planned_name",
    "RfaReaderError",
    "read_rfa_metadata",
    "classify_rfa_via_revit",
    "refresh_result_metadata_via_revit",
]
