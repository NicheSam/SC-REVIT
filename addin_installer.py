import os
import shutil
import hashlib
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).parent
SOURCE_DLL = BASE_DIR / "revit_addin" / "bin" / "RfaMetadataAddin.dll"
ADDIN_FILE_NAME = "RfaMetadataAddin.addin"


@dataclass(frozen=True)
class AddinInstallResult:
    installed: bool
    target_path: Path
    message: str


def get_user_addins_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("找不到 APPDATA 環境變數")
    return Path(appdata) / "Autodesk" / "Revit" / "Addins" / "2024"


def get_ascii_deploy_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        raise RuntimeError("找不到 LOCALAPPDATA 環境變數")
    return Path(local_appdata) / "RfaMetadataAddin"


def get_manifest_assembly_paths(manifest_path: Path) -> tuple[Path, ...]:
    if not manifest_path.is_file():
        return ()
    try:
        root = ET.fromstring(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ET.ParseError):
        return ()

    paths = []
    for node in root.findall(".//AddIn/Assembly"):
        value = (node.text or "").strip()
        if not value:
            continue
        assembly_path = Path(value)
        if not assembly_path.is_absolute():
            assembly_path = manifest_path.parent / assembly_path
        paths.append(assembly_path)
    return tuple(paths)


def existing_manifest_is_usable(manifest_path: Path) -> bool:
    assembly_paths = get_manifest_assembly_paths(manifest_path)
    return bool(assembly_paths) and all(path.is_file() for path in assembly_paths)


def ensure_revit_addin_installed(force: bool = False) -> AddinInstallResult:
    if not SOURCE_DLL.exists():
        raise RuntimeError("找不到 RfaMetadataAddin.dll，請先建置外掛")

    ascii_deploy_dir = get_ascii_deploy_dir()
    ascii_deploy_dir.mkdir(parents=True, exist_ok=True)
    (ascii_deploy_dir / "sc_revit_home.txt").write_text(
        str(get_launcher_root()),
        encoding="utf-8",
    )

    target_dir = get_user_addins_dir()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise RuntimeError(
            "無法寫入 Revit 外掛資料夾；請以有權限的方式安裝外掛"
        ) from exc
    except FileExistsError as exc:
        if not target_dir.is_dir():
            raise RuntimeError("Revit 外掛目標路徑不是資料夾") from exc
    target_path = target_dir / ADDIN_FILE_NAME
    existed_before = target_path.exists()
    if not force and existing_manifest_is_usable(target_path):
        return AddinInstallResult(
            installed=False,
            target_path=target_path,
            message="保留現有 Revit 外掛部署",
        )

    ascii_deploy_dll = ascii_deploy_dir / versioned_dll_name(SOURCE_DLL)
    if (
        not ascii_deploy_dll.exists()
        or hashlib.sha256(ascii_deploy_dll.read_bytes()).digest()
        != hashlib.sha256(SOURCE_DLL.read_bytes()).digest()
    ):
        shutil.copy2(SOURCE_DLL, ascii_deploy_dll)

    try:
        if existed_before:
            target_path.chmod(0o666)
        manifest = render_manifest(ascii_deploy_dll)
        target_path.write_text(manifest, encoding="utf-8")
        target_path.chmod(0o444)
    except PermissionError as exc:
        raise RuntimeError(
            "無法寫入 Revit 外掛資料夾；請允許安裝或手動複製 .addin"
        ) from exc
    return AddinInstallResult(
        installed=not existed_before,
        target_path=target_path,
        message="已自動安裝 Revit 外掛",
    )


def get_launcher_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return BASE_DIR.resolve()


def render_manifest(dll_path: Path) -> str:
    normalized = str(dll_path.resolve())
    return f"""<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>RfaMetadataListener</Name>
    <Assembly>{normalized}</Assembly>
    <AddInId>6DCCB516-9F7B-4AF4-90D4-6BE5B8B9B1D8</AddInId>
    <FullClassName>RfaMetadataAddin.RfaMetadataBootstrapApplication</FullClassName>
    <VendorId>DEX</VendorId>
    <VendorDescription>Background queue listener for RFA metadata requests</VendorDescription>
  </AddIn>
  <AddIn Type="Command">
    <Name>RfaMetadataAddin</Name>
    <Assembly>{normalized}</Assembly>
    <AddInId>1C9F98C5-50C8-4C1E-9D1F-7BEAD9A6762C</AddInId>
    <FullClassName>RfaMetadataAddin.RfaMetadataCommand</FullClassName>
    <VendorId>DEX</VendorId>
    <VendorDescription>RFA metadata reader for internal classifier</VendorDescription>
  </AddIn>
  <AddIn Type="Command">
    <Name>SC Drainage Runtime Self Test</Name>
    <Assembly>{normalized}</Assembly>
    <AddInId>A60D2AB6-D860-43D0-91D6-82F4EAC7216A</AddInId>
    <FullClassName>RfaMetadataAddin.DrainageRuntimeSelfTestCommand</FullClassName>
    <VendorId>DEX</VendorId>
    <VendorDescription>Development-only runtime verification for SC drainage tools</VendorDescription>
  </AddIn>
</RevitAddIns>
"""


def versioned_dll_name(source_dll: Path) -> str:
    digest = hashlib.sha256(source_dll.read_bytes()).hexdigest()[:12]
    return f"RfaMetadataAddin.{digest}.dll"


if __name__ == "__main__":
    result = ensure_revit_addin_installed(force="--force" in sys.argv[1:])
    print(result.message)
    print(result.target_path)
