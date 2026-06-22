import os
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from gui_models import RfaTask
from addin_installer import ensure_revit_addin_installed
from dwg_block_reader import DwgBlockReaderError, read_dwg_blocks
from listener_status import get_listener_status
from xlsx_exporter import export_library_index_xlsx, export_opening_candidates_xlsx, write_xlsx
from sc_revit.family_library import (
    IngestError,
    SUFFIX_ORDER,
    analyze_source_name,
    build_available_copy_name,
    find_duplicate_names,
    generate_planned_name,
    ingest_copy_only,
    record_ingest,
    validate_library_root,
)
from sc_revit.parameters import (
    build_parameter_preview,
    build_safe_text_values,
    request_add_missing_string_parameters,
    request_set_string_parameter_values,
)
from sc_revit.openings import (
    request_opening_context,
    request_place_opening_markers,
    request_scan_opening_candidates,
    request_view_opening_candidate,
)
from sc_revit.cad_points import (
    default_mapping_dir,
    export_cad_points_batch_report_xlsx,
    filter_mappings_for_blocks,
    load_mapping_file,
    request_cad_import_path,
    request_create_dwg_preview_markers,
    request_place_dwg_blocks,
    request_point_placement_context,
    request_transform_dwg_points,
    safe_mapping_file_name,
    save_mapping_file,
)
from sc_revit.fire_branch import (
    request_create_fire_branch_preview,
    request_create_fire_branch_pipes,
    request_fire_branch_context,
    request_fire_branch_selection,
)
from sc_revit.connect_fitting import request_connect_pipe_fittings, request_diagnose_mep_connectors
from sc_revit.core.backstage import request_delete_tracked_elements, request_sync_tracked_elements
from sc_revit.core.batch import BatchStore, DB_PATH, activate_batch, batch_context
from sc_revit.element_inspector import request_inspect_selected_elements
from sc_revit.parameter_audit import request_scan_sc_parameters
from sc_revit.piping_support import request_preview_piping_support_points
from sc_revit.project_recovery import (
    get_project_recovery_dir,
    request_project_family_export,
    request_project_family_scan,
)
from settings_store import load_settings, save_library_root
from workflow import classify_rfa_via_revit, refresh_result_metadata_via_revit


DWG_UNIT_TO_FEET = {
    "自動": None,
    "毫米": 1.0 / 304.8,
    "公分": 1.0 / 30.48,
    "公尺": 1.0 / 0.3048,
    "英尺": 1.0,
}


class FamilyClassifierApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.app_mode = self._read_app_mode()
        titles = {
            "archive": "REVIT 族群歸檔器",
            "recovery": "REVIT 族群回收器",
            "placement": "REVIT 批量點位放置",
            "fire_branch": "REVIT 消防支管建立",
            "opening_check": "REVIT 開孔定位",
            "backstage": "SC REVIT " + "\u5f8c\u53f0",
            "element_inspector": "SC REVIT " + "\u5143\u4ef6\u8eab\u4efd\u6aa2\u67e5",
            "parameter_audit": "SC REVIT " + "SC \u53c3\u6578\u5065\u6aa2",
            "connect_fitting": "SC REVIT " + "\u7ba1\u7dda\u65b7\u9ede\u6aa2\u67e5",
            "piping_support": "SC REVIT " + "\u7ba1\u652f\u6490\u9810\u89bd",
        }
        self.title(titles.get(self.app_mode, "REVIT 族群工具"))
        if self.app_mode == "backstage":
            self.geometry("1280x760")
            self.minsize(1180, 700)
        else:
            self.geometry("1100x700")
            self.minsize(980, 620)
        self._configure_fonts()

        self.library_root: str | None = None
        self.tasks: dict[str, RfaTask] = {}
        self.visible_filter = tk.StringVar(value="全部")
        self.total_tasks = 0
        self.finished_tasks = 0
        self.project_scan_result: dict | None = None
        self.project_families_by_iid: dict[str, dict] = {}
        self.placement_context: dict | None = None
        self.placement_preview: dict | None = None

        self._ensure_addin_installed()
        self._build_ui()
        self._load_or_choose_library_root()

    def _read_app_mode(self) -> str:
        args = {arg.casefold() for arg in sys.argv[1:]}
        if "--mode=recovery" in args or "--recovery" in args:
            return "recovery"
        if "--mode=placement" in args or "--placement" in args:
            return "placement"
        if "--mode=fire-branch" in args or "--fire-branch" in args:
            return "fire_branch"
        if "--mode=opening-check" in args or "--opening-check" in args:
            return "opening_check"
        if "--mode=backstage" in args or "--backstage" in args:
            return "backstage"
        if "--mode=element-inspector" in args or "--element-inspector" in args:
            return "element_inspector"
        if "--mode=parameter-audit" in args or "--parameter-audit" in args:
            return "parameter_audit"
        if "--mode=connect-fitting" in args or "--connect-fitting" in args:
            return "connect_fitting"
        if "--mode=piping-support" in args or "--piping-support" in args:
            return "piping_support"
        return "archive"

    def _configure_fonts(self) -> None:
        # Windows 繁中環境下的黑體字族；若不存在，Tk 會自動回退。
        default_font = tkfont.nametofont("TkDefaultFont")
        text_font = tkfont.nametofont("TkTextFont")
        heading_font = tkfont.nametofont("TkHeadingFont")
        for item in (default_font, text_font, heading_font):
            item.configure(family="Microsoft JhengHei UI", size=10)
        style = ttk.Style(self)
        style.configure(".", font=("Microsoft JhengHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft JhengHei UI", 10, "bold"))

    def _ensure_addin_installed(self) -> None:
        try:
            result = ensure_revit_addin_installed()
        except Exception as exc:
            messagebox.showerror(
                "Revit 外掛檢查失敗",
                f"{exc}\n\n若外掛尚未安裝，Revit 監聽狀態會一直顯示未連線。",
            )
            return

        if result.installed:
            messagebox.showinfo(
                "Revit 外掛已安裝",
                "已自動安裝 RfaMetadataAddin。\n"
                "如果 Revit 目前已開啟，請先關閉並重新啟動一次，讓監聽器載入。",
            )

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="族群庫位置").grid(row=0, column=0, sticky="w")
        self.library_var = tk.StringVar(value="尚未載入")
        ttk.Label(top, textvariable=self.library_var).grid(row=0, column=1, sticky="w", padx=10)
        self.listener_var = tk.StringVar(value="Revit：檢查中")
        ttk.Label(top, textvariable=self.listener_var).grid(row=0, column=2, padx=(8, 12))
        ttk.Button(top, text="重新選擇", command=lambda: self._choose_library_root(force=True)).grid(row=0, column=3, padx=(8, 0))

        if self.app_mode == "archive":
            actions = ttk.Frame(self, padding=(12, 0, 12, 12))
            actions.grid(row=1, column=0, sticky="ew")
            ttk.Button(actions, text="加入族群", command=self._add_files).pack(side="left")
            ttk.Button(actions, text="從專案回收中匯入", command=self._import_from_project_recovery).pack(side="left", padx=(8, 4))
            ttk.Button(actions, text="全選", command=self._select_all).pack(side="left", padx=(8, 4))
            ttk.Button(actions, text="開始分類", command=self._classify_selected).pack(side="left", padx=(4, 4))
            ttk.Button(actions, text="清除選取", command=self._clear_selection).pack(side="left", padx=(4, 4))
            ttk.Button(actions, text="加入族群庫", command=self._ingest_selected).pack(side="left", padx=(4, 0))
            ttk.Label(actions, text="顯示").pack(side="left", padx=(16, 4))
            filter_box = ttk.Combobox(
                actions,
                textvariable=self.visible_filter,
                values=["全部", "等待", "已分類", "人工審核完成", "需確認", "失敗"],
                state="readonly",
                width=10,
            )
            filter_box.pack(side="left")
            filter_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_tree())

        main_tabs = ttk.Notebook(self)
        main_tabs.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

        library_tab = ttk.Frame(main_tabs)
        if self.app_mode == "placement":
            placement_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(placement_tab, text="批量點位放置")
            self._build_point_placement_tab(placement_tab)
            self._refresh_listener_status()
            return
        if self.app_mode == "fire_branch":
            fire_branch_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(fire_branch_tab, text="消防支管建立")
            self._build_fire_branch_tab(fire_branch_tab)
            self._refresh_listener_status()
            return
        if self.app_mode == "opening_check":
            opening_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(opening_tab, text="開孔定位")
            self._build_opening_check_tab(opening_tab)
            self._refresh_listener_status()
            return
        if self.app_mode == "recovery":
            project_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(project_tab, text="專案回收")
            self._build_project_recovery_tab(project_tab)
            self._refresh_listener_status()
            return
        if self.app_mode == "backstage":
            backstage_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(backstage_tab, text="SC " + "\u5f8c\u53f0")
            self._build_backstage_tab(backstage_tab)
            self._refresh_listener_status()
            return
        if self.app_mode == "element_inspector":
            inspector_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(inspector_tab, text="\u5143\u4ef6\u8eab\u4efd\u6aa2\u67e5")
            self._build_element_inspector_tab(inspector_tab)
            self._refresh_listener_status()
            return
        if self.app_mode == "parameter_audit":
            parameter_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(parameter_tab, text="SC \u53c3\u6578\u5065\u6aa2")
            self._build_parameter_audit_tab(parameter_tab)
            self._refresh_listener_status()
            return
        if self.app_mode == "connect_fitting":
            fitting_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(fitting_tab, text="\u7ba1\u7dda\u65b7\u9ede\u6aa2\u67e5")
            self._build_connect_fitting_tab(fitting_tab)
            self._refresh_listener_status()
            return
        if self.app_mode == "piping_support":
            support_tab = ttk.Frame(main_tabs, padding=12)
            main_tabs.add(support_tab, text="\u7ba1\u652f\u6490\u9810\u89bd")
            self._build_piping_support_tab(support_tab)
            self._refresh_listener_status()
            return
        main_tabs.add(library_tab, text="族群歸檔")

        library_tab.rowconfigure(0, weight=1)
        library_tab.columnconfigure(0, weight=1)

        body = ttk.Panedwindow(library_tab, orient="horizontal")
        body.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(body)
        right = ttk.Frame(body, padding=12)
        body.add(left, weight=3)
        body.add(right, weight=2)

        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            left,
            columns=("file_name", "planned_name", "status", "classification"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("file_name", text="原檔名")
        self.tree.heading("planned_name", text="預計修改名稱")
        self.tree.heading("status", text="狀態")
        self.tree.heading("classification", text="建議分類")
        self.tree.column("file_name", width=180)
        self.tree.column("planned_name", width=180)
        self.tree.column("status", width=110, anchor="center")
        self.tree.column("classification", width=240)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._show_selected_detail)

        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        ttk.Label(right, text="入庫確認", font=("Microsoft JhengHei UI", 12, "bold")).pack(anchor="w")
        detail_tabs = ttk.Notebook(right)
        detail_tabs.pack(fill="both", expand=True, pady=(8, 0))

        judgement_tab = ttk.Frame(detail_tabs, padding=(0, 8, 0, 0))
        standard_tab = ttk.Frame(detail_tabs, padding=8)
        detail_tabs.add(judgement_tab, text="入庫確認")
        detail_tabs.add(standard_tab, text="RFA 資訊")

        judgement_tab.rowconfigure(0, weight=1)
        judgement_tab.columnconfigure(0, weight=1)
        self.detail_text = tk.Text(judgement_tab, wrap="word", height=16)
        self.detail_text.grid(row=0, column=0, sticky="nsew")

        ttk.Label(judgement_tab, text="人工改選資料夾").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.override_var = tk.StringVar()
        self.override_entry = ttk.Entry(judgement_tab, textvariable=self.override_var)
        self.override_entry.grid(row=2, column=0, sticky="ew", pady=(4, 8))
        override_actions = ttk.Frame(judgement_tab)
        override_actions.grid(row=3, column=0, sticky="ew")
        ttk.Button(override_actions, text="選擇資料夾", command=self._choose_override_folder).pack(side="left")
        ttk.Button(override_actions, text="套用改選", command=self._apply_override).pack(side="right")

        ttk.Label(judgement_tab, text="主名").grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.base_name_var = tk.StringVar()
        self.base_name_entry = ttk.Entry(judgement_tab, textvariable=self.base_name_var)
        self.base_name_entry.grid(row=5, column=0, sticky="ew", pady=(4, 8))
        self.base_name_entry.bind("<KeyRelease>", lambda _event: self._preview_planned_name())

        ttk.Label(judgement_tab, text="可保留資訊").grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.suffix_frame = ttk.Frame(judgement_tab)
        self.suffix_frame.grid(row=7, column=0, sticky="ew", pady=(4, 8))
        self.suffix_vars: list[tuple[str, str, tk.BooleanVar]] = []

        ttk.Label(judgement_tab, text="預計修改名稱").grid(row=8, column=0, sticky="w", pady=(4, 0))
        self.planned_name_var = tk.StringVar()
        self.planned_name_entry = ttk.Entry(judgement_tab, textvariable=self.planned_name_var)
        self.planned_name_entry.grid(row=9, column=0, sticky="ew", pady=(4, 8))
        ttk.Button(
            judgement_tab,
            text="套用名稱",
            command=self._apply_planned_name,
        ).grid(row=10, column=0, sticky="e")

        self.duplicate_preview = ttk.Treeview(judgement_tab)

        standard_tab.rowconfigure(1, weight=1)
        standard_tab.columnconfigure(0, weight=1)
        ttk.Label(
            standard_tab,
            text="公司標準參數預覽（只會修改加入族群庫後的複製檔）",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.standard_text = tk.Text(standard_tab, wrap="word")
        self.standard_text.grid(row=1, column=0, sticky="nsew")
        ttk.Button(
            standard_tab,
            text="套用公司標準",
            command=self._apply_company_standard,
        ).grid(row=2, column=0, sticky="e", pady=(8, 0))

        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)
        self.summary_var = tk.StringVar(value="尚未加入檔案")
        ttk.Label(bottom, textvariable=self.summary_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))

        browser = ttk.LabelFrame(self, text="庫內瀏覽 / 搜尋（暫緩）", padding=12)
        browser.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))
        browser.columnconfigure(1, weight=1)
        ttk.Label(browser, text="關鍵字").grid(row=0, column=0, sticky="w")
        ttk.Entry(browser).grid(row=0, column=1, sticky="ew", padx=(8, 12))
        ttk.Combobox(browser, values=["全部系統", "HVAC", "PLB", "FP", "PWR", "LTG", "ELV"], state="disabled", width=14).grid(row=0, column=2)
        ttk.Button(browser, text="搜尋", state="disabled").grid(row=0, column=3, padx=(8, 0))
        ttk.Label(
            browser,
            text="搜尋功能暫緩，先保留版面位置。",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self.tree.tag_configure("done", background="#e8f5e9")
        self.tree.tag_configure("review", background="#fff8e1")
        self.tree.tag_configure("error", background="#ffebee")
        self.tree.tag_configure("waiting", background="#f5f5f5")
        self._refresh_listener_status()

    def _build_backstage_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        parent.rowconfigure(2, weight=2)

        status_frame = ttk.LabelFrame(parent, text="\u5de5\u4f5c\u6982\u6cc1", padding=10)
        status_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for column in range(8):
            status_frame.columnconfigure(column, weight=1 if column % 2 == 1 else 0)
        self.backstage_total_var = tk.StringVar(value="0")
        self.backstage_failed_var = tk.StringVar(value="0")
        self.backstage_product_var = tk.StringVar(value="0")
        self.backstage_db_var = tk.StringVar(value=str(DB_PATH))
        ttk.Label(status_frame, text="\u64cd\u4f5c\u8a18\u9304").grid(row=0, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.backstage_total_var).grid(row=0, column=1, sticky="w", padx=(6, 18))
        ttk.Label(status_frame, text="\u9700\u8981\u6ce8\u610f").grid(row=0, column=2, sticky="w")
        ttk.Label(status_frame, textvariable=self.backstage_failed_var).grid(row=0, column=3, sticky="w", padx=(6, 18))
        ttk.Label(status_frame, text="\u76ee\u524d\u53ef\u522a\u9664").grid(row=0, column=4, sticky="w")
        ttk.Label(status_frame, textvariable=self.backstage_product_var).grid(row=0, column=5, sticky="w", padx=(6, 18))
        ttk.Button(status_frame, text="\u91cd\u65b0\u6574\u7406", command=self._refresh_backstage_batches).grid(row=0, column=6, sticky="e")
        ttk.Button(status_frame, text="\u958b\u555f\u7d00\u9304\u8cc7\u6599\u593e", command=self._open_backstage_runtime_folder).grid(row=0, column=7, sticky="e", padx=(8, 0))
        ttk.Label(status_frame, text="\u7d00\u9304\u6a94").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(status_frame, textvariable=self.backstage_db_var).grid(row=1, column=1, columnspan=7, sticky="ew", pady=(8, 0))

        main = ttk.Panedwindow(parent, orient="horizontal")
        main.grid(row=1, column=0, sticky="nsew")
        nav = ttk.LabelFrame(main, text="\u7ba1\u7406\u9805\u76ee", padding=10)
        center = ttk.LabelFrame(main, text="\u5efa\u7acb\u7d00\u9304", padding=10)
        side = ttk.LabelFrame(main, text="\u9078\u53d6\u9805\u76ee", padding=10)
        main.add(nav, weight=1)
        main.add(center, weight=5)
        main.add(side, weight=3)

        self.backstage_view_var = tk.StringVar(value="\u5efa\u7acb\u7d00\u9304")
        for label in ["\u9996\u9801", "\u5efa\u7acb\u7d00\u9304", "\u9700\u8981\u6ce8\u610f", "\u53ef\u7ba1\u7406\u5143\u4ef6", "\u532f\u51fa", "\u8a2d\u5b9a"]:
            ttk.Radiobutton(
                nav,
                text=label,
                value=label,
                variable=self.backstage_view_var,
                command=self._refresh_backstage_batches,
            ).pack(anchor="w", pady=4)
        ttk.Separator(nav).pack(fill="x", pady=10)
        ttk.Label(
            nav,
            text="\u9019\u88e1\u7528\u4f86\u67e5\u770b\u5efa\u7acb\u7d50\u679c\u3001\u532f\u51fa\u5831\u8868\u3001\u6aa2\u67e5\u6a21\u578b\u72c0\u614b\uff0c\u4ee5\u53ca\u79fb\u9664\u5916\u639b\u672c\u6b21\u5efa\u7acb\u7684 Revit \u5143\u4ef6\u3002",
            wraplength=150,
            foreground="#666666",
        ).pack(anchor="w", pady=(0, 4))

        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        self.backstage_tree = ttk.Treeview(
            center,
            columns=("created_at", "feature", "action", "status", "tracked", "existing", "missing", "unknown", "errors", "title"),
            show="headings",
            selectmode="browse",
        )
        headings = {
            "created_at": "\u6642\u9593",
            "feature": "\u529f\u80fd",
            "action": "\u52d5\u4f5c",
            "status": "\u72c0\u614b",
            "tracked": "\u5efa\u7acb",
            "existing": "\u5b58\u5728",
            "missing": "\u5df2\u522a\u9664",
            "unknown": "\u7121\u6cd5\u78ba\u8a8d",
            "errors": "\u7570\u5e38",
            "title": "\u8aaa\u660e",
        }
        widths = {"created_at": 145, "feature": 95, "action": 125, "status": 70, "tracked": 55, "existing": 55, "missing": 65, "unknown": 55, "errors": 55, "title": 230}
        for column, title in headings.items():
            self.backstage_tree.heading(column, text=title)
            self.backstage_tree.column(column, width=widths[column], anchor="center" if column != "title" else "w")
        self.backstage_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(center, orient="vertical", command=self.backstage_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.backstage_tree.configure(yscrollcommand=scrollbar.set)
        self.backstage_tree.bind("<<TreeviewSelect>>", self._show_backstage_batch_detail)

        side.columnconfigure(0, weight=1)
        self.backstage_selected_var = tk.StringVar(value="\u672a\u9078\u64c7\u6279\u6b21")
        self.backstage_selected_status_var = tk.StringVar(value="-")
        self.backstage_selected_counts_var = tk.StringVar(value="-")
        ttk.Label(side, text="\u9078\u53d6\u7684\u5de5\u4f5c", font=("Microsoft JhengHei UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(side, textvariable=self.backstage_selected_var, wraplength=320).grid(row=1, column=0, sticky="ew", pady=(6, 8))
        ttk.Label(side, text="\u72c0\u614b").grid(row=2, column=0, sticky="w")
        ttk.Label(side, textvariable=self.backstage_selected_status_var).grid(row=3, column=0, sticky="ew", pady=(2, 8))
        ttk.Label(side, text="\u6578\u91cf").grid(row=4, column=0, sticky="w")
        ttk.Label(side, textvariable=self.backstage_selected_counts_var).grid(row=5, column=0, sticky="ew", pady=(2, 12))
        ttk.Button(side, text="\u532f\u51fa\u9019\u6b21\u5de5\u4f5c XLSX", command=self._export_selected_batch_xlsx).grid(row=6, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(side, text="\u91cd\u65b0\u6aa2\u67e5\u6a21\u578b\u72c0\u614b", command=self._sync_selected_batch_products).grid(row=7, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(side, text="\u522a\u9664\u9019\u6b21\u5efa\u7acb\u7684\u5143\u4ef6", command=self._delete_selected_batch_products).grid(row=8, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            side,
            text="\u522a\u9664\u6703\u5148\u6aa2\u67e5\u6a21\u578b\u73fe\u6cc1\uff0c\u53ea\u8655\u7406\u9019\u6b21\u7531\u5916\u639b\u5efa\u7acb\u7684\u5143\u4ef6\uff1b\u4e0d\u6703\u522a\u9664 RFA \u8907\u88fd\u6a94\u6216 CAD Link\u3002",
            wraplength=320,
            foreground="#666666",
        ).grid(row=9, column=0, sticky="ew", pady=(8, 0))

        detail_frame = ttk.LabelFrame(parent, text="\u57f7\u884c\u5167\u5bb9", padding=10)
        detail_frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.backstage_detail = tk.Text(detail_frame, height=10, wrap="word")
        self.backstage_detail.grid(row=0, column=0, sticky="nsew")
        detail_scrollbar = ttk.Scrollbar(detail_frame, orient="vertical", command=self.backstage_detail.yview)
        detail_scrollbar.grid(row=0, column=1, sticky="ns")
        self.backstage_detail.configure(yscrollcommand=detail_scrollbar.set)

        self.backstage_batches_by_iid = {}
        self.backstage_batch_request_counts = {}
        self._refresh_backstage_batches()

    def _refresh_backstage_batches(self, select_batch_id: str | None = None) -> None:
        if not hasattr(self, "backstage_tree"):
            return
        for item in self.backstage_tree.get_children():
            self.backstage_tree.delete(item)
        store = BatchStore()
        batches = store.list_batches(limit=500)
        self.backstage_batches_by_iid = {}
        self.backstage_batch_request_counts = {}
        view = self.backstage_view_var.get() if hasattr(self, "backstage_view_var") else "\u5efa\u7acb\u7d00\u9304"
        total_products = 0
        failed_batches = 0
        visible_index = 0
        for batch in batches:
            requests = store.list_requests(batch.get("batch_id", ""))
            failed_requests = sum(1 for item in requests if item.get("status") == "failed" or item.get("error_message"))
            product_count = int(batch.get("product_count", 0) or 0)
            tracked_count = int(batch.get("tracked_count", 0) or 0)
            existing_count = int(batch.get("existing_count", product_count) or 0)
            missing_count = int(batch.get("missing_count", 0) or 0)
            unknown_count = int(batch.get("unknown_count", 0) or 0)
            total_products += existing_count
            is_failed = batch.get("status") == "failed" or bool(batch.get("error_message")) or failed_requests > 0
            if is_failed:
                failed_batches += 1
            if view == "\u9700\u8981\u6ce8\u610f" and not is_failed:
                continue
            if view == "\u53ef\u7ba1\u7406\u5143\u4ef6" and product_count <= 0:
                continue
            iid = str(visible_index)
            visible_index += 1
            self.backstage_batches_by_iid[iid] = batch
            self.backstage_batch_request_counts[iid] = (len(requests), failed_requests)
            self.backstage_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    batch.get("created_at", ""),
                    self._display_feature_name(batch.get("feature", "")),
                    batch.get("action", ""),
                    self._display_batch_status(batch.get("status", "")),
                    tracked_count,
                    existing_count,
                    missing_count,
                    unknown_count,
                    failed_requests,
                    batch.get("title", ""),
                ),
            )
        self.backstage_total_var.set(str(len(batches)))
        self.backstage_failed_var.set(str(failed_batches))
        self.backstage_product_var.set(str(total_products))
        if select_batch_id:
            for iid, batch in self.backstage_batches_by_iid.items():
                if str(batch.get("batch_id", "")) == str(select_batch_id):
                    self.backstage_tree.selection_set(iid)
                    self.backstage_tree.focus(iid)
                    self._show_backstage_batch_detail()
                    return
        self._set_backstage_detail(self._backstage_view_intro(view, len(self.backstage_batches_by_iid)))
        self.backstage_selected_var.set("\u672a\u9078\u64c7\u5de5\u4f5c")
        self.backstage_selected_status_var.set("-")
        self.backstage_selected_counts_var.set("-")

    def _display_feature_name(self, feature: object) -> str:
        mapping = {
            "family_archive": "\u65cf\u7fa4\u6b78\u6a94",
            "family_library": "\u65cf\u7fa4\u6b78\u6a94",
            "project_recovery": "\u5c08\u6848\u56de\u6536",
            "cad_points": "CAD \u9ede\u4f4d",
            "openings": "\u958b\u5b54\u5b9a\u4f4d",
            "fire_branch": "\u6d88\u9632\u652f\u7ba1",
            "backstage": "\u5f8c\u53f0",
        }
        text = str(feature or "")
        return mapping.get(text, text)

    def _display_batch_status(self, status: object) -> str:
        mapping = {"running": "\u57f7\u884c\u4e2d", "success": "\u6210\u529f", "failed": "\u9700\u8981\u6ce8\u610f"}
        text = str(status or "")
        return mapping.get(text, text)

    def _backstage_view_intro(self, view: str, visible_count: int) -> str:
        lines = [
            f"\u76ee\u524d\u5340\u57df\uff1a{view}",
            f"\u986f\u793a\u6279\u6b21\uff1a{visible_count}",
            "",
        ]
        if view == "\u9996\u9801":
            lines.append("\u7528\u4f86\u5feb\u901f\u6aa2\u8996 SC REVIT \u7684\u64cd\u4f5c\u72c0\u614b\u3001\u5931\u6557\u6279\u6b21\u8207\u53ef\u7ba1\u7406\u7522\u7269\u3002")
        elif view == "\u9700\u8981\u6ce8\u610f":
            lines.append("\u53ea\u986f\u793a\u5931\u6557\u6279\u6b21\u6216\u542b\u5931\u6557 Revit \u8acb\u6c42\u7684\u7d00\u9304\u3002")
        elif view == "\u53ef\u7ba1\u7406\u5143\u4ef6":
            lines.append("\u53ea\u986f\u793a\u5c1a\u6709\u53ef\u7ba1\u7406 Revit \u5143\u4ef6\u7684\u5efa\u7acb\u7d00\u9304\u3002")
        elif view == "\u532f\u51fa":
            lines.append("\u9078\u53d6\u6279\u6b21\u5f8c\uff0c\u53ef\u5f9e\u53f3\u5074\u532f\u51fa\u672c\u6279\u6b21 XLSX\u3002")
        elif view == "\u8a2d\u5b9a":
            lines.extend(["\u7d00\u9304\u8cc7\u6599\u5eab\uff1a", str(DB_PATH)])
        else:
            lines.append("\u9078\u53d6\u6279\u6b21\u5f8c\uff0c\u4e0b\u65b9\u6703\u986f\u793a\u8acb\u6c42\u3001\u932f\u8aa4\u8207\u7d50\u679c\u660e\u7d30\u3002")
        return "\n".join(lines)

    def _set_backstage_detail(self, text: str) -> None:
        if not hasattr(self, "backstage_detail"):
            return
        self.backstage_detail.delete("1.0", "end")
        self.backstage_detail.insert("1.0", text)

    def _selected_backstage_batch(self) -> dict | None:
        selection = self.backstage_tree.selection() if hasattr(self, "backstage_tree") else []
        if not selection:
            return None
        return self.backstage_batches_by_iid.get(selection[0])

    def _show_backstage_batch_detail(self, _event=None) -> None:
        if not hasattr(self, "backstage_detail"):
            return
        selection = self.backstage_tree.selection()
        if not selection:
            return
        batch = self.backstage_batches_by_iid.get(selection[0])
        if not batch:
            return
        store = BatchStore()
        batch_id = batch.get("batch_id", "")
        requests = store.list_requests(batch_id)
        events = store.list_events(batch_id)
        failed_requests = sum(1 for item in requests if item.get("status") == "failed" or item.get("error_message"))
        self.backstage_selected_var.set(str(batch_id))
        self.backstage_selected_status_var.set(self._display_batch_status(batch.get("status", "")))
        self.backstage_selected_counts_var.set(
            f"\u64cd\u4f5c {len(requests)}\uff5c\u5efa\u7acb {batch.get('tracked_count', 0)}\uff5c\u5b58\u5728 {batch.get('existing_count', 0)}\uff5c\u5df2\u522a\u9664 {batch.get('missing_count', 0)}\uff5c\u7121\u6cd5\u78ba\u8a8d {batch.get('unknown_count', 0)}\uff5c\u7570\u5e38 {failed_requests}"
        )
        lines = [
            f"\u6279\u6b21\uff1a{batch_id}",
            f"\u529f\u80fd\uff1a{self._display_feature_name(batch.get('feature', ''))}",
            f"\u52d5\u4f5c\uff1a{batch.get('action', '')}",
            f"\u72c0\u614b\uff1a{self._display_batch_status(batch.get('status', ''))}",
            f"\u6642\u9593\uff1a{batch.get('created_at', '')} -> {batch.get('updated_at', '')}",
            f"\u5efa\u7acb\u7e3d\u6578\uff1a{batch.get('tracked_count', 0)}",
            f"\u76ee\u524d\u5b58\u5728\uff1a{batch.get('existing_count', 0)}",
            f"\u5df2\u522a\u9664\uff1a{batch.get('missing_count', 0)}",
            f"\u7121\u6cd5\u78ba\u8a8d\uff1a{batch.get('unknown_count', 0)}",
            "",
            "\u8f38\u5165\u6458\u8981\uff1a",
            batch.get("input_summary") or "-",
            "",
            "\u7d50\u679c\u6458\u8981\uff1a",
            batch.get("result_summary") or "-",
        ]
        if batch.get("error_message"):
            lines.extend(["", "\u6279\u6b21\u932f\u8aa4\uff1a", str(batch.get("error_message"))])
        if requests:
            lines.extend(["", "Revit \u8acb\u6c42\uff1a"])
            for request in requests[:80]:
                lines.append(
                    f"- {request.get('action')} | {self._display_batch_status(request.get('status', ''))} | {request.get('request_id')}"
                )
                if request.get("error_message"):
                    lines.append(f"  \u932f\u8aa4\uff1a{request.get('error_message')}")
        if events:
            lines.extend(["", "\u4e8b\u4ef6\uff1a"])
            for event in events[:80]:
                lines.append(f"- {event.get('created_at')} | {event.get('level')} | {event.get('message')}")
        self._set_backstage_detail("\n".join(lines))

    def _open_backstage_runtime_folder(self) -> None:
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            os.startfile(str(DB_PATH.parent))
        except Exception as exc:
            messagebox.showerror("\u7121\u6cd5\u958b\u555f\u7d00\u9304\u8cc7\u6599\u593e", str(exc))

    def _export_selected_batch_xlsx(self) -> None:
        batch = self._selected_backstage_batch()
        if not batch:
            messagebox.showerror("\u7121\u6cd5\u532f\u51fa", "\u8acb\u5148\u9078\u64c7\u4e00\u500b\u6279\u6b21")
            return
        batch_id = str(batch.get("batch_id", ""))
        output_name = filedialog.asksaveasfilename(
            title="\u9078\u64c7\u6279\u6b21\u5831\u8868\u532f\u51fa\u4f4d\u7f6e",
            initialdir=str(DB_PATH.parent),
            initialfile=f"{batch_id}.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel \u5de5\u4f5c\u7c3f", "*.xlsx"), ("\u6240\u6709\u6a94\u6848", "*.*")],
        )
        if not output_name:
            return
        store = BatchStore()
        if str(batch.get("feature", "")) == "cad_points":
            try:
                export_cad_points_batch_report_xlsx(batch_id, output_name, store=store)
            except Exception as exc:
                messagebox.showerror("\u532f\u51fa\u5931\u6557", str(exc))
                return
            messagebox.showinfo("\u532f\u51fa\u5b8c\u6210", f"\u5df2\u532f\u51fa\uff1a\n{output_name}")
            return
        requests = store.list_requests(batch_id)
        events = store.list_events(batch_id)
        rows = [
            ["\u985e\u578b", "\u6642\u9593", "\u529f\u80fd/\u52d5\u4f5c", "\u72c0\u614b", "\u5167\u5bb9", "\u932f\u8aa4"],
            ["\u64cd\u4f5c\u8a18\u9304", batch.get("created_at", ""), self._display_feature_name(batch.get("feature", "")), self._display_batch_status(batch.get("status", "")), batch.get("title", ""), batch.get("error_message", "")],
        ]
        for request in requests:
            rows.append(["Revit \u8acb\u6c42", request.get("created_at", ""), request.get("action", ""), self._display_batch_status(request.get("status", "")), request.get("request_id", ""), request.get("error_message", "")])
        for event in events:
            rows.append(["\u4e8b\u4ef6", event.get("created_at", ""), event.get("level", ""), "", event.get("message", ""), event.get("detail", "")])
        try:
            write_xlsx(Path(output_name), "SC \u6279\u6b21\u5831\u8868", rows)
        except Exception as exc:
            messagebox.showerror("\u532f\u51fa\u5931\u6557", str(exc))
            return
        messagebox.showinfo("\u532f\u51fa\u5b8c\u6210", f"\u5df2\u532f\u51fa\uff1a\n{output_name}")

    def _sync_selected_batch_products(self, *, show_message: bool = True) -> dict | None:
        batch = self._selected_backstage_batch()
        if not batch:
            if show_message:
                messagebox.showerror("\u7121\u6cd5\u6aa2\u67e5", "\u8acb\u5148\u9078\u64c7\u4e00\u7b46\u5efa\u7acb\u7d00\u9304")
            return None
        batch_id = str(batch.get("batch_id", ""))
        try:
            payload = request_sync_tracked_elements(batch_id)
        except Exception as exc:
            if show_message:
                messagebox.showerror("\u6aa2\u67e5\u5931\u6557", str(exc))
            return None
        self._refresh_backstage_batches(select_batch_id=batch_id)
        if show_message:
            messagebox.showinfo(
                "\u6aa2\u67e5\u5b8c\u6210",
                f"\u5b58\u5728 {payload.get('existing_count', 0)}\uff5c\u5df2\u522a\u9664 {payload.get('missing_count', 0)}\uff5c\u7121\u6cd5\u78ba\u8a8d {payload.get('unknown_count', 0)}",
            )
        return payload

    def _delete_selected_batch_products(self) -> None:
        batch = self._selected_backstage_batch()
        if not batch:
            messagebox.showerror("\u7121\u6cd5\u522a\u9664", "\u8acb\u5148\u9078\u64c7\u4e00\u7b46\u5efa\u7acb\u7d00\u9304")
            return
        batch_id = str(batch.get("batch_id", ""))

        sync_payload = self._sync_selected_batch_products(show_message=False)
        if sync_payload is None:
            messagebox.showerror(
                "\u7121\u6cd5\u522a\u9664",
                "\u6a21\u578b\u72c0\u614b\u6aa2\u67e5\u5931\u6557\uff0c\u5df2\u505c\u6b62\u522a\u9664\u3002\n\u8acb\u78ba\u8a8d Revit \u6c92\u6709\u505c\u5728\u8b66\u544a\u8996\u7a97\u6216\u5c0d\u8a71\u6846\u3002",
            )
            return

        existing_before = int(sync_payload.get("existing_count", 0) or 0)
        excluded_before = int(sync_payload.get("unknown_count", 0) or 0)
        already_missing = int(sync_payload.get("missing_count", 0) or 0)
        if existing_before <= 0:
            self._refresh_backstage_batches(select_batch_id=batch_id)
            messagebox.showinfo(
                "\u6c92\u6709\u53ef\u522a\u9664\u5143\u4ef6",
                f"\u9019\u7b46\u5efa\u7acb\u7d00\u9304\u76ee\u524d\u6c92\u6709\u53ef\u522a\u9664\u7684 Revit \u5143\u4ef6\u3002\n\u6a21\u578b\u4e2d\u5df2\u4e0d\u5b58\u5728\uff1a{already_missing}\n\u7121\u6cd5\u78ba\u8a8d\uff1a{excluded_before}",
            )
            return

        try:
            payload = request_delete_tracked_elements(batch_id)
        except Exception as exc:
            self._refresh_backstage_batches(select_batch_id=batch_id)
            messagebox.showerror("\u522a\u9664\u5931\u6557", str(exc))
            return

        sync_after = None
        sync_after_error = None
        try:
            sync_after = request_sync_tracked_elements(batch_id)
        except Exception as exc:
            sync_after_error = str(exc)

        self._refresh_backstage_batches(select_batch_id=batch_id)

        deleted_count = int(payload.get("deleted_count", 0) or 0)
        failed_items = payload.get("failed", []) or []
        failed_count = len(failed_items) if isinstance(failed_items, list) else 0
        ungrouped_count = len(payload.get("ungrouped_group_ids", []) or [])
        remaining_count = int(sync_after.get("existing_count", 0) or 0) if sync_after else None
        unknown_after = int(sync_after.get("unknown_count", 0) or 0) if sync_after else excluded_before

        lines = [
            "\u522a\u9664\u6d41\u7a0b\u5b8c\u6210\u3002",
            f"\u522a\u9664\u524d\u53ef\u7ba1\u7406\u5143\u4ef6\uff1a{existing_before}",
            f"\u5df2\u522a\u9664\uff1a{deleted_count}",
            f"\u5df2\u5148\u89e3\u9664 SC \u7fa4\u7d44\uff1a{ungrouped_count}",
        ]
        if remaining_count is not None:
            lines.append(f"\u522a\u9664\u5f8c\u4ecd\u5b58\u5728\uff1a{remaining_count}")
        else:
            lines.append("\u522a\u9664\u5f8c\u672a\u80fd\u518d\u6aa2\u67e5\u6a21\u578b\u72c0\u614b")
        if unknown_after:
            lines.append(f"\u5df2\u6392\u9664\u7121\u6cd5\u78ba\u8a8d\u6216\u53d7\u4fdd\u8b77\u5143\u4ef6\uff1a{unknown_after}")
        if failed_count:
            lines.append(f"\u522a\u9664\u5931\u6557\uff1a{failed_count}")
        if sync_after_error:
            lines.append("")
            lines.append("\u6ce8\u610f\uff1a\u522a\u9664\u5f8c\u518d\u6aa2\u67e5\u5931\u6557\uff0c\u5f8c\u53f0\u6703\u4fdd\u7559\u5df2\u56de\u5831\u7684\u522a\u9664\u7d50\u679c\u3002")
            lines.append(sync_after_error)

        if failed_count or sync_after_error or (remaining_count is not None and remaining_count > 0):
            messagebox.showwarning("\u522a\u9664\u5b8c\u6210\uff0c\u4f46\u9700\u8981\u6ce8\u610f", "\n".join(lines))
        else:
            messagebox.showinfo("\u522a\u9664\u5b8c\u6210", "\n".join(lines))

    def _clear_tree(self, tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _tool_text(self, code: str | None) -> str:
        texts = {
            "trackable": "\u53ef\u8ffd\u8e64",
            "revit_identity_only": "\u53ea\u6709 Revit \u8eab\u4efd",
            "sync_or_report": "\u53ef\u540c\u6b65 / \u5831\u8868",
            "reference_only": "\u50c5\u53ef\u53c3\u8003",
            "none": "\u7121",
            "missing_sc_parameters": "\u7f3a\u5c11 SC_ \u8ffd\u8e64\u53c3\u6578",
            "can_sync_or_report": "\u53ef\u540c\u6b65\u6216\u5831\u8868\u56de\u67e5",
            "add_tracking_parameters_before_management": "\u8981\u7d0d\u5165\u5f8c\u53f0\u7ba1\u7406\u6642\uff0c\u5148\u88dc\u8ffd\u8e64\u53c3\u6578",
            "not_managed": "\u672a\u7d0d\u7ba1",
            "missing_required": "\u7f3a\u5fc5\u8981\u53c3\u6578",
            "empty_values": "\u6709\u7a7a\u503c",
            "pass": "\u901a\u904e",
            "add_tracking_parameters_if_needed": "\u9700\u8981\u7d0d\u7ba1\u6642\u518d\u88dc\u8ffd\u8e64\u53c3\u6578",
            "add_missing_parameters": "\u5148\u88dc\u9f4a\u7f3a\u5c11\u53c3\u6578",
            "fill_empty_values": "\u88dc\u4e0a\u7a7a\u503c\u5f8c\u518d\u56de\u67e5",
            "no_action": "\u4e0d\u9700\u8655\u7406",
            "normal": "\u6b63\u5e38",
            "no_connectors": "\u7121\u53ef\u6aa2\u67e5\u63a5\u982d",
            "has_pipe_break": "\u7ba1\u7dda\u6709\u65b7\u9ede",
            "diagnostic_only": "\u50c5\u8a3a\u65b7",
            "repairable": "\u53ef\u4fee\u5fa9",
            "too_far": "\u8ddd\u96e2\u904e\u9060",
            "failed": "\u4fee\u5fa9\u5931\u6557",
            "repaired": "\u5df2\u4fee\u5fa9",
            "all_connected": "\u7aef\u9ede\u90fd\u5df2\u9023\u63a5",
            "element_has_no_connectors": "\u9019\u985e\u5143\u4ef6\u6c92\u6709\u53ef\u6aa2\u67e5\u7684\u63a5\u982d",
            "pipe_has_open_connectors": "pipe \u6709\u672a\u9023\u63a5\u7aef\u9ede",
            "non_pipe_has_open_connectors": "\u975e pipe \u5143\u4ef6\u6709\u672a\u9023\u63a5\u7aef\u9ede",
            "pipe_pair_within_threshold": "\u5169\u500b pipe \u7aef\u9ede\u5728\u4fee\u5fa9\u9580\u6abb\u5167",
            "pipe_pair_over_threshold": "\u5169\u500b pipe \u7aef\u9ede\u8d85\u904e\u4fee\u5fa9\u9580\u6abb",
            "non_pipe_pair": "\u4e0d\u662f pipe \u5c0d pipe\uff0c\u4e0d\u81ea\u52d5\u4fee\u5fa9",
            "fitting_create_failed": "Revit \u7121\u6cd5\u5efa\u7acb\u63a5\u982d",
            "skip_or_select_mep_curve": "\u7565\u904e\uff0c\u6216\u6539\u9078 pipe / duct / conduit",
            "review_repairable_pairs": "\u67e5\u770b\u4e0b\u65b9\u5019\u9078\u914d\u5c0d",
            "manual_repair_only": "\u5148\u4eba\u5de5\u8655\u7406",
            "can_auto_repair_pipe": "\u53ef\u6309\u300c\u53ea\u4fee\u5fa9\u53ef\u4fee\u5fa9\u7684 pipe \u65b7\u9ede\u300d",
            "check_selection_or_adjust_manually": "\u6aa2\u67e5\u662f\u5426\u9078\u932f\u7bc4\u570d\uff0c\u6216\u624b\u52d5\u8abf\u6574\u5f8c\u91cd\u8a66",
            "manual_adjust_then_retry": "\u624b\u52d5\u8abf\u6574\u4f4d\u7f6e / \u9ad8\u7a0b\u5f8c\u518d\u91cd\u8a66",
        }
        return texts.get(code or "", code or "")

    def _add_tool_intro(self, parent: ttk.Frame, title: str, body: str, steps: str) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, font=("Microsoft JhengHei UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=body, wraplength=980).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(frame, text=steps, wraplength=980).grid(row=2, column=0, sticky="w", pady=(2, 0))

    def _build_element_inspector_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        self._add_tool_intro(
            parent,
            "\u5143\u4ef6\u8eab\u4efd\u6aa2\u67e5",
            "\u7528\u4f86\u5224\u65b7\u9078\u53d6\u5143\u4ef6\u80fd\u4e0d\u80fd\u88ab SC \u5f8c\u53f0\u8ffd\u8e64\u3001\u5831\u8868\u56de\u67e5\u6216\u5f8c\u7e8c\u540c\u6b65\u7ba1\u7406\u3002",
            "1. \u5728 Revit \u9078\u53d6\u5143\u4ef6\u30002. \u6309\u300c\u6aa2\u67e5\u9078\u53d6\u5143\u4ef6\u300d\u30003. \u770b\u72c0\u614b\u3001\u554f\u984c\u548c\u5efa\u8b70\u8655\u7f6e\u3002",
        )
        header = ttk.Frame(parent)
        header.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(header, text="\u6aa2\u67e5\u9078\u53d6\u5143\u4ef6", command=self._load_element_inspection).pack(side="left")
        self.element_inspector_status_var = tk.StringVar(value="\u5c1a\u672a\u8b80\u53d6")
        ttk.Label(header, textvariable=self.element_inspector_status_var).pack(side="left", padx=(12, 0))

        columns = ("status", "element_id", "category", "name", "management", "issue", "recommendation")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=20)
        headings = {
            "status": "\u72c0\u614b",
            "element_id": "ElementId",
            "category": "\u985e\u5225",
            "name": "\u540d\u7a31",
            "management": "\u5f8c\u53f0\u7ba1\u7406",
            "issue": "\u554f\u984c",
            "recommendation": "\u5efa\u8b70\u8655\u7f6e",
        }
        widths = {"status": 110, "element_id": 90, "category": 130, "name": 190, "management": 130, "issue": 210, "recommendation": 290}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")
        tree.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self.element_inspector_tree = tree

    def _load_element_inspection(self) -> None:
        self.element_inspector_status_var.set("\u8b80\u53d6 Revit \u9078\u53d6\u4e2d\u2026")
        threading.Thread(target=self._load_element_inspection_worker, daemon=True).start()

    def _load_element_inspection_worker(self) -> None:
        try:
            with batch_context("element_inspector", "inspect_selected", "Inspect selected elements"):
                payload = request_inspect_selected_elements()
        except Exception as exc:
            self.after(0, lambda: self._finish_mep_tool_error("element_inspector", exc))
            return
        self.after(0, lambda: self._finish_element_inspection(payload))

    def _finish_element_inspection(self, payload: dict) -> None:
        self._clear_tree(self.element_inspector_tree)
        for element in payload.get("elements", []):
            self.element_inspector_tree.insert(
                "",
                "end",
                values=(
                    self._tool_text(element.get("status_code")),
                    element.get("element_id", ""),
                    element.get("category", ""),
                    element.get("name", ""),
                    self._tool_text(element.get("management_code")),
                    self._tool_text(element.get("issue_code")),
                    self._tool_text(element.get("recommendation_code")),
                ),
            )
        problem_count = sum(1 for element in payload.get("elements", []) if element.get("status_code") != "trackable")
        self.element_inspector_status_var.set(
            f"\u5df2\u6aa2\u67e5 {payload.get('selected_count', 0)} \u500b\u5143\u4ef6\uff0c{problem_count} \u500b\u9700\u6ce8\u610f"
        )

    def _build_parameter_audit_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        self._add_tool_intro(
            parent,
            "SC \u53c3\u6578\u5065\u6aa2",
            "\u7528\u4f86\u6aa2\u67e5\u9078\u53d6\u6216\u76ee\u524d\u8996\u5716\u7684\u5143\u4ef6\u662f\u5426\u5df2\u5177\u5099 SC_ \u8ffd\u8e64\u53c3\u6578\uff0c\u4ee5\u5224\u65b7\u80fd\u4e0d\u80fd\u9032\u5165\u5f8c\u53f0\u7ba1\u7406\u3002",
            "1. \u9078\u64c7\u7bc4\u570d\u30002. \u78ba\u8a8d\u524d\u7db4\u6216\u8f38\u5165\u9810\u671f\u53c3\u6578\u30003. \u6309\u6383\u63cf\u5f8c\u67e5\u770b\u7f3a\u5c11\u3001\u7a7a\u503c\u8207\u5efa\u8b70\u3002",
        )
        header = ttk.Frame(parent)
        header.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(header, text="\u7bc4\u570d").pack(side="left")
        self.parameter_audit_scope_var = tk.StringVar(value="selection")
        ttk.Combobox(
            header,
            textvariable=self.parameter_audit_scope_var,
            values=["selection", "active_view"],
            state="readonly",
            width=14,
        ).pack(side="left", padx=(6, 12))
        ttk.Label(header, text="\u524d\u7db4").pack(side="left")
        self.parameter_audit_prefix_var = tk.StringVar(value="SC_")
        ttk.Entry(header, textvariable=self.parameter_audit_prefix_var, width=10).pack(side="left", padx=(6, 12))
        ttk.Label(header, text="\u9810\u671f\u53c3\u6578").pack(side="left")
        self.parameter_audit_expected_var = tk.StringVar(value="")
        ttk.Entry(header, textvariable=self.parameter_audit_expected_var, width=28).pack(side="left", padx=(6, 12))
        ttk.Button(header, text="\u6383\u63cf", command=self._scan_sc_parameters).pack(side="left")
        self.parameter_audit_status_var = tk.StringVar(value="\u5c1a\u672a\u6383\u63cf")
        ttk.Label(header, textvariable=self.parameter_audit_status_var).pack(side="left", padx=(12, 0))

        columns = ("status", "element_id", "category", "name", "missing", "empty", "recommendation")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=20)
        headings = {
            "status": "\u72c0\u614b",
            "element_id": "ElementId",
            "category": "\u985e\u5225",
            "name": "\u540d\u7a31",
            "missing": "\u7f3a\u5c11\u53c3\u6578",
            "empty": "\u7a7a\u503c\u53c3\u6578",
            "recommendation": "\u5efa\u8b70\u8655\u7f6e",
        }
        widths = {"status": 110, "element_id": 90, "category": 130, "name": 190, "missing": 220, "empty": 180, "recommendation": 300}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")
        tree.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self.parameter_audit_tree = tree

    def _scan_sc_parameters(self) -> None:
        self.parameter_audit_status_var.set("\u6383\u63cf\u4e2d\u2026")
        threading.Thread(target=self._scan_sc_parameters_worker, daemon=True).start()

    def _scan_sc_parameters_worker(self) -> None:
        expected = [
            item.strip()
            for item in self.parameter_audit_expected_var.get().split(",")
            if item.strip()
        ]
        try:
            with batch_context(
                "parameter_audit",
                "scan_sc_parameters",
                "Scan SC parameters",
                {"scope": self.parameter_audit_scope_var.get(), "prefix": self.parameter_audit_prefix_var.get()},
            ):
                payload = request_scan_sc_parameters(
                    scope=self.parameter_audit_scope_var.get(),
                    parameter_prefix=self.parameter_audit_prefix_var.get() or "SC_",
                    expected_parameters=expected,
                )
        except Exception as exc:
            self.after(0, lambda: self._finish_mep_tool_error("parameter_audit", exc))
            return
        self.after(0, lambda: self._finish_parameter_audit(payload))

    def _finish_parameter_audit(self, payload: dict) -> None:
        self._clear_tree(self.parameter_audit_tree)
        for element in payload.get("elements", []):
            self.parameter_audit_tree.insert(
                "",
                "end",
                values=(
                    self._tool_text(element.get("status_code")),
                    element.get("element_id", ""),
                    element.get("category", ""),
                    element.get("name", ""),
                    ", ".join(element.get("missing_parameters", [])) or "-",
                    ", ".join(element.get("empty_parameters", [])) or "-",
                    self._tool_text(element.get("recommendation_code")),
                ),
            )
        problem_count = sum(1 for element in payload.get("elements", []) if element.get("status_code") != "pass")
        self.parameter_audit_status_var.set(
            f"\u5df2\u6383\u63cf {payload.get('scanned_count', 0)} \u500b\u5143\u4ef6\uff0c{problem_count} \u500b\u9700\u8655\u7406"
        )

    def _build_connect_fitting_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        self._add_tool_intro(
            parent,
            "\u7ba1\u7dda\u65b7\u9ede\u6aa2\u67e5",
            "\u7528\u4f86\u627e\u51fa\u9078\u53d6\u7bc4\u570d\u5167\u6c92\u6709\u9023\u63a5\u7684\u7ba1\u7dda\u7aef\u9ede\uff0c\u4e26\u5224\u65b7\u54ea\u4e9b pipe \u65b7\u9ede\u53ef\u4ee5\u81ea\u52d5\u4fee\u5fa9\u3002duct / conduit \u53ea\u505a\u8a3a\u65b7\uff0c\u4e0d\u81ea\u52d5\u4fee\u6539\u6a21\u578b\u3002",
            "1. \u9078\u53d6 pipe / duct / conduit \u6216\u76f8\u95dc\u63a5\u982d\u30002. \u6309\u300c\u6aa2\u67e5\u65b7\u9ede\u300d\u30003. \u53ea\u5c0d\u72c0\u614b\u70ba\u53ef\u4fee\u5fa9\u7684 pipe \u57f7\u884c\u81ea\u52d5\u4fee\u5fa9\u3002",
        )
        header = ttk.Frame(parent)
        header.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(header, text="\u6aa2\u67e5\u65b7\u9ede", command=self._diagnose_mep_connectors).pack(side="left")
        ttk.Label(header, text="\u4fee\u5fa9\u9580\u6abb(mm)").pack(side="left", padx=(12, 4))
        self.connect_fitting_distance_var = tk.StringVar(value="50")
        ttk.Entry(header, textvariable=self.connect_fitting_distance_var, width=8).pack(side="left")
        ttk.Button(header, text="\u53ea\u4fee\u5fa9\u53ef\u4fee\u5fa9\u7684 pipe \u65b7\u9ede", command=self._connect_pipe_fittings).pack(side="left", padx=(8, 0))
        self.connect_fitting_status_var = tk.StringVar(value="\u5c1a\u672a\u8a3a\u65b7")
        ttk.Label(header, textvariable=self.connect_fitting_status_var).pack(side="left", padx=(12, 0))

        columns = ("status", "element_a", "element_b", "distance", "reason", "recommendation")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=20)
        headings = {
            "status": "\u72c0\u614b",
            "element_a": "\u5143\u4ef6 A",
            "element_b": "\u5143\u4ef6 B",
            "distance": "\u8ddd\u96e2",
            "reason": "\u539f\u56e0",
            "recommendation": "\u5efa\u8b70\u8655\u7f6e",
        }
        widths = {"status": 110, "element_a": 180, "element_b": 180, "distance": 90, "reason": 260, "recommendation": 320}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")
        tree.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self.connect_fitting_tree = tree

    def _diagnose_mep_connectors(self) -> None:
        try:
            max_distance_mm = float(self.connect_fitting_distance_var.get() or 50)
        except ValueError:
            messagebox.showerror("\u8f38\u5165\u932f\u8aa4", "\u4fee\u5fa9\u9580\u6abb\u5fc5\u9808\u662f\u6578\u5b57")
            return
        self.connect_fitting_status_var.set("\u6aa2\u67e5\u65b7\u9ede\u4e2d\u2026")
        threading.Thread(target=self._diagnose_mep_connectors_worker, args=(max_distance_mm,), daemon=True).start()

    def _diagnose_mep_connectors_worker(self, max_distance_mm: float) -> None:
        try:
            with batch_context(
                "connect_fitting",
                "diagnose_mep_connectors",
                "Diagnose MEP connectors",
                {"max_distance_mm": max_distance_mm},
            ):
                payload = request_diagnose_mep_connectors(max_distance_mm=max_distance_mm)
        except Exception as exc:
            self.after(0, lambda: self._finish_mep_tool_error("connect_fitting", exc))
            return
        self.after(0, lambda: self._finish_connector_diagnosis(payload))

    def _finish_connector_diagnosis(self, payload: dict) -> None:
        self._clear_tree(self.connect_fitting_tree)
        for element in payload.get("elements", []):
            self.connect_fitting_tree.insert(
                "",
                "end",
                values=(
                    self._tool_text(element.get("status_code")),
                    f"{element.get('element_id', '')} {element.get('name', '')}",
                    "",
                    "",
                    self._tool_text(element.get("reason_code")),
                    self._tool_text(element.get("recommendation_code")),
                ),
            )
        for pair in payload.get("nearest_open_pairs", []):
            self.connect_fitting_tree.insert(
                "",
                "end",
                values=(
                    self._tool_text(pair.get("status_code")),
                    pair.get("a_element_id", ""),
                    pair.get("b_element_id", ""),
                    f"{pair.get('distance_mm', '')} mm",
                    self._tool_text(pair.get("reason_code")),
                    self._tool_text(pair.get("recommendation_code")),
                ),
            )
        repairable_count = sum(1 for pair in payload.get("nearest_open_pairs", []) if pair.get("status_code") == "repairable")
        issue_count = sum(1 for element in payload.get("elements", []) if element.get("status_code") not in ("normal", "no_connectors"))
        self.connect_fitting_status_var.set(
            f"\u5df2\u6aa2\u67e5 {payload.get('selected_count', 0)} \u500b MEP \u5143\u4ef6\uff0c{issue_count} \u500b\u6709\u65b7\u9ede\uff0c{repairable_count} \u7d44\u53ef\u4fee\u5fa9"
        )

    def _connect_pipe_fittings(self) -> None:
        try:
            max_distance_mm = float(self.connect_fitting_distance_var.get() or 50)
        except ValueError:
            messagebox.showerror("\u8f38\u5165\u932f\u8aa4", "\u4fee\u5fa9\u9580\u6abb\u5fc5\u9808\u662f\u6578\u5b57")
            return
        self.connect_fitting_status_var.set("pipe \u81ea\u52d5\u4fee\u5fa9\u4e2d\u2026")
        threading.Thread(target=self._connect_pipe_fittings_worker, args=(max_distance_mm,), daemon=True).start()

    def _connect_pipe_fittings_worker(self, max_distance_mm: float) -> None:
        try:
            with batch_context(
                "connect_fitting",
                "connect_pipe_fittings",
                "Connect pipe fittings",
                {"max_distance_mm": max_distance_mm},
            ):
                payload = request_connect_pipe_fittings(max_distance_mm=max_distance_mm)
        except Exception as exc:
            self.after(0, lambda: self._finish_mep_tool_error("connect_fitting", exc))
            return
        self.after(0, lambda: self._finish_pipe_connection(payload))

    def _finish_pipe_connection(self, payload: dict) -> None:
        self._clear_tree(self.connect_fitting_tree)
        for pair in payload.get("connected", []):
            self.connect_fitting_tree.insert(
                "",
                "end",
                values=(
                    self._tool_text("repaired"),
                    pair.get("a_element_id", ""),
                    pair.get("b_element_id", ""),
                    f"{pair.get('distance_mm', '')} mm",
                    self._tool_text(pair.get("reason_code")),
                    self._tool_text("no_action"),
                ),
            )
        for item in payload.get("failed", []):
            self.connect_fitting_tree.insert(
                "",
                "end",
                values=(
                    self._tool_text("failed"),
                    item.get("a_element_id", ""),
                    item.get("b_element_id", ""),
                    f"{item.get('distance_mm', '')} mm",
                    item.get("error", "") or self._tool_text(item.get("reason_code")),
                    self._tool_text(item.get("recommendation_code")),
                ),
            )
        self.connect_fitting_status_var.set(
            f"\u5df2\u4fee\u5fa9 {payload.get('connected_count', 0)} \u7d44\uff0c\u5931\u6557 {payload.get('failed_count', 0)} \u7d44"
        )

    def _build_piping_support_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.piping_support_spacing_var = tk.StringVar(value="150")
        self.piping_support_start_var = tk.StringVar(value="30")
        self.piping_support_end_var = tk.StringVar(value="30")
        self.piping_support_size_var = tk.StringVar(value="10")
        self.piping_support_family_var = tk.StringVar(value="")
        self.piping_support_type_var = tk.StringVar(value="")
        for label, var, width in [
            ("\u9593\u8ddd(cm)", self.piping_support_spacing_var, 8),
            ("\u8d77\u9ede(cm)", self.piping_support_start_var, 8),
            ("\u7d42\u9ede(cm)", self.piping_support_end_var, 8),
            ("\u6a19\u8a18(cm)", self.piping_support_size_var, 8),
            ("\u65cf\u7fa4ID", self.piping_support_family_var, 10),
            ("\u985e\u578bID", self.piping_support_type_var, 10),
        ]:
            ttk.Label(header, text=label).pack(side="left")
            ttk.Entry(header, textvariable=var, width=width).pack(side="left", padx=(4, 8))
        ttk.Button(header, text="\u7522\u751f\u5019\u9078\u9ede\u9810\u89bd", command=self._preview_piping_support_points).pack(side="left")
        self.piping_support_status_var = tk.StringVar(value="\u5c1a\u672a\u9810\u89bd")
        ttk.Label(header, textvariable=self.piping_support_status_var).pack(side="left", padx=(12, 0))

        columns = ("pipe_id", "index", "distance_cm", "x", "y", "z")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=20)
        headings = {"pipe_id": "PipeId", "index": "#", "distance_cm": "\u8ddd\u96e2(cm)", "x": "X", "y": "Y", "z": "Z"}
        widths = {"pipe_id": 90, "index": 60, "distance_cm": 100, "x": 120, "y": 120, "z": 120}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")
        tree.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self.piping_support_tree = tree

    def _preview_piping_support_points(self) -> None:
        try:
            spacing_cm = float(self.piping_support_spacing_var.get() or 150)
            start_offset_cm = float(self.piping_support_start_var.get() or 30)
            end_offset_cm = float(self.piping_support_end_var.get() or 30)
            marker_size_cm = float(self.piping_support_size_var.get() or 10)
        except ValueError:
            messagebox.showerror("\u8f38\u5165\u932f\u8aa4", "\u9593\u8ddd\u8207\u504f\u79fb\u5fc5\u9808\u662f\u6578\u5b57")
            return
        self.piping_support_status_var.set("\u7522\u751f\u9810\u89bd\u4e2d\u2026")
        threading.Thread(
            target=self._preview_piping_support_points_worker,
            args=(spacing_cm, start_offset_cm, end_offset_cm, marker_size_cm),
            daemon=True,
        ).start()

    def _preview_piping_support_points_worker(
        self,
        spacing_cm: float,
        start_offset_cm: float,
        end_offset_cm: float,
        marker_size_cm: float,
    ) -> None:
        try:
            with batch_context(
                "piping_support",
                "preview_piping_support_points",
                "Preview piping support points",
                {"spacing_cm": spacing_cm, "start_offset_cm": start_offset_cm, "end_offset_cm": end_offset_cm},
            ):
                payload = request_preview_piping_support_points(
                    spacing_cm=spacing_cm,
                    start_offset_cm=start_offset_cm,
                    end_offset_cm=end_offset_cm,
                    marker_size_cm=marker_size_cm,
                    support_family_id=self.piping_support_family_var.get() or None,
                    support_type_id=self.piping_support_type_var.get() or None,
                )
        except Exception as exc:
            self.after(0, lambda: self._finish_mep_tool_error("piping_support", exc))
            return
        self.after(0, lambda: self._finish_piping_support_preview(payload))

    def _finish_piping_support_preview(self, payload: dict) -> None:
        self._clear_tree(self.piping_support_tree)
        for point in payload.get("points", []):
            xyz = point.get("point") or {}
            self.piping_support_tree.insert(
                "",
                "end",
                values=(
                    point.get("pipe_id", ""),
                    point.get("index", ""),
                    point.get("distance_cm", ""),
                    xyz.get("x", ""),
                    xyz.get("y", ""),
                    xyz.get("z", ""),
                ),
            )
        self.piping_support_status_var.set(
            f"\u5df2\u7522\u751f {payload.get('point_count', 0)} \u500b\u5019\u9078\u9ede\uff5cGroup {payload.get('group_id', 0)}"
        )

    def _finish_mep_tool_error(self, tool_name: str, exc: Exception) -> None:
        if tool_name == "element_inspector":
            self.element_inspector_status_var.set("\u8b80\u53d6\u5931\u6557")
        elif tool_name == "parameter_audit":
            self.parameter_audit_status_var.set("\u6383\u63cf\u5931\u6557")
        elif tool_name == "connect_fitting":
            self.connect_fitting_status_var.set("\u57f7\u884c\u5931\u6557")
        elif tool_name == "piping_support":
            self.piping_support_status_var.set("\u9810\u89bd\u5931\u6557")
        messagebox.showerror("\u57f7\u884c\u5931\u6557", str(exc))

    def _build_opening_check_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        header = ttk.LabelFrame(parent, text="1. 讀取土建 Link", padding=10)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(1, weight=1)
        ttk.Button(
            header,
            text="讀取目前專案",
            command=self._load_opening_context,
        ).grid(row=0, column=0, sticky="w")
        self.opening_status_var = tk.StringVar(value="尚未讀取")
        ttk.Label(header, textvariable=self.opening_status_var).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(12, 0),
        )

        settings = ttk.LabelFrame(parent, text="2. 掃描設定", padding=10)
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="土建 Link").grid(row=0, column=0, sticky="w")
        self.opening_link_var = tk.StringVar()
        self.opening_link_combo = ttk.Combobox(
            settings,
            textvariable=self.opening_link_var,
            state="readonly",
            width=60,
        )
        self.opening_link_combo.grid(row=0, column=1, sticky="ew", padx=(8, 12))

        self.opening_mep_vars = {
            "pipe": tk.BooleanVar(value=True),
            "conduit": tk.BooleanVar(value=True),
            "duct": tk.BooleanVar(value=True),
            "cable_tray": tk.BooleanVar(value=True),
        }
        mep_frame = ttk.Frame(settings)
        mep_frame.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Label(settings, text="MEP 類型").grid(row=1, column=0, sticky="w", pady=(10, 0))
        for index, (key, label) in enumerate(
            [
                ("pipe", "管"),
                ("conduit", "電管"),
                ("duct", "風管"),
                ("cable_tray", "電纜架"),
            ]
        ):
            ttk.Checkbutton(
                mep_frame,
                text=label,
                variable=self.opening_mep_vars[key],
            ).grid(row=0, column=index, sticky="w", padx=(0, 14))

        self.opening_host_vars = {
            "wall": tk.BooleanVar(value=True),
            "floor": tk.BooleanVar(value=True),
            "beam": tk.BooleanVar(value=True),
            "column": tk.BooleanVar(value=True),
        }
        host_frame = ttk.Frame(settings)
        host_frame.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Label(settings, text="土建構件").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Checkbutton(host_frame, text="牆", variable=self.opening_host_vars["wall"]).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Checkbutton(host_frame, text="樓板", variable=self.opening_host_vars["floor"]).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(host_frame, text="梁", variable=self.opening_host_vars["beam"]).grid(row=0, column=2, sticky="w", padx=(14, 14))
        ttk.Checkbutton(host_frame, text="柱", variable=self.opening_host_vars["column"]).grid(row=0, column=3, sticky="w")

        ttk.Label(settings, text="開孔放大值(mm)").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.opening_clearance_var = tk.StringVar(value="50")
        ttk.Entry(settings, textvariable=self.opening_clearance_var, width=12).grid(
            row=3,
            column=1,
            sticky="w",
            padx=(8, 0),
            pady=(10, 0),
        )

        ttk.Label(settings, text="標註形式").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.opening_dimension_type_var = tk.StringVar(value="依專案預設")
        self.opening_dimension_type_combo = ttk.Combobox(
            settings,
            textvariable=self.opening_dimension_type_var,
            state="readonly",
            width=40,
        )
        self.opening_dimension_type_combo.grid(row=4, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        self.opening_dimension_type_combo.configure(values=["依專案預設"])

        actions = ttk.Frame(parent)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(actions, text="掃描開孔候選", command=self._scan_opening_candidates).pack(side="left")
        ttk.Button(actions, text="3D檢視選取開孔", command=self._view_selected_opening_candidate).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="建立平面標記", command=self._place_opening_markers).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="匯出 XLSX", command=self._export_opening_candidates).pack(side="left", padx=(8, 0))
        ttk.Label(
            actions,
            text="第一版只產生清單，不放標記、不切牆/樓板。",
            foreground="#666666",
        ).pack(side="left", padx=(12, 0))

        result_frame = ttk.LabelFrame(parent, text="3. 開孔候選清單", padding=10)
        result_frame.grid(row=3, column=0, sticky="nsew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        self.opening_tree = ttk.Treeview(
            result_frame,
            columns=(
                "index",
                "opening_id",
                "status",
                "dimension_status",
                "dimension_ref",
                "dimension_distance",
                "center_source",
                "system",
                "mep_type",
                "mep_id",
                "host_type",
                "host_id",
                "level",
                "shape",
                "size",
                "note",
            ),
            show="headings",
            selectmode="browse",
        )
        headings = {
            "index": "序號",
            "opening_id": "開孔編號",
            "status": "狀態",
            "dimension_status": "標註",
            "dimension_ref": "標註基準",
            "dimension_distance": "標註距離(cm)",
            "center_source": "中心來源",
            "system": "系統",
            "mep_type": "MEP 類型",
            "mep_id": "MEP 元素ID",
            "host_type": "土建構件",
            "host_id": "Link構件ID",
            "level": "樓層",
            "shape": "孔型",
            "size": "開孔尺寸",
            "note": "備註",
        }
        widths = {
            "index": 60,
            "opening_id": 190,
            "status": 90,
            "dimension_status": 90,
            "dimension_ref": 150,
            "dimension_distance": 110,
            "center_source": 160,
            "system": 90,
            "mep_type": 100,
            "mep_id": 100,
            "host_type": 90,
            "host_id": 110,
            "level": 120,
            "shape": 80,
            "size": 150,
            "note": 260,
        }
        for column, title in headings.items():
            self.opening_tree.heading(column, text=title)
            self.opening_tree.column(column, width=widths[column], anchor="center" if column != "note" else "w")
        self.opening_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.opening_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.opening_tree.configure(yscrollcommand=scrollbar.set)
        self.opening_tree.tag_configure("normal", background="#e8f5e9")
        self.opening_tree.tag_configure("review", background="#fff8e1")
        self.opening_tree.tag_configure("ignore", background="#f5f5f5")
        self.opening_link_items = {}
        self.opening_dimension_type_items = {}
        self.opening_scan_result = None
        self.opening_candidates_by_iid = {}

    def _load_opening_context(self) -> None:
        self.opening_status_var.set("讀取 Link 中…")
        threading.Thread(target=self._load_opening_context_worker, daemon=True).start()

    def _load_opening_context_worker(self) -> None:
        try:
            with batch_context("openings", "list_context", "Opening context"):
                payload = request_opening_context()
        except Exception as exc:
            self.after(0, lambda: self._finish_opening_error("讀取開孔資料失敗", exc))
            return
        self.after(0, lambda: self._finish_opening_context(payload))

    def _finish_opening_context(self, payload: dict) -> None:
        links = list(payload.get("links", []))
        self.opening_link_items = {
            str(item.get("display_name", "")): item
            for item in links
            if item.get("display_name")
        }
        self.opening_link_combo.configure(values=list(self.opening_link_items.keys()))
        if self.opening_link_items:
            self.opening_link_combo.current(0)
        dimension_types = list(payload.get("dimension_types", []))
        self.opening_dimension_type_items = {
            str(item.get("display_name", "")): item
            for item in dimension_types
            if item.get("display_name")
        }
        dimension_values = ["依專案預設"] + list(self.opening_dimension_type_items.keys())
        if hasattr(self, "opening_dimension_type_combo"):
            self.opening_dimension_type_combo.configure(values=dimension_values)
            self.opening_dimension_type_var.set(dimension_values[0])
        self.opening_status_var.set(
            f"已讀取｜Link {len(links)}｜Pipe {payload.get('pipe_count', 0)}｜Conduit {payload.get('conduit_count', 0)}｜Duct {payload.get('duct_count', 0)}｜CableTray {payload.get('cable_tray_count', 0)}"
        )

    def _scan_opening_candidates(self) -> None:
        link = self.opening_link_items.get(self.opening_link_var.get())
        if not link:
            messagebox.showerror("無法掃描", "請先讀取目前專案並選擇土建 Link")
            return
        mep_types = [key for key, var in self.opening_mep_vars.items() if var.get()]
        host_types = [key for key, var in self.opening_host_vars.items() if var.get()]
        if not mep_types:
            messagebox.showerror("無法掃描", "請至少選擇一種 MEP 類型")
            return
        if not host_types:
            messagebox.showerror("無法掃描", "請至少選擇一種土建構件")
            return
        try:
            clearance_mm = float(self.opening_clearance_var.get() or 0)
        except ValueError:
            messagebox.showerror("無法掃描", "開孔放大值必須是數字，單位為 mm")
            return
        for item in self.opening_tree.get_children():
            self.opening_tree.delete(item)
        self.opening_status_var.set("掃描開孔候選中…")
        threading.Thread(
            target=self._scan_opening_candidates_worker,
            args=(link, mep_types, host_types, clearance_mm),
            daemon=True,
        ).start()

    def _scan_opening_candidates_worker(
        self,
        link: dict,
        mep_types: list[str],
        host_types: list[str],
        clearance_mm: float,
    ) -> None:
        try:
            with batch_context("openings", "scan_candidates", "Scan opening candidates", {"mep_types": mep_types, "host_types": host_types, "clearance_mm": clearance_mm}):
                payload = request_scan_opening_candidates(
                    link_id=link.get("element_id"),
                    mep_types=mep_types,
                    host_types=host_types,
                    clearance_mm=clearance_mm,
                )
        except Exception as exc:
            self.after(0, lambda: self._finish_opening_error("開孔掃描失敗", exc))
            return
        self.after(0, lambda: self._finish_opening_scan(payload))

    def _finish_opening_scan(self, payload: dict) -> None:
        self.opening_scan_result = payload
        candidates = list(payload.get("candidates", []))
        payload["candidates"] = candidates
        for item in self.opening_tree.get_children():
            self.opening_tree.delete(item)
        self.opening_candidates_by_iid = {}
        for index, candidate in enumerate(candidates, start=1):
            status = str(candidate.get("status", "需確認"))
            tag = "normal" if status == "正常" else "review" if status == "需確認" else "ignore"
            system = self._opening_system_name(candidate)
            opening_id = self._build_opening_id(candidate, system, index)
            candidate["system"] = system
            candidate["opening_id"] = opening_id
            dimension_reliable = bool(candidate.get("dimension_is_reliable"))
            dimension_status = "可標註" if dimension_reliable else "不自動標註"
            dimension_ref_kind = str(candidate.get("dimension_ref_kind") or "")
            dimension_ref_name = str(candidate.get("dimension_ref_name") or "")
            dimension_ref = "｜".join(part for part in [dimension_ref_kind, dimension_ref_name] if part)
            try:
                dimension_distance = f"{float(candidate.get('dimension_distance_cm') or 0):.1f}" if dimension_reliable else ""
            except (TypeError, ValueError):
                dimension_distance = ""
            iid = str(index)
            self.opening_candidates_by_iid[iid] = candidate
            self.opening_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    index,
                    opening_id,
                    status,
                    dimension_status,
                    dimension_ref,
                    dimension_distance,
                    candidate.get("center_source", ""),
                    system,
                    candidate.get("mep_type", ""),
                    candidate.get("mep_id", ""),
                    candidate.get("host_type", ""),
                    candidate.get("host_id", ""),
                    candidate.get("level", ""),
                    candidate.get("shape", ""),
                    candidate.get("size_text", ""),
                    candidate.get("note", ""),
                ),
                tags=(tag,),
            )
        self.opening_status_var.set(
            f"掃描完成｜候選 {len(candidates)}｜正常 {payload.get('normal_count', 0)}｜需確認 {payload.get('review_count', 0)}"
        )

    def _safe_opening_id_part(self, value: object, fallback: str) -> str:
        text = str(value or "").strip()
        blocked = set('\\/:*?"<>|')
        cleaned = "".join("_" if char in blocked or ord(char) < 32 or char.isspace() else char for char in text)
        cleaned = cleaned.strip("_-.")
        return cleaned or fallback

    def _opening_system_name(self, candidate: dict) -> str:
        raw = str(
            candidate.get("system")
            or candidate.get("system_name")
            or candidate.get("mep_system")
            or candidate.get("mep_type")
            or ""
        )
        probe = raw.casefold()
        if any(token in probe for token in ["消防", "fire", "sprinkler", "fp"]):
            return "消防"
        if any(token in probe for token in ["給排水", "排水", "給水", "衛生", "plumbing", "plb"]):
            return "給排水"
        if any(token in probe for token in ["風管", "空調", "hvac", "duct"]):
            return "空調"
        if any(token in probe for token in ["弱電", "通信", "資料", "data", "telecom", "elv"]):
            return "弱電"
        if any(token in probe for token in ["照明", "lighting", "ltg"]):
            return "照明"
        if any(token in probe for token in ["動力", "power", "pwr"]):
            return "動力"
        mep_type = str(candidate.get("mep_type", ""))
        if mep_type in {"電管", "電纜架"}:
            return "電氣"
        if mep_type == "風管":
            return "空調"
        return raw or "未分類"

    def _build_opening_id(self, candidate: dict, system: str, index: int) -> str:
        existing = str(candidate.get("opening_id") or "").strip()
        if existing:
            return existing
        level = self._safe_opening_id_part(candidate.get("level"), "未分層")
        system_part = self._safe_opening_id_part(system, "未分類")
        return f"SC-OP-{level}-{system_part}-{index:04d}"

    def _opening_report_dir(self) -> Path:
        cwd = Path.cwd()
        if cwd.name == "RevitFamilyClassifier" and cwd.parent.name.lower() == "dist":
            project_root = cwd.parent.parent
        elif (cwd / "gui_app.py").exists():
            project_root = cwd
        else:
            project_root = Path.home() / "Documents" / "SC REVIT"
        return project_root / "runtime" / "opening_reports"

    def _export_opening_candidates(self) -> None:
        candidates = []
        if self.opening_scan_result:
            candidates = list(self.opening_scan_result.get("candidates", []))
        if not candidates:
            candidates = list(self.opening_candidates_by_iid.values())
        if not candidates:
            messagebox.showerror("無法匯出", "請先掃描開孔候選清單")
            return
        default_dir = self._opening_report_dir()
        default_dir.mkdir(parents=True, exist_ok=True)
        output_name = filedialog.asksaveasfilename(
            title="選擇開孔清單匯出位置",
            initialdir=str(default_dir),
            initialfile=f"SC_開孔候選清單_{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx"), ("所有檔案", "*.*")],
        )
        if not output_name:
            self.opening_status_var.set("已取消匯出")
            return
        try:
            output_path = export_opening_candidates_xlsx(candidates, output_name)
        except Exception as exc:
            messagebox.showerror("匯出失敗", str(exc))
            return
        self.opening_status_var.set(f"已匯出 XLSX｜{output_path}")
        messagebox.showinfo("匯出完成", f"已產生中文開孔候選清單：\n{output_path}")

    def _view_selected_opening_candidate(self) -> None:
        selected = list(self.opening_tree.selection())
        if not selected:
            messagebox.showerror("無法檢視", "請先在開孔候選清單選取一筆資料")
            return
        candidate = self.opening_candidates_by_iid.get(selected[0])
        if not candidate:
            messagebox.showerror("無法檢視", "找不到選取開孔的資料，請重新掃描")
            return
        self.opening_status_var.set("建立 3D 開孔檢視中…")
        threading.Thread(
            target=self._view_selected_opening_candidate_worker,
            args=(candidate,),
            daemon=True,
        ).start()

    def _view_selected_opening_candidate_worker(self, candidate: dict) -> None:
        try:
            with batch_context("openings", "view_candidate", "View opening candidate", {"opening_id": candidate.get("opening_id")}):
                payload = request_view_opening_candidate(candidate=candidate, box_size_cm=250)
        except Exception as exc:
            self.after(0, lambda: self._finish_opening_error("3D 檢視失敗", exc))
            return
        self.after(0, lambda: self._finish_opening_view(payload))

    def _finish_opening_view(self, payload: dict) -> None:
        self.opening_status_var.set(
            f"已切換 3D 檢視｜{payload.get('view_name', '')}｜中心 {payload.get('center_text', '')}"
        )

    def _place_opening_markers(self) -> None:
        candidates = []
        if self.opening_scan_result:
            candidates = list(self.opening_scan_result.get("candidates", []))
        if not candidates:
            candidates = list(self.opening_candidates_by_iid.values())
        if not candidates:
            messagebox.showerror("無法建立標記", "沒有可標記的開孔候選")
            return
        dimension_item = getattr(self, "opening_dimension_type_items", {}).get(
            getattr(self, "opening_dimension_type_var", tk.StringVar(value="")).get()
        )
        dimension_type_id = dimension_item.get("element_id") if dimension_item else None
        self.opening_status_var.set("建立開孔標記中…")
        threading.Thread(
            target=self._place_opening_markers_worker,
            args=(candidates, dimension_type_id),
            daemon=True,
        ).start()

    def _place_opening_markers_worker(self, candidates: list[dict], dimension_type_id: object | None = None) -> None:
        try:
            with batch_context("openings", "place_markers", "Place opening markers", {"candidate_count": len(candidates)}):
                payload = request_place_opening_markers(
                    candidates=candidates,
                    clear_existing=True,
                    dimension_type_id=dimension_type_id,
                )
        except Exception as exc:
            self.after(0, lambda: self._finish_opening_error("建立開孔標記失敗", exc))
            return
        self.after(0, lambda: self._finish_opening_marker_placement(payload))

    def _finish_opening_marker_placement(self, payload: dict) -> None:
        view_names = list(payload.get("view_names", []))
        placed_count = payload.get("placed_count", 0)
        group_count = payload.get("group_count", 0)
        self.opening_status_var.set(
            f"已建立平面標記｜標記 {placed_count}｜視圖 {len(view_names)}｜群組 {group_count}"
        )
        lines = [
            f"已建立 {placed_count} 個開孔標記。",
            f"已建立/更新 {len(view_names)} 個預留套管平面視圖。",
            f"已建立 {group_count} 個樓層標記群組。",
        ]
        if view_names:
            lines.extend(["", "視圖："])
            lines.extend(f"- {name}" for name in view_names[:20])
        messagebox.showinfo("平面標記完成", "\n".join(lines))

    def _finish_opening_error(self, title: str, exc: Exception) -> None:
        self.opening_status_var.set(title)
        messagebox.showerror(title, str(exc))

    def _build_fire_branch_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        header = ttk.LabelFrame(parent, text="1. 讀取專案資料", padding=10)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(3, weight=1)
        ttk.Button(header, text="讀取管路資料", command=self._load_fire_branch_context).grid(row=0, column=0, sticky="w")
        self.fire_branch_status_var = tk.StringVar(value="尚未讀取")
        ttk.Label(header, text="先讀取管類型、系統類型、樓層與已使用管徑。").grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(header, textvariable=self.fire_branch_status_var).grid(row=0, column=2, columnspan=2, sticky="w", padx=(12, 0))

        main_frame = ttk.LabelFrame(parent, text="2. 主管", padding=10)
        main_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        main_frame.columnconfigure(1, weight=1)
        ttk.Label(main_frame, text="目前主管").grid(row=0, column=0, sticky="w")
        self.fire_main_pipe_var = tk.StringVar(value="未選取")
        ttk.Label(main_frame, textvariable=self.fire_main_pipe_var).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(main_frame, text="讀取選取主管", command=self._read_fire_main_pipe_selection).grid(row=0, column=2, sticky="e")

        setting_frame = ttk.LabelFrame(parent, text="3. 支管設定", padding=10)
        setting_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        setting_frame.columnconfigure(1, weight=1)
        setting_frame.columnconfigure(3, weight=1)
        ttk.Label(setting_frame, text="系統類型").grid(row=0, column=0, sticky="w")
        self.fire_system_type_var = tk.StringVar()
        self.fire_system_type_combo = ttk.Combobox(setting_frame, textvariable=self.fire_system_type_var, state="readonly", width=28)
        self.fire_system_type_combo.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        ttk.Label(setting_frame, text="管類型").grid(row=0, column=2, sticky="w")
        self.fire_pipe_type_var = tk.StringVar()
        self.fire_pipe_type_combo = ttk.Combobox(setting_frame, textvariable=self.fire_pipe_type_var, state="readonly", width=28)
        self.fire_pipe_type_combo.grid(row=0, column=3, sticky="ew", padx=(8, 0))
        ttk.Label(setting_frame, text="管徑").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.fire_diameter_var = tk.StringVar(value="25 mm")
        self.fire_diameter_combo = ttk.Combobox(setting_frame, textvariable=self.fire_diameter_var, state="readonly", width=12)
        self.fire_diameter_combo.grid(row=1, column=1, sticky="w", padx=(8, 12), pady=(10, 0))
        ttk.Label(setting_frame, text="樓層").grid(row=1, column=2, sticky="w", pady=(10, 0))
        self.fire_level_var = tk.StringVar()
        self.fire_level_combo = ttk.Combobox(setting_frame, textvariable=self.fire_level_var, state="readonly", width=20)
        self.fire_level_combo.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(10, 0))
        ttk.Label(setting_frame, text="支管距離樓層高度(cm)").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.fire_branch_offset_var = tk.StringVar(value="0")
        ttk.Entry(setting_frame, textvariable=self.fire_branch_offset_var, width=12).grid(row=2, column=1, sticky="w", padx=(8, 12), pady=(10, 0))
        ttk.Label(setting_frame, text="高度基準").grid(row=2, column=2, sticky="w", pady=(10, 0))
        self.fire_height_reference_var = tk.StringVar(value="管中心")
        self.fire_height_reference_combo = ttk.Combobox(
            setting_frame,
            textvariable=self.fire_height_reference_var,
            state="readonly",
            width=12,
            values=["管上端", "管中心", "管下端"],
        )
        self.fire_height_reference_combo.grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(10, 0))

        sprinkler_frame = ttk.LabelFrame(parent, text="4. 選取撒水頭（Revit 內框選或多選後讀取）", padding=10)
        sprinkler_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        sprinkler_frame.columnconfigure(0, weight=1)
        sprinkler_frame.rowconfigure(1, weight=1)
        ttk.Button(sprinkler_frame, text="讀取框選撒水頭", command=self._read_fire_sprinkler_selection).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.fire_sprinkler_tree = ttk.Treeview(
            sprinkler_frame,
            columns=("id", "family", "type", "x", "y", "z"),
            show="headings",
            selectmode="extended",
        )
        headings = {
            "id": "ID",
            "family": "族群",
            "type": "類型",
            "x": "X",
            "y": "Y",
            "z": "Z",
        }
        widths = {"id": 90, "family": 220, "type": 220, "x": 100, "y": 100, "z": 100}
        for column, title in headings.items():
            self.fire_sprinkler_tree.heading(column, text=title)
            self.fire_sprinkler_tree.column(column, width=widths[column], anchor="center" if column in {"id", "x", "y", "z"} else "w")
        self.fire_sprinkler_tree.grid(row=1, column=0, sticky="nsew")
        fire_scroll = ttk.Scrollbar(sprinkler_frame, orient="vertical", command=self.fire_sprinkler_tree.yview)
        fire_scroll.grid(row=1, column=1, sticky="ns")
        self.fire_sprinkler_tree.configure(yscrollcommand=fire_scroll.set)

        action_frame = ttk.Frame(parent)
        action_frame.grid(row=4, column=0, sticky="ew")
        ttk.Button(action_frame, text="產生螢光路徑預覽", command=self._preview_fire_branch_paths).pack(side="left")
        ttk.Button(action_frame, text="建立消防支管", command=self._create_fire_branch_pipes).pack(side="left", padx=(8, 0))
        ttk.Label(
            action_frame,
            text="支管以主管為基準正交建立；同排撒水頭共用一支支管。",
            foreground="#666666",
        ).pack(side="left", padx=(12, 0))

        self.fire_pipe_type_items = {}
        self.fire_system_type_items = {}
        self.fire_level_items = {}
        self.fire_diameter_items = {}
        self.fire_main_pipe = None
        self.fire_sprinklers = []
        self.fire_preview_group = None

    def _load_fire_branch_context(self) -> None:
        self.fire_branch_status_var.set("讀取管類型中…")
        threading.Thread(target=self._load_fire_branch_context_worker, daemon=True).start()

    def _load_fire_branch_context_worker(self) -> None:
        try:
            with batch_context("fire_branch", "list_context", "Fire branch context"):
                payload = request_fire_branch_context()
        except Exception as exc:
            self.after(0, lambda: self._finish_fire_branch_error("讀取失敗", exc))
            return
        self.after(0, lambda: self._finish_fire_branch_context(payload))

    def _finish_fire_branch_context(self, payload: dict) -> None:
        self.fire_system_type_items = {
            f"系統｜{item.get('name', '')}": item
            for item in payload.get("system_types", [])
            if item.get("name")
        }
        self.fire_pipe_type_items = {
            f"管類型｜{item.get('name', '')}": item
            for item in payload.get("pipe_types", [])
            if item.get("name")
        }
        self.fire_level_items = {
            str(item.get("name", "")): item
            for item in payload.get("levels", [])
            if item.get("name")
        }
        self.fire_diameter_items = {
            str(item.get("label", "")): item
            for item in payload.get("used_diameters", [])
            if item.get("label")
        }
        self.fire_system_type_combo.configure(values=list(self.fire_system_type_items.keys()))
        self.fire_pipe_type_combo.configure(values=list(self.fire_pipe_type_items.keys()))
        self.fire_level_combo.configure(values=list(self.fire_level_items.keys()))
        self.fire_diameter_combo.configure(values=list(self.fire_diameter_items.keys()) or ["25 mm"])
        if self.fire_pipe_type_items:
            self.fire_pipe_type_combo.current(0)
        if self.fire_system_type_items:
            self.fire_system_type_combo.current(0)
        if self.fire_level_items:
            self.fire_level_combo.current(0)
        if self.fire_diameter_items:
            self.fire_diameter_combo.current(0)
        self.fire_branch_status_var.set(
            f"已讀取｜管類型 {len(self.fire_pipe_type_items)}｜系統類型 {len(self.fire_system_type_items)}｜管徑 {len(self.fire_diameter_items)}"
        )

    def _read_fire_main_pipe_selection(self) -> None:
        self.fire_selection_mode = "main"
        self._read_fire_branch_selection()

    def _read_fire_sprinkler_selection(self) -> None:
        self.fire_selection_mode = "sprinklers"
        self._read_fire_branch_selection()

    def _read_fire_branch_selection(self) -> None:
        self.fire_branch_status_var.set("讀取 Revit 選取項目中…")
        threading.Thread(target=self._read_fire_branch_selection_worker, daemon=True).start()

    def _read_fire_branch_selection_worker(self) -> None:
        try:
            with batch_context("fire_branch", "read_selection", "Read fire branch selection"):
                payload = request_fire_branch_selection()
        except Exception as exc:
            self.after(0, lambda: self._finish_fire_branch_error("選取讀取失敗", exc))
            return
        self.after(0, lambda: self._finish_fire_branch_selection(payload))

    def _finish_fire_branch_selection(self, payload: dict) -> None:
        pipes = list(payload.get("pipes", []))
        sprinklers = list(payload.get("sprinklers", []))
        mode = getattr(self, "fire_selection_mode", "all")
        if mode in {"main", "all"}:
            self.fire_main_pipe = pipes[0] if pipes else None
        if mode in {"sprinklers", "all"}:
            self.fire_sprinklers = sprinklers
        if mode in {"main", "all"}:
            if self.fire_main_pipe:
                self.fire_main_pipe_var.set(
                    f"ID {self.fire_main_pipe.get('element_id')}｜{self.fire_main_pipe.get('name')}｜管徑 {float(self.fire_main_pipe.get('diameter_mm') or 0):g} mm"
                )
                pipe_type_id = str(self.fire_main_pipe.get("pipe_type_id") or "")
                for name, item in self.fire_pipe_type_items.items():
                    if str(item.get("element_id")) == pipe_type_id:
                        self.fire_pipe_type_var.set(name)
                        break
                system_type_id = str(self.fire_main_pipe.get("system_type_id") or "")
                for name, item in self.fire_system_type_items.items():
                    if str(item.get("element_id")) == system_type_id:
                        self.fire_system_type_var.set(name)
                        break
                if float(self.fire_main_pipe.get("diameter_mm") or 0) > 0:
                    diameter_label = f"{float(self.fire_main_pipe.get('diameter_mm')):g} mm"
                    if diameter_label in self.fire_diameter_items:
                        self.fire_diameter_var.set(diameter_label)
            else:
                self.fire_main_pipe_var.set("未選取主管")

        if mode in {"sprinklers", "all"}:
            for item in self.fire_sprinkler_tree.get_children():
                self.fire_sprinkler_tree.delete(item)
            for sprinkler in self.fire_sprinklers:
                point = sprinkler.get("point") or {}
                self.fire_sprinkler_tree.insert(
                    "",
                    "end",
                    iid=str(sprinkler.get("element_id")),
                    values=(
                        sprinkler.get("element_id", ""),
                        sprinkler.get("family_name", ""),
                        sprinkler.get("type_name", ""),
                        f"{float(point.get('x') or 0):.2f}",
                        f"{float(point.get('y') or 0):.2f}",
                        f"{float(point.get('z') or 0):.2f}",
                    ),
                )
        self.fire_branch_status_var.set(f"已讀取｜主管 {1 if self.fire_main_pipe else 0}｜撒水頭 {len(self.fire_sprinklers)}")

    def _create_fire_branch_pipes(self) -> None:
        if not self.fire_main_pipe:
            messagebox.showerror("無法建立", "請先在 Revit 選取一段主管，並按「讀取目前選取」")
            return
        if not self.fire_sprinklers:
            messagebox.showerror("無法建立", "請先在 Revit 選取要連接的撒水頭，並按「讀取目前選取」")
            return
        pipe_type = self.fire_pipe_type_items.get(self.fire_pipe_type_var.get())
        system_type = self.fire_system_type_items.get(self.fire_system_type_var.get())
        level = self.fire_level_items.get(self.fire_level_var.get())
        if not pipe_type:
            messagebox.showerror("無法建立", "請先選擇管類型")
            return
        if not system_type:
            messagebox.showerror("無法建立", "請先選擇系統類型")
            return
        if not level:
            messagebox.showerror("無法建立", "請先選擇樓層")
            return
        try:
            diameter_text = str(self.fire_diameter_var.get() or "0").replace("mm", "").strip()
            diameter_mm = float(diameter_text)
            branch_offset_cm = float(self.fire_branch_offset_var.get() or 0)
        except ValueError:
            messagebox.showerror("無法建立", "管徑與支管高度差必須是數字")
            return
        if diameter_mm <= 0:
            messagebox.showerror("無法建立", "管徑必須大於 0")
            return
        if not messagebox.askyesno(
            "確認建立消防支管",
            f"將建立 {len(self.fire_sprinklers)} 顆撒水頭的支管。\n第一版不做避障與變徑，是否繼續？",
        ):
            return
        self.fire_branch_status_var.set("建立消防支管中…")
        preview_group = self.fire_preview_group
        threading.Thread(
            target=self._create_fire_branch_pipes_worker,
            args=(
                self.fire_main_pipe,
                list(self.fire_sprinklers),
                pipe_type,
                system_type,
                level,
                diameter_mm,
                branch_offset_cm,
                self.fire_height_reference_var.get(),
                preview_group,
            ),
            daemon=True,
        ).start()

    def _preview_fire_branch_paths(self) -> None:
        if not self.fire_main_pipe:
            messagebox.showerror("無法預覽", "請先讀取選取主管")
            return
        if not self.fire_sprinklers:
            messagebox.showerror("無法預覽", "請先框選並讀取撒水頭")
            return
        level = self.fire_level_items.get(self.fire_level_var.get())
        if not level:
            messagebox.showerror("無法預覽", "請先選擇樓層")
            return
        try:
            branch_offset_cm = float(self.fire_branch_offset_var.get() or 0)
        except ValueError:
            messagebox.showerror("無法預覽", "支管高度必須是數字")
            return
        self.fire_branch_status_var.set("產生螢光路徑預覽中…")
        threading.Thread(
            target=self._preview_fire_branch_paths_worker,
            args=(self.fire_main_pipe, list(self.fire_sprinklers), level, branch_offset_cm, self.fire_height_reference_var.get()),
            daemon=True,
        ).start()

    def _preview_fire_branch_paths_worker(
        self,
        main_pipe: dict,
        sprinklers: list[dict],
        level: dict,
        branch_offset_cm: float,
        height_reference: str,
    ) -> None:
        try:
            with batch_context("fire_branch", "preview", "Preview fire branch", {"sprinkler_count": len(sprinklers)}):
                payload = request_create_fire_branch_preview(
                    main_pipe_id=main_pipe.get("element_id"),
                    sprinkler_ids=[item.get("element_id") for item in sprinklers],
                    level_id=level.get("element_id"),
                    branch_offset_cm=branch_offset_cm,
                    height_reference=height_reference,
                )
        except Exception as exc:
            self.after(0, lambda: self._finish_fire_branch_error("預覽失敗", exc))
            return
        self.after(0, lambda: self._finish_fire_branch_preview(payload))

    def _finish_fire_branch_preview(self, payload: dict) -> None:
        self.fire_preview_group = {
            "group_id": payload.get("group_id"),
            "group_name": payload.get("group_name"),
            "batch_id": payload.get("batch_id"),
        }
        self.fire_branch_status_var.set(f"已產生螢光路徑預覽｜{payload.get('segment_count', 0)} 段")

    def _create_fire_branch_pipes_worker(
        self,
        main_pipe: dict,
        sprinklers: list[dict],
        pipe_type: dict,
        system_type: dict,
        level: dict,
        diameter_mm: float,
        branch_offset_cm: float,
        height_reference: str,
        preview_group: dict | None,
    ) -> None:
        try:
            preview_group_id = (preview_group or {}).get("group_id")
            with batch_context("fire_branch", "create_pipes", "Create fire branch pipes", {"sprinkler_count": len(sprinklers), "diameter_mm": diameter_mm}):
                payload = request_create_fire_branch_pipes(
                    main_pipe_id=main_pipe.get("element_id"),
                    sprinkler_ids=[item.get("element_id") for item in sprinklers],
                    pipe_type_id=pipe_type.get("element_id"),
                    system_type_id=system_type.get("element_id"),
                    level_id=level.get("element_id"),
                    diameter_mm=diameter_mm,
                    branch_offset_cm=branch_offset_cm,
                    height_reference=height_reference,
                    preview_group_id=preview_group_id,
                    delete_preview_after_create=True,
                )
        except Exception as exc:
            self.after(0, lambda: self._finish_fire_branch_error("建立失敗", exc))
            return
        self.after(0, lambda: self._finish_fire_branch_created(payload))

    def _finish_fire_branch_created(self, payload: dict) -> None:
        created = list(payload.get("created", []))
        failed = list(payload.get("failed", []))
        if payload.get("deleted_preview_group_id"):
            self.fire_preview_group = None
        self.fire_branch_status_var.set(
            f"建立完成｜管段 {len(created)}｜失敗 {len(failed)}｜Batch {payload.get('batch_id', '')}"
        )
        if failed:
            messagebox.showwarning(
                "消防支管部分失敗",
                "\n".join(str(item.get("reason", item)) for item in failed[:10]),
            )

    def _finish_fire_branch_error(self, title: str, exc: Exception) -> None:
        self.fire_branch_status_var.set(title)
        messagebox.showerror(title, str(exc))

    def _build_project_recovery_tab(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(3, weight=1)
        parent.columnconfigure(0, weight=1)

        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Button(
            header,
            text="掃描目前專案",
            command=self._scan_project_families,
        ).grid(row=0, column=0, sticky="w")
        self.project_scan_var = tk.StringVar(value="尚未掃描")
        ttk.Label(header, textvariable=self.project_scan_var).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(12, 0),
        )

        ttk.Label(
            parent,
            text="第一版只讀掃描：不匯出、不入庫、不修改任何專案或族群。",
        ).grid(row=1, column=0, sticky="w", pady=(8, 8))

        project_actions = ttk.Frame(parent)
        project_actions.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(
            project_actions,
            text="全選可回收",
            command=self._select_recoverable_project_families,
        ).pack(side="left")
        ttk.Button(
            project_actions,
            text="清除選取",
            command=lambda: self.project_family_tree.selection_remove(
                self.project_family_tree.selection()
            ),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            project_actions,
            text="匯出到回收暫存區",
            command=self._export_selected_project_families,
        ).pack(side="left", padx=(8, 0))

        self.project_family_tree = ttk.Treeview(
            parent,
            columns=("family_name", "category", "instance_count", "symbol_count", "status"),
            show="headings",
            selectmode="extended",
        )
        self.project_family_tree.heading("family_name", text="族群名稱")
        self.project_family_tree.heading("category", text="Revit 類別")
        self.project_family_tree.heading("instance_count", text="使用數量")
        self.project_family_tree.heading("symbol_count", text="類型數")
        self.project_family_tree.heading("status", text="狀態")
        self.project_family_tree.column("family_name", width=260)
        self.project_family_tree.column("category", width=160)
        self.project_family_tree.column("instance_count", width=90, anchor="center")
        self.project_family_tree.column("symbol_count", width=80, anchor="center")
        self.project_family_tree.column("status", width=180)
        self.project_family_tree.grid(row=3, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.project_family_tree.yview)
        scrollbar.grid(row=3, column=1, sticky="ns")
        self.project_family_tree.configure(yscrollcommand=scrollbar.set)

        self.project_family_tree.tag_configure("recoverable", background="#e8f5e9")
        self.project_family_tree.tag_configure("unused", background="#f5f5f5")
        self.project_family_tree.tag_configure("blocked", background="#ffebee")

    def _build_point_placement_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(1, weight=4)

        project_frame = ttk.LabelFrame(parent, text="1. 掃描專案資料", padding=10)
        project_frame.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        project_frame.columnconfigure(1, weight=1)
        ttk.Button(
            project_frame,
            text="讀取目前專案資料",
            command=self._load_point_placement_context,
        ).grid(row=0, column=0, sticky="w")
        self.placement_status_var = tk.StringVar(value="尚未讀取")
        ttk.Label(project_frame, textvariable=self.placement_status_var).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(12, 0),
        )

        cad_frame = ttk.LabelFrame(parent, text="2. 選取 CAD Link 並掃描圖塊", padding=10)
        cad_frame.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))
        cad_frame.columnconfigure(1, weight=1)
        cad_frame.columnconfigure(3, weight=1)

        ttk.Label(cad_frame, text="CAD Link / 來源").grid(row=0, column=0, sticky="w")
        self.placement_cad_var = tk.StringVar()
        self.placement_cad_combo = ttk.Combobox(
            cad_frame,
            textvariable=self.placement_cad_var,
            state="readonly",
            width=42,
        )
        self.placement_cad_combo.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        self.placement_cad_combo.bind("<<ComboboxSelected>>", self._on_placement_cad_selected)

        ttk.Label(cad_frame, text="DWG 檔案").grid(row=0, column=2, sticky="w")
        self.placement_dwg_path_var = tk.StringVar()
        ttk.Entry(cad_frame, textvariable=self.placement_dwg_path_var).grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(8, 8),
        )
        ttk.Button(
            cad_frame,
            text="選擇 DWG",
            command=self._choose_placement_dwg_file,
        ).grid(row=0, column=4, sticky="w")

        ttk.Label(cad_frame, text="DWG 單位").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.placement_dwg_unit_var = tk.StringVar(value="自動")
        self.placement_dwg_unit_combo = ttk.Combobox(
            cad_frame,
            textvariable=self.placement_dwg_unit_var,
            state="readonly",
            width=12,
            values=list(DWG_UNIT_TO_FEET.keys()),
        )
        self.placement_dwg_unit_combo.grid(row=1, column=1, sticky="w", padx=(8, 12), pady=(10, 0))
        ttk.Button(
            cad_frame,
            text="掃描 CAD 圖塊",
            command=self._read_placement_dwg_blocks,
        ).grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Label(
            cad_frame,
            text="建議使用 Link CAD；Import CAD 僅作備用。",
            foreground="#666666",
        ).grid(row=1, column=3, columnspan=2, sticky="w", padx=(8, 0), pady=(10, 0))

        block_frame = ttk.LabelFrame(parent, text="3. 選取 CAD 圖塊", padding=10)
        block_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 8))
        block_frame.columnconfigure(0, weight=1)
        block_frame.rowconfigure(0, weight=1)
        self.placement_mapping_tree = ttk.Treeview(
            block_frame,
            columns=("block_name", "count", "category", "family", "type", "level", "height", "status"),
            show="headings",
            selectmode="browse",
            height=18,
        )
        headings = {
            "block_name": "CAD圖塊",
            "count": "數量",
            "category": "Revit類別",
            "family": "Revit族群",
            "type": "Revit類型",
            "level": "樓層",
            "height": "高度(cm)",
            "status": "狀態",
        }
        widths = {
            "block_name": 260,
            "count": 70,
            "category": 120,
            "family": 220,
            "type": 180,
            "level": 120,
            "height": 90,
            "status": 120,
        }
        for column, title in headings.items():
            self.placement_mapping_tree.heading(column, text=title)
            anchor = "center" if column in {"count", "height", "status"} else "w"
            self.placement_mapping_tree.column(column, width=widths[column], anchor=anchor)
        self.placement_mapping_tree.grid(row=0, column=0, sticky="nsew")
        self.placement_mapping_tree.bind("<<TreeviewSelect>>", self._on_mapping_row_selected)
        mapping_scrollbar = ttk.Scrollbar(block_frame, orient="vertical", command=self.placement_mapping_tree.yview)
        mapping_scrollbar.grid(row=0, column=1, sticky="ns")
        self.placement_mapping_tree.configure(yscrollcommand=mapping_scrollbar.set)
        self.placement_mapping_tree.tag_configure("mapped", background="#e8f5e9")
        self.placement_mapping_tree.tag_configure("unmapped", background="#fff8e1")

        family_frame = ttk.LabelFrame(parent, text="4. 選取 Revit 族群與放置屬性", padding=10)
        family_frame.grid(row=2, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))
        family_frame.columnconfigure(1, weight=1)
        family_frame.columnconfigure(3, weight=1)

        ttk.Label(family_frame, text="Revit 類別").grid(row=0, column=0, sticky="w")
        self.placement_category_var = tk.StringVar()
        self.placement_category_combo = ttk.Combobox(
            family_frame,
            textvariable=self.placement_category_var,
            state="readonly",
            width=28,
        )
        self.placement_category_combo.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        self.placement_category_combo.bind("<<ComboboxSelected>>", self._on_placement_category_selected)

        ttk.Label(family_frame, text="Revit 族群").grid(row=0, column=2, sticky="w")
        self.placement_family_var = tk.StringVar()
        self.placement_family_combo = ttk.Combobox(
            family_frame,
            textvariable=self.placement_family_var,
            state="readonly",
            width=28,
        )
        self.placement_family_combo.grid(row=0, column=3, sticky="ew", padx=(8, 0))
        self.placement_family_combo.bind("<<ComboboxSelected>>", self._on_placement_family_selected)

        ttk.Label(family_frame, text="Revit 類型").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.placement_symbol_var = tk.StringVar()
        self.placement_symbol_combo = ttk.Combobox(
            family_frame,
            textvariable=self.placement_symbol_var,
            state="readonly",
            width=28,
        )
        self.placement_symbol_combo.grid(row=1, column=1, sticky="ew", padx=(8, 12), pady=(10, 0))
        self.placement_symbol_combo.bind("<<ComboboxSelected>>", self._on_placement_symbol_selected)

        self.placement_level_label = ttk.Label(family_frame, text="樓層")
        self.placement_level_label.grid(row=1, column=2, sticky="w", pady=(10, 0))
        self.placement_level_var = tk.StringVar()
        self.placement_level_combo = ttk.Combobox(
            family_frame,
            textvariable=self.placement_level_var,
            state="readonly",
            width=20,
        )
        self.placement_level_combo.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(10, 0))

        self.placement_offset_label = ttk.Label(family_frame, text="距離樓層高度(cm)")
        self.placement_offset_label.grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.placement_offset_var = tk.StringVar(value="0")
        ttk.Entry(family_frame, textvariable=self.placement_offset_var, width=12).grid(
            row=2,
            column=1,
            sticky="w",
            padx=(8, 12),
            pady=(10, 0),
        )
        ttk.Button(
            family_frame,
            text="套用到選取圖塊",
            command=self._apply_mapping_to_selected_block,
        ).grid(row=2, column=3, sticky="e", pady=(10, 0))

        action_frame = ttk.LabelFrame(parent, text="5. 預覽校正並生成", padding=10)
        action_frame.grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=(0, 8))
        action_frame.columnconfigure(1, weight=1)
        ttk.Button(
            action_frame,
            text="產生螢光預覽點",
            command=self._preview_cad_blocks,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            action_frame,
            text="在 Revit 圖面移動整個螢光群組校正位置。",
            foreground="#666666",
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(action_frame, text="防重複距離(mm)").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.placement_tolerance_var = tk.StringVar(value="10")
        ttk.Entry(action_frame, textvariable=self.placement_tolerance_var, width=12).grid(
            row=1,
            column=1,
            sticky="w",
            padx=(8, 0),
            pady=(12, 0),
        )
        ttk.Button(
            action_frame,
            text="放置選取圖塊全部",
            command=self._place_preview_points,
        ).grid(row=1, column=2, sticky="e", padx=(12, 0), pady=(12, 0))
        ttk.Button(
            action_frame,
            text="\u5132\u5b58\u5c0d\u7167",
            command=self._save_placement_mapping,
        ).grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Button(
            action_frame,
            text="\u8f09\u5165\u5c0d\u7167",
            command=self._load_placement_mapping,
        ).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(12, 0))

    def _load_or_choose_library_root(self) -> None:
        if self.app_mode == "opening_check":
            self.library_root = None
            self.library_var.set("開孔定位不需要族群庫")
            return
        if self.app_mode == "backstage":
            saved_root = load_settings().get("library_root")
            self.library_root = saved_root if saved_root else None
            self.library_var.set(saved_root or "SC " + "\u5f8c\u53f0" + "\u4e0d\u9700\u8981\u5148\u8a2d\u5b9a\u65cf\u7fa4\u5eab")
            return
        saved_root = load_settings().get("library_root")
        if saved_root:
            validation = validate_library_root(saved_root)
            if validation["valid"]:
                self.library_root = str(validation["root"])
                self.library_var.set(self.library_root)
                return
            messagebox.showwarning(
                "已儲存的族群庫路徑無效",
                "先前儲存的族群庫位置已失效，請重新選擇有效的族群庫根目錄。",
            )
        self._choose_library_root(force=True)

    def _choose_library_root(self, force: bool = False) -> None:
        selected = filedialog.askdirectory(title="選擇族群庫根目錄")
        if not selected:
            if force and not self.library_root:
                self.library_var.set("尚未設定")
            return
        validation = validate_library_root(selected)
        if not validation["valid"]:
            missing = "\n".join(f"- {path}" for path in validation.get("missing_paths", [])[:8])
            detail = f"\n\n缺少必要結構：\n{missing}" if missing else ""
            messagebox.showerror("族群庫路徑錯誤", f"{validation['error']}{detail}")
            return
        self.library_root = str(validation["root"])
        self.library_var.set(self.library_root)
        save_library_root(self.library_root)

    def _refresh_listener_status(self) -> None:
        status = get_listener_status()
        self.listener_var.set(f"Revit：{status['label']}")
        self.after(3000, self._refresh_listener_status)

    def _load_point_placement_context(self) -> None:
        self.placement_status_var.set("讀取中…")
        threading.Thread(target=self._load_point_placement_context_worker, daemon=True).start()

    def _load_point_placement_context_worker(self) -> None:
        try:
            with batch_context("cad_points", "list_context", "CAD point placement context"):
                payload = request_point_placement_context()
        except Exception as exc:
            self.after(0, lambda: self._finish_point_placement_context_error(exc))
            return
        self.after(0, lambda: self._finish_point_placement_context(payload))

    def _finish_point_placement_context_error(self, exc: Exception) -> None:
        self.placement_status_var.set("讀取失敗")
        messagebox.showerror("批量點位放置讀取失敗", str(exc))

    def _finish_point_placement_context(self, payload: dict) -> None:
        self.placement_context = payload
        cad_items = list(payload.get("cad_imports", []))
        cad_items.sort(key=lambda item: (not bool(item.get("is_linked")), str(item.get("name", ""))))
        self.placement_cad_items = {}
        for item in cad_items:
            source_kind = "Link" if item.get("is_linked") else "Import"
            display_name = (
                item.get("display_name")
                or f"{item.get('name', '')}｜ID {item.get('element_id')}｜{source_kind}"
            )
            if not item.get("is_linked"):
                display_name = f"不建議：{display_name}"
            self.placement_cad_items[display_name] = item
        self.placement_block_items = {}
        self.placement_mapping_data = {}
        self.placement_block_counts = {}
        self._clear_placement_mapping_tree()
        self._clear_placement_preview_tree()
        self.placement_all_symbols = list(payload.get("family_symbols", []))
        self.placement_symbol_items = {}
        self._refresh_placement_categories()
        self.placement_level_items = {
            str(item.get("name", "")): item
            for item in payload.get("levels", [])
        }
        self.placement_cad_combo.configure(values=list(self.placement_cad_items.keys()))
        self.placement_level_combo.configure(values=list(self.placement_level_items.keys()))
        if self.placement_cad_items:
            self.placement_cad_combo.current(0)
        if self.placement_level_items:
            self.placement_level_combo.current(0)
        self.placement_status_var.set(
            f"CAD {len(self.placement_cad_items)}｜族群類型 {len(self.placement_all_symbols)}｜樓層 {len(self.placement_level_items)}"
        )
        if self.placement_cad_items:
            self._sync_dwg_path_from_selected_cad()

    def _refresh_placement_categories(self) -> None:
        preferred_order = [
            "電氣設備",
            "電氣裝置",
            "照明設備",
            "照明裝置",
            "火警裝置",
            "通訊裝置",
            "資料裝置",
            "安全裝置",
            "電話裝置",
            "機械設備",
            "管附件",
            "管配件",
        ]
        categories = sorted({
            str(item.get("category", ""))
            for item in getattr(self, "placement_all_symbols", [])
            if item.get("category")
        })
        categories.sort(
            key=lambda value: (
                preferred_order.index(value) if value in preferred_order else 999,
                value,
            )
        )
        self.placement_category_combo.configure(values=categories)
        self.placement_category_var.set("")
        self.placement_family_combo.configure(values=[])
        self.placement_family_var.set("")
        self.placement_symbol_combo.configure(values=[])
        self.placement_symbol_var.set("")
        if categories:
            self.placement_category_combo.current(0)
            self._refresh_placement_families()

    def _on_placement_category_selected(self, _event=None) -> None:
        self._refresh_placement_families()

    def _refresh_placement_families(self) -> None:
        category = self.placement_category_var.get()
        families = sorted({
            str(item.get("family_name", ""))
            for item in getattr(self, "placement_all_symbols", [])
            if item.get("category") == category and item.get("family_name")
        })
        self.placement_family_combo.configure(values=families)
        self.placement_family_var.set("")
        self.placement_symbol_combo.configure(values=[])
        self.placement_symbol_var.set("")
        if families:
            self.placement_family_combo.current(0)
            self._refresh_placement_types()

    def _on_placement_family_selected(self, _event=None) -> None:
        self._refresh_placement_types()

    def _on_placement_symbol_selected(self, _event=None) -> None:
        self._refresh_placement_input_module()

    def _refresh_placement_types(self) -> None:
        category = self.placement_category_var.get()
        family = self.placement_family_var.get()
        matching = [
            item
            for item in getattr(self, "placement_all_symbols", [])
            if item.get("category") == category and item.get("family_name") == family
        ]
        matching.sort(key=lambda item: str(item.get("type_name", "")))
        self.placement_symbol_items = {
            str(item.get("type_name") or item.get("display_name") or ""): item
            for item in matching
        }
        values = list(self.placement_symbol_items.keys())
        self.placement_symbol_combo.configure(values=values)
        self.placement_symbol_var.set("")
        if values:
            self.placement_symbol_combo.current(0)
        self._refresh_placement_input_module()

    def _get_selected_placement_symbol(self) -> dict | None:
        return getattr(self, "placement_symbol_items", {}).get(self.placement_symbol_var.get())

    def _get_placement_rule(self, symbol: dict | None = None) -> str:
        symbol = symbol or self._get_selected_placement_symbol()
        category = str((symbol or {}).get("category") or self.placement_category_var.get() or "")
        if "柱" in category:
            return "column"
        if any(token in category for token in ("門", "窗")):
            return "host_required"
        return "level_offset"

    def _refresh_placement_input_module(self) -> None:
        rule = self._get_placement_rule()
        if rule == "column":
            self.placement_level_label.configure(text="基準樓層")
            self.placement_offset_label.configure(text="基準偏移(cm)")
        elif rule == "host_required":
            self.placement_level_label.configure(text="主體樓層")
            self.placement_offset_label.configure(text="離主體高度(cm)")
        else:
            self.placement_level_label.configure(text="樓層")
            self.placement_offset_label.configure(text="距離樓層高度(cm)")

    def _format_cm_from_mm(self, value) -> str:
        try:
            return f"{float(value or 0) / 10:g}"
        except (TypeError, ValueError):
            return ""

    def _get_selected_placement_ids(self) -> tuple[str, str | None, str | None]:
        cad = getattr(self, "placement_cad_items", {}).get(self.placement_cad_var.get())
        symbol = getattr(self, "placement_symbol_items", {}).get(self.placement_symbol_var.get())
        level = getattr(self, "placement_level_items", {}).get(self.placement_level_var.get())
        return (
            str(cad.get("element_id")) if cad else "",
            str(symbol.get("element_id")) if symbol else None,
            str(level.get("element_id")) if level else None,
        )

    def _on_placement_cad_selected(self, _event=None) -> None:
        self._sync_dwg_path_from_selected_cad()

    def _sync_dwg_path_from_selected_cad(self) -> None:
        cad = getattr(self, "placement_cad_items", {}).get(self.placement_cad_var.get())
        path = str(cad.get("path") or "") if cad else ""
        if path:
            self.placement_dwg_path_var.set(path)
        elif cad:
            self._load_selected_cad_path_async(str(cad.get("element_id") or ""), self.placement_cad_var.get())
        self.placement_block_items = {}
        self.placement_mapping_data = {}
        self.placement_block_counts = {}
        self._clear_placement_mapping_tree()
        self._clear_placement_preview_tree()
        self.placement_dwg_result = None
        self.placement_preview = None
        self.placement_preview_block_name = ""

    def _load_selected_cad_path_async(self, import_id: str, selected_key: str) -> None:
        if not import_id:
            return
        self.placement_status_var.set("讀取 CAD Link 路徑中…")
        threading.Thread(
            target=self._load_selected_cad_path_worker,
            args=(import_id, selected_key),
            daemon=True,
        ).start()

    def _load_selected_cad_path_worker(self, import_id: str, selected_key: str) -> None:
        try:
            payload = request_cad_import_path(import_id, timeout_seconds=30)
        except Exception:
            self.after(0, lambda: self.placement_status_var.set("無法自動讀取 CAD 路徑，請先在 Revit 管理連結重新載入，或手動選擇 DWG"))
            return
        self.after(0, lambda: self._finish_selected_cad_path(import_id, selected_key, payload))

    def _format_cad_link_status_message(self, payload: dict) -> str | None:
        status = str(payload.get("linked_status") or "")
        path = str(payload.get("path") or "")
        path_exists = bool(payload.get("path_exists"))
        if status == "NotFound":
            return "CAD Link 狀態為找不到，請先在 Revit 管理連結中重新載入"
        if path and not path_exists:
            return f"CAD Link 路徑不存在：{path}"
        if not path:
            return "CAD Link 未提供 DWG 路徑，請先在 Revit 管理連結中重新載入"
        return None

    def _finish_selected_cad_path(self, import_id: str, selected_key: str, payload: dict) -> None:
        if self.placement_cad_var.get() != selected_key:
            return
        path = str(payload.get("path") or "")
        cad = getattr(self, "placement_cad_items", {}).get(selected_key)
        if cad is not None:
            cad["path"] = path
            cad["linked_status"] = payload.get("linked_status")
            cad["path_exists"] = payload.get("path_exists")
            cad["usable"] = payload.get("usable")
        message = self._format_cad_link_status_message(payload)
        if message:
            self.placement_dwg_path_var.set(path)
            self.placement_status_var.set(message)
            return
        self.placement_dwg_path_var.set(path)
        self.placement_status_var.set("已帶入 CAD Link 的 DWG 路徑")

    def _get_selected_cad_import_id(self) -> str:
        cad = getattr(self, "placement_cad_items", {}).get(self.placement_cad_var.get())
        return str(cad.get("element_id") or "") if cad else ""

    def _resolve_placement_dwg_path_for_scan(self) -> str:
        import_id = self._get_selected_cad_import_id()
        if not import_id:
            raise DwgBlockReaderError("請先選擇 CAD Link")
        payload = request_cad_import_path(import_id, timeout_seconds=30)
        selected_key = self.placement_cad_var.get()
        cad = getattr(self, "placement_cad_items", {}).get(selected_key)
        if cad is not None:
            cad["path"] = payload.get("path")
            cad["linked_status"] = payload.get("linked_status")
            cad["path_exists"] = payload.get("path_exists")
            cad["usable"] = payload.get("usable")
        message = self._format_cad_link_status_message(payload)
        dwg_path = str(payload.get("path") or "").strip()
        if dwg_path:
            self.placement_dwg_path_var.set(dwg_path)
        if message:
            raise DwgBlockReaderError(message)
        return dwg_path

    def _choose_placement_dwg_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="選擇實際 DWG 檔案",
            filetypes=[("DWG 檔案", "*.dwg"), ("所有檔案", "*.*")],
        )
        if not selected:
            return
        self.placement_dwg_path_var.set(selected)
        self.placement_block_items = {}
        self.placement_mapping_data = {}
        self.placement_block_counts = {}
        self._clear_placement_mapping_tree()
        self._clear_placement_preview_tree()
        self.placement_dwg_result = None
        self.placement_preview = None
        self.placement_preview_block_name = ""

    def _read_placement_dwg_blocks(self) -> None:
        self.placement_status_var.set("讀取 CAD 圖塊中…")
        threading.Thread(
            target=self._read_placement_dwg_blocks_worker,
            daemon=True,
        ).start()

    def _read_placement_dwg_blocks_worker(self) -> None:
        try:
            with batch_context("cad_points", "read_dwg_blocks", "Read DWG blocks"):
                dwg_path = self._resolve_placement_dwg_path_for_scan()
                payload = read_dwg_blocks(dwg_path, timeout_seconds=30)
                payload["dwg_path"] = dwg_path
        except Exception as exc:
            self.after(0, lambda: self._finish_cad_block_names_error(exc))
            return
        self.after(0, lambda: self._finish_cad_block_names(payload))

    def _finish_cad_block_names_error(self, exc: Exception) -> None:
        self.placement_status_var.set("圖塊清單讀取失敗")
        messagebox.showerror("CAD 圖塊清單讀取失敗", str(exc))

    def _finish_cad_block_names(self, payload: dict) -> None:
        if payload.get("dwg_path"):
            self.placement_dwg_path_var.set(str(payload.get("dwg_path")))
        self.placement_dwg_result = payload
        self.placement_preview = None
        self.placement_preview_block_name = ""
        blocks = list(payload.get("blocks", []))
        self.placement_mapping_data = {}
        self.placement_block_counts = {
            str(item.get("block_name", "")): int(item.get("count", 0) or 0)
            for item in blocks
            if item.get("block_name")
        }
        self.placement_block_items = {
            f"{item.get('block_name', '')}（{item.get('count', 0)}）": str(item.get("block_name", ""))
            for item in blocks
            if item.get("block_name")
        }
        self._render_placement_mapping_tree()
        self._clear_placement_preview_tree()
        unit_name = str(payload.get("unit_name") or "自動")
        if unit_name in DWG_UNIT_TO_FEET:
            self.placement_dwg_unit_var.set(unit_name)
        elif int(payload.get("unit_code") or 0) == 0:
            self.placement_dwg_unit_var.set("毫米")
        else:
            self.placement_dwg_unit_var.set("自動")
        self.placement_status_var.set(
            f"圖塊清單完成｜共 {len(self.placement_block_counts)} 種圖塊｜DWG單位：{payload.get('unit_name', '未知')}｜目前採用：{self.placement_dwg_unit_var.get()}"
        )

    def _clear_placement_mapping_tree(self) -> None:
        tree = getattr(self, "placement_mapping_tree", None)
        if not tree:
            return
        for item in tree.get_children():
            tree.delete(item)

    def _clear_placement_preview_tree(self) -> None:
        tree = getattr(self, "placement_preview_tree", None)
        if not tree:
            return
        for item in tree.get_children():
            tree.delete(item)

    def _render_placement_mapping_tree(self) -> None:
        self._clear_placement_mapping_tree()
        for block_name, count in sorted(getattr(self, "placement_block_counts", {}).items()):
            mapping = getattr(self, "placement_mapping_data", {}).get(block_name, {})
            mapped = bool(mapping)
            self.placement_mapping_tree.insert(
                "",
                "end",
                iid=block_name,
                values=(
                    block_name,
                    count,
                    mapping.get("category", ""),
                    mapping.get("family_name", ""),
                    mapping.get("type_name", ""),
                    mapping.get("level_name", ""),
                    self._format_cm_from_mm(mapping.get("offset_mm", "")),
                    "已設定" if mapped else "未設定",
                ),
                tags=("mapped" if mapped else "unmapped",),
            )

    def _on_mapping_row_selected(self, _event=None) -> None:
        block_name = self._get_selected_block_name()
        if not block_name:
            return
        mapping = getattr(self, "placement_mapping_data", {}).get(block_name)
        if not mapping:
            return
        self.placement_category_var.set(mapping.get("category", ""))
        self._refresh_placement_families()
        self.placement_family_var.set(mapping.get("family_name", ""))
        self._refresh_placement_types()
        self.placement_symbol_var.set(mapping.get("type_name", ""))
        self.placement_level_var.set(mapping.get("level_name", ""))
        self._refresh_placement_input_module()
        self.placement_offset_var.set(self._format_cm_from_mm(mapping.get("offset_mm", "0")))

    def _apply_mapping_to_selected_block(self) -> None:
        block_name = self._get_selected_block_name()
        if not block_name:
            messagebox.showerror("無法套用", "請先在圖塊對照表選取一個 CAD 圖塊")
            return
        symbol = getattr(self, "placement_symbol_items", {}).get(self.placement_symbol_var.get())
        level = getattr(self, "placement_level_items", {}).get(self.placement_level_var.get())
        if not symbol:
            messagebox.showerror("無法套用", "請先選擇 Revit 類型")
            return
        if not level:
            messagebox.showerror("無法套用", "請先選擇樓層")
            return
        rule = self._get_placement_rule(symbol)
        if rule == "host_required":
            messagebox.showerror("暫不支援", "這類族群需要牆、天花板、樓板或工作平面作為主體，不能只用 CAD 點位自動放置。")
            return
        try:
            offset_cm = float(self.placement_offset_var.get() or 0)
            offset_mm = offset_cm * 10
        except ValueError:
            messagebox.showerror("無法套用", "高度必須是數字，單位為 cm")
            return
        self.placement_mapping_data[block_name] = {
            "block_name": block_name,
            "category": str(symbol.get("category", "")),
            "family_name": str(symbol.get("family_name", "")),
            "type_name": str(symbol.get("type_name", "")),
            "symbol_id": str(symbol.get("element_id")),
            "level_name": self.placement_level_var.get(),
            "level_id": str(level.get("element_id")),
            "offset_mm": offset_mm,
        }
        self._render_placement_mapping_tree()
        self.placement_mapping_tree.selection_set(block_name)
        self.placement_mapping_tree.see(block_name)
        self.placement_status_var.set(f"已套用對照：{block_name} → {symbol.get('family_name')} : {symbol.get('type_name')}")

    def _get_placement_mapping_source(self) -> tuple[str, str]:
        source_var = getattr(self, "placement_dwg_path_var", None)
        cad_var = getattr(self, "placement_cad_var", None)
        source_path = str(source_var.get() if source_var else "").strip()
        selected_name = str(cad_var.get() if cad_var else "").strip()
        if source_path:
            return source_path, Path(source_path).stem or selected_name or "cad2bim_mapping"
        return "", selected_name or "cad2bim_mapping"

    def _save_placement_mapping(self) -> None:
        mappings = getattr(self, "placement_mapping_data", {})
        if not mappings:
            messagebox.showerror("\u7121\u6cd5\u5132\u5b58", "\u76ee\u524d\u9084\u6c92\u6709 CAD \u5716\u584a\u5c0d\u7167")
            return
        source_path, source_name = self._get_placement_mapping_source()
        output_name = filedialog.asksaveasfilename(
            title="\u5132\u5b58 CAD2BIM \u5c0d\u7167\u6a94",
            initialdir=str(default_mapping_dir()),
            initialfile=safe_mapping_file_name(source_name),
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("\u6240\u6709\u6a94\u6848", "*.*")],
        )
        if not output_name:
            return
        try:
            save_mapping_file(
                output_name,
                source_path=source_path,
                source_name=source_name,
                mappings=mappings,
                block_counts=getattr(self, "placement_block_counts", {}),
            )
        except Exception as exc:
            messagebox.showerror("\u5132\u5b58\u5931\u6557", str(exc))
            return
        self.placement_status_var.set(f"CAD2BIM mapping saved: {output_name}")
        messagebox.showinfo("\u5132\u5b58\u5b8c\u6210", f"\u5df2\u5132\u5b58\uff1a\n{output_name}")

    def _load_placement_mapping(self) -> None:
        block_counts = getattr(self, "placement_block_counts", {})
        if not block_counts:
            messagebox.showerror("\u7121\u6cd5\u8f09\u5165", "\u8acb\u5148\u8b80\u53d6 CAD \u5716\u584a")
            return
        input_name = filedialog.askopenfilename(
            title="\u8f09\u5165 CAD2BIM \u5c0d\u7167\u6a94",
            initialdir=str(default_mapping_dir()),
            filetypes=[("JSON", "*.json"), ("\u6240\u6709\u6a94\u6848", "*.*")],
        )
        if not input_name:
            return
        try:
            document = load_mapping_file(input_name)
            matched = filter_mappings_for_blocks(document.get("mappings", {}), block_counts)
        except Exception as exc:
            messagebox.showerror("\u8f09\u5165\u5931\u6557", str(exc))
            return
        if not matched:
            messagebox.showwarning(
                "\u6c92\u6709\u53ef\u7528\u5c0d\u7167",
                "\u5c0d\u7167\u6a94\u8207\u76ee\u524d CAD \u5716\u584a\u540d\u7a31\u6c92\u6709\u5339\u914d",
            )
            return
        self.placement_mapping_data.update(matched)
        self._render_placement_mapping_tree()
        self.placement_status_var.set(f"Loaded {len(matched)} CAD2BIM mappings from {input_name}")
        messagebox.showinfo("\u8f09\u5165\u5b8c\u6210", f"\u5df2\u8f09\u5165 {len(matched)} \u7b46\u5c0d\u7167")

    def _get_selected_mapping(self) -> dict | None:
        block_name = self._get_selected_block_name()
        if not block_name:
            return None
        return getattr(self, "placement_mapping_data", {}).get(block_name)

    def _get_selected_block_name(self) -> str:
        tree = getattr(self, "placement_mapping_tree", None)
        if tree:
            selection = tree.selection()
            if selection:
                return str(selection[0])
        return ""

    def _preview_cad_blocks(self) -> None:
        import_id, _symbol_id, _level_id = self._get_selected_placement_ids()
        if not import_id:
            messagebox.showerror("無法預覽", "請先讀取目前專案資料並選擇 CAD 來源")
            return
        mapping = self._get_selected_mapping()
        if not mapping:
            messagebox.showerror("無法預覽", "請先選取 CAD 圖塊，並套用 Revit 族群對照")
            return
        block_name = self._get_selected_block_name()
        if not block_name:
            messagebox.showerror("無法預覽", "請先選擇 CAD 圖塊名稱")
            return
        points = self._build_dwg_points_for_selected_block(limit=None)
        if not points:
            messagebox.showerror("無法預覽", "選定的 DWG 圖塊沒有可用點位")
            return
        self.placement_preview_block_name = block_name
        self.placement_status_var.set("產生螢光預覽點中…")
        threading.Thread(
            target=self._preview_cad_blocks_worker,
            args=(
                import_id,
                str(mapping.get("level_id")),
                points,
                float(mapping.get("offset_mm") or 0),
            ),
            daemon=True,
        ).start()

    def _preview_cad_blocks_worker(self, import_id: str, level_id: str, points: list[dict], offset_mm: float) -> None:
        try:
            with batch_context("cad_points", "create_preview_markers", "Create CAD preview markers", {"point_count": len(points)}):
                payload = request_create_dwg_preview_markers(
                    import_id=import_id,
                    level_id=level_id,
                    points=points,
                    offset_mm=offset_mm,
                    marker_size_mm=180,
                )
        except Exception as exc:
            self.after(0, lambda: self._finish_cad_preview_error(exc))
            return
        self.after(0, lambda: self._finish_cad_preview(payload))

    def _build_dwg_points_for_selected_block(self, limit: int | None = None) -> list[dict]:
        block_name = self._get_selected_block_name()
        result = getattr(self, "placement_dwg_result", None)
        if not block_name or not result:
            return []
        unit_choice = self.placement_dwg_unit_var.get()
        unit_override = DWG_UNIT_TO_FEET.get(unit_choice)
        scale = float(unit_override if unit_override is not None else result.get("unit_to_feet") or 1.0)
        points = []
        for point in result.get("points", []):
            if point.get("block_name") != block_name:
                continue
            points.append(
                {
                    "block_name": point.get("block_name", ""),
                    "x": float(point.get("x") or 0) * scale,
                    "y": float(point.get("y") or 0) * scale,
                    "z": float(point.get("z") or 0) * scale,
                    "rotation_degrees": float(point.get("rotation_degrees") or 0),
                    "layer": point.get("layer", ""),
                    "handle": point.get("handle", ""),
                }
            )
            if limit and len(points) >= limit:
                break
        return points

    def _finish_cad_preview_error(self, exc: Exception) -> None:
        self.placement_status_var.set("預覽失敗")
        messagebox.showerror("CAD 圖塊預覽失敗", str(exc))

    def _finish_cad_preview(self, payload: dict) -> None:
        self.placement_preview = payload
        self.placement_preview_marker = payload
        self._clear_placement_preview_tree()
        points = list(payload.get("points", []))
        self.placement_status_var.set(
            f"已產生螢光預覽點｜共 {payload.get('marker_count', len(points))} 點。請在 Revit 圖面移動整個預覽群組校正位置。"
        )

    def _place_preview_points(self) -> None:
        import_id, _symbol_id, _level_id = self._get_selected_placement_ids()
        if not import_id:
            messagebox.showerror("無法放置", "請先選擇 CAD 來源")
            return
        mapping = self._get_selected_mapping()
        if not mapping:
            messagebox.showerror("無法放置", "請先選取 CAD 圖塊，並套用 Revit 族群對照")
            return
        if not self.placement_preview:
            messagebox.showerror("無法放置", "請先執行預覽，確認點位後再放置")
            return
        block_name = self._get_selected_block_name()
        if not block_name:
            messagebox.showerror("無法放置", "請先選擇 CAD 圖塊名稱")
            return
        if getattr(self, "placement_preview_block_name", "") != block_name:
            messagebox.showerror("無法放置", "目前預覽資料不是選取圖塊，請重新預覽後再放置")
            return
        points = self._build_dwg_points_for_selected_block(limit=None)
        if not points:
            messagebox.showerror("無法放置", "選定的 DWG 圖塊沒有可用點位")
            return
        try:
            tolerance_mm = float(self.placement_tolerance_var.get() or 10)
        except ValueError:
            messagebox.showerror("無法放置", "防重複距離必須是數字")
            return
        if not messagebox.askyesno(
            "確認放置全部點位",
            f"此操作會在目前 Revit 專案中放置「{block_name}」全部 {len(points)} 筆族群實例，並建立一個 Revit 群組方便選取。\n\n確定要繼續？",
        ):
            return
        self.placement_status_var.set("放置測試中…")
        threading.Thread(
            target=self._place_preview_points_worker,
            args=(
                import_id,
                str(mapping.get("symbol_id")),
                str(mapping.get("level_id")),
                points,
                float(mapping.get("offset_mm") or 0),
                tolerance_mm,
                getattr(self, "placement_preview_marker", {}),
            ),
            daemon=True,
        ).start()

    def _place_preview_points_worker(
        self,
        import_id: str,
        symbol_id: str,
        level_id: str,
        points: list[dict],
        offset_mm: float,
        tolerance_mm: float,
        preview_marker: dict | None = None,
    ) -> None:
        try:
            with batch_context("cad_points", "place_blocks", "Place CAD block points", {"point_count": len(points), "symbol_id": symbol_id}):
                payload = request_place_dwg_blocks(
                    import_id=import_id,
                    symbol_id=symbol_id,
                    level_id=level_id,
                    points=points,
                    offset_mm=offset_mm,
                    duplicate_tolerance_mm=tolerance_mm,
                    preview_group_id=(preview_marker or {}).get("group_id"),
                    preview_origin=(preview_marker or {}).get("group_origin"),
                    delete_preview_after_place=True,
                )
        except Exception as exc:
            self.after(0, lambda: self._finish_place_preview_error(exc))
            return
        self.after(0, lambda: self._finish_place_preview(payload))

    def _finish_place_preview_error(self, exc: Exception) -> None:
        self.placement_status_var.set("放置失敗")
        messagebox.showerror("批量點位放置失敗", str(exc))

    def _finish_place_preview(self, payload: dict) -> None:
        created = list(payload.get("created", []))
        duplicates = list(payload.get("duplicates", []))
        failed = list(payload.get("failed", []))
        self.placement_status_var.set(
            f"放置完成｜Created {len(created)}｜Duplicate {len(duplicates)}｜Failed {len(failed)}｜Batch {payload.get('batch_id', '')}"
        )
        lines = [
            f"Created：{len(created)}",
            f"Duplicate：{len(duplicates)}",
            f"Failed：{len(failed)}",
            f"Batch ID：{payload.get('batch_id', '')}",
        ]
        if payload.get("group_name"):
            lines.append(f"群組：{payload.get('group_name')}")
        if failed:
            lines.extend(["", "失敗原因："])
            lines.extend(
                f"- {item.get('block_name', '')}：{item.get('reason', '')}"
                for item in failed[:10]
            )
        messagebox.showinfo("批量點位放置完成", "\n".join(lines))

    def _scan_project_families(self) -> None:
        self.project_scan_var.set("掃描中…")
        for item in self.project_family_tree.get_children():
            self.project_family_tree.delete(item)
        threading.Thread(target=self._scan_project_families_worker, daemon=True).start()

    def _scan_project_families_worker(self) -> None:
        try:
            with batch_context("project_recovery", "scan_families", "Scan project families"):
                payload = request_project_family_scan()
        except Exception as exc:
            self.after(0, lambda: self._finish_project_scan_error(exc))
            return
        self.after(0, lambda: self._finish_project_scan(payload))

    def _finish_project_scan_error(self, exc: Exception) -> None:
        self.project_scan_var.set("掃描失敗")
        messagebox.showerror("專案回收掃描失敗", str(exc))

    def _finish_project_scan(self, payload: dict) -> None:
        self.project_scan_result = payload
        families = list(payload.get("families", []))
        families.sort(
            key=lambda item: (
                not bool(item.get("is_used")),
                not bool(item.get("can_recover")),
                str(item.get("revit_category", "")),
                str(item.get("family_name", "")),
            )
        )
        for item in self.project_family_tree.get_children():
            self.project_family_tree.delete(item)
        self.project_families_by_iid = {}
        for index, family in enumerate(families):
            can_recover = bool(family.get("can_recover"))
            is_used = bool(family.get("is_used"))
            tag = "blocked"
            if can_recover and is_used:
                tag = "recoverable"
            elif can_recover:
                tag = "unused"
            iid = str(index)
            self.project_families_by_iid[iid] = family
            self.project_family_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    family.get("family_name", ""),
                    family.get("revit_category", ""),
                    family.get("instance_count", 0),
                    family.get("symbol_count", 0),
                    family.get("status", ""),
                ),
                tags=(tag,),
            )
        used_count = sum(1 for item in families if item.get("is_used"))
        recoverable_count = sum(1 for item in families if item.get("can_recover"))
        self.project_scan_var.set(
            f"{payload.get('project_title', '目前專案')}｜共 {len(families)} 個族群｜已使用 {used_count}｜可回收 {recoverable_count}"
        )

    def _select_recoverable_project_families(self) -> None:
        recoverable = [
            iid
            for iid, item in self.project_families_by_iid.items()
            if item.get("can_recover")
        ]
        self.project_family_tree.selection_set(recoverable)

    def _export_selected_project_families(self) -> None:
        selected = list(self.project_family_tree.selection())
        family_ids = [
            self.project_families_by_iid[iid].get("family_id")
            for iid in selected
            if self.project_families_by_iid.get(iid, {}).get("can_recover")
        ]
        if not family_ids:
            messagebox.showerror("無法匯出", "請先選擇至少一個可回收族群")
            return
        try:
            output_dir = get_project_recovery_dir(self.library_root)
        except Exception as exc:
            messagebox.showerror("無法匯出", str(exc))
            return
        self.project_scan_var.set(f"匯出中… 目標：{output_dir}")
        threading.Thread(
            target=self._export_project_families_worker,
            args=(family_ids, str(output_dir)),
            daemon=True,
        ).start()

    def _export_project_families_worker(self, family_ids: list[int | str], output_dir: str) -> None:
        try:
            with batch_context("project_recovery", "export_families", "Export project families", {"family_count": len(family_ids)}):
                payload = request_project_family_export(family_ids, output_dir)
        except Exception as exc:
            self.after(0, lambda: self._finish_project_export_error(exc))
            return
        self.after(0, lambda: self._finish_project_export(payload))

    def _finish_project_export_error(self, exc: Exception) -> None:
        self.project_scan_var.set("匯出失敗")
        messagebox.showerror("專案族群匯出失敗", str(exc))

    def _finish_project_export(self, payload: dict) -> None:
        exported = list(payload.get("exported", []))
        skipped = list(payload.get("skipped", []))
        self.project_scan_var.set(
            f"匯出完成｜成功 {len(exported)}｜略過 {len(skipped)}｜{payload.get('output_dir', '')}"
        )
        lines = [f"成功匯出 {len(exported)} 顆族群到：", str(payload.get("output_dir", ""))]
        if exported:
            lines.extend(["", "匯出檔案："])
            lines.extend(f"- {item.get('file_name', '')}" for item in exported[:20])
        if skipped:
            lines.extend(["", "略過："])
            lines.extend(
                f"- {item.get('family_name', '')}：{item.get('reason', '')}"
                for item in skipped[:20]
            )
        messagebox.showinfo("專案族群匯出完成", "\n".join(lines))

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="選擇 RFA",
            filetypes=[("Revit Family", "*.rfa")],
        )
        self._add_rfa_paths(paths)
        self._update_summary()

    def _import_from_project_recovery(self) -> None:
        try:
            recovery_dir = get_project_recovery_dir(self.library_root)
        except Exception as exc:
            messagebox.showerror("無法匯入", str(exc))
            return

        paths = sorted(recovery_dir.glob("*.rfa"))
        if not paths:
            messagebox.showinfo(
                "沒有可匯入族群",
                f"專案回收暫存區目前沒有 RFA：\n{recovery_dir}",
            )
            return

        added = self._add_rfa_paths(paths)
        self._update_summary()
        if added:
            self.tree.selection_set([str(path) for path in added])
            self.tree.see(str(added[0]))
        messagebox.showinfo(
            "匯入完成",
            f"已從專案回收暫存區匯入 {len(added)} 顆族群。\n\n"
            "接下來可直接按「開始分類」接續入庫流程。",
        )

    def _add_rfa_paths(self, paths) -> list[Path]:
        added: list[Path] = []
        for raw_path in paths:
            path = Path(raw_path)
            if path.suffix.casefold() != ".rfa":
                continue
            key = str(path)
            if key in self.tasks:
                continue
            task = RfaTask(path=path)
            task.planned_name = generate_planned_name(str(path))
            self.tasks[key] = task
            self.tree.insert(
                "",
                "end",
                iid=key,
                values=(task.file_name, task.planned_name or "", task.status, ""),
            )
            added.append(path)
        return added

    def _selected_keys(self, default_all_when_empty: bool = True) -> list[str]:
        selected = list(self.tree.selection())
        if selected:
            return selected
        return list(self.tasks.keys()) if default_all_when_empty else []

    def _classify_selected(self) -> None:
        keys = self._selected_keys()
        self.total_tasks = len(keys)
        self.finished_tasks = 0
        self.progress.configure(maximum=max(self.total_tasks, 1), value=0)
        self._update_summary()
        batch = BatchStore().start_batch("family_library", "classify_rfa", "Classify RFA files", {"file_count": len(keys)})
        self.current_classify_batch_id = batch.batch_id
        for key in keys:
            task = self.tasks[key]
            task.status = "等待 Revit"
            self._refresh_row(key)
            threading.Thread(target=self._classify_task, args=(key, batch.batch_id), daemon=True).start()

    def _classify_task(self, key: str, batch_id: str | None = None) -> None:
        task = self.tasks[key]
        try:
            with activate_batch(batch_id):
                result = classify_rfa_via_revit(str(task.path))
                task.result = result
                if not task.planned_name_manual:
                    source_metadata = result.get("source_metadata", {})
                    analysis = analyze_source_name(source_metadata.get("family_name") or task.file_name)
                    task.base_name = analysis.base_name
                    task.suffix_options = [
                        {"category": item.category, "value": item.value, "selected": item.selected}
                        for item in analysis.suffixes
                    ]
                    task.planned_name = generate_planned_name(
                        str(task.path),
                        system=result.get("system"),
                        family_name=source_metadata.get("family_name"),
                        editable_name=task.base_name,
                        suffixes=[
                            str(item["value"])
                            for item in task.suffix_options
                            if item["selected"]
                        ],
                    )
                    self._refresh_duplicate_result(task)
                task.status = {
                    "classified": "已分類",
                    "suggest_review": "需確認",
                    "needs_review": "待審核",
                }.get(result["status"], result["status"])
        except Exception as exc:
            task.error = str(exc)
            task.status = "失敗"
        self.after(0, lambda: self._finish_task(key))

    def _finish_task(self, key: str) -> None:
        self.finished_tasks += 1
        self.progress.configure(value=self.finished_tasks)
        self._refresh_row(key)
        self._update_summary()
        if getattr(self, "current_classify_batch_id", None) and self.finished_tasks >= self.total_tasks:
            has_error = any(task.status == "失敗" for task in self.tasks.values())
            BatchStore().finish_batch(
                self.current_classify_batch_id,
                "failed" if has_error else "success",
                {"total": self.total_tasks, "failed": sum(1 for task in self.tasks.values() if task.status == "失敗")},
            )
            self.current_classify_batch_id = None

    def _refresh_row(self, key: str) -> None:
        task = self.tasks[key]
        classification = ""
        if task.result:
            classification = task.approved_path or task.result.get("path", "")
        self.tree.item(
            key,
            values=(task.file_name, task.planned_name or "", task.status, classification),
        )
        tag = "waiting"
        if task.status == "已分類":
            tag = "done"
        elif task.status == "已入庫":
            tag = "done"
        elif task.status == "已入庫待修正":
            tag = "review"
        elif task.status == "人工審核完成":
            tag = "done"
        elif task.status in {"需確認", "待審核"}:
            tag = "review"
        elif task.status == "失敗":
            tag = "error"
        self.tree.item(key, tags=(tag,))

    def _show_selected_detail(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        task = self.tasks[selection[0]]
        self.detail_text.delete("1.0", tk.END)
        lines = [
            f"檔名：{task.file_name}",
            f"預計修改名稱：{task.planned_name or ''}",
            f"狀態：{task.status}",
        ]
        if task.error:
            lines.append(f"錯誤：{task.error}")
        if task.result:
            lines.extend(
                [
                    f"建議路徑：{task.result.get('path', '')}",
                    f"人工改選路徑：{task.approved_path or ''}",
                    f"系統別：{task.result.get('system', '')}",
                    f"信心分數：{task.result.get('score', '')}",
                    f"已入庫位置：{task.ingested_path or ''}",
                    "",
                    "命中依據：",
                    str(task.result.get("matched", {})),
                ]
            )
        if task.standardization_result:
            lines.extend(
                [
                    "",
                    "公司標準寫入：",
                    f"新增參數：{', '.join(task.standardization_result.get('added_parameters', [])) or '無'}",
                    f"更新參數：{', '.join(task.standardization_result.get('updated_parameters', [])) or '無'}",
                ]
            )
        self.override_var.set(
            task.approved_path
            or ((task.result or {}).get("path", ""))
            or ""
        )
        self.base_name_var.set(task.base_name or "")
        self._render_suffix_options(task)
        self.planned_name_var.set(task.planned_name or "")
        self._render_duplicate_result(task)
        self._render_standard_preview(task)
        self.detail_text.insert("1.0", "\n".join(lines))

    def _apply_override(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        task = self.tasks[selection[0]]
        task.approved_path = self.override_var.get().strip() or None
        if task.status in {"待審核", "需確認", "人工審核完成"}:
            self._auto_apply_manual_review_name(task)
        self._maybe_mark_manual_review_done(task)
        self._refresh_row(selection[0])
        self._show_selected_detail()

    def _infer_system_from_relative_path(self, relative_path: str | None) -> str | None:
        if not relative_path:
            return None
        normalized = relative_path.replace("/", "\\")
        for code in ("HVAC", "PLB", "FP", "PWR", "LTG", "ELV", "ARC", "STR", "DRW"):
            if f" {code} " in normalized or normalized.endswith(f" {code}") or f"\\{code} " in normalized:
                return code
        return None

    def _ensure_naming_basis(self, task: RfaTask) -> None:
        if not task.base_name:
            analysis = analyze_source_name(task.file_name)
            task.base_name = analysis.base_name
            if not task.suffix_options:
                task.suffix_options = [
                    {"category": item.category, "value": item.value, "selected": item.selected}
                    for item in analysis.suffixes
                ]

    def _auto_apply_manual_review_name(self, task: RfaTask) -> None:
        if not task.approved_path:
            return
        if task.result is None:
            task.result = {}
        task.result["path"] = task.approved_path
        inferred_system = self._infer_system_from_relative_path(task.approved_path)
        if inferred_system:
            task.result["system"] = inferred_system
        self._ensure_naming_basis(task)
        task.base_name = self.base_name_var.get().strip() or task.base_name
        self._sync_suffix_selection(task)
        source_metadata = task.result.get("source_metadata", {})
        task.planned_name = generate_planned_name(
            str(task.path),
            system=task.result.get("system"),
            family_name=source_metadata.get("family_name"),
            editable_name=task.base_name,
            suffixes=[
                str(item["value"])
                for item in task.suffix_options
                if item["selected"]
            ],
        )
        task.planned_name_manual = True
        self._refresh_duplicate_result(task)

    def _maybe_mark_manual_review_done(self, task: RfaTask) -> None:
        if task.status not in {"待審核", "需確認", "人工審核完成"}:
            return
        if not task.approved_path:
            return
        if not task.planned_name:
            return
        task.status = "人工審核完成"

    def _apply_planned_name(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        task = self.tasks[selection[0]]
        candidate = self.planned_name_var.get().strip()
        if not candidate:
            messagebox.showerror("名稱錯誤", "預計修改名稱不可為空白")
            return
        if not candidate.casefold().endswith(".rfa"):
            candidate += ".rfa"
        task.base_name = self.base_name_var.get().strip() or task.base_name
        self._sync_suffix_selection(task)
        task.planned_name = candidate
        task.planned_name_manual = True
        self._maybe_mark_manual_review_done(task)
        self._refresh_duplicate_result(task)
        self._refresh_row(selection[0])
        self._show_selected_detail()

    def _render_suffix_options(self, task: RfaTask) -> None:
        for child in self.suffix_frame.winfo_children():
            child.destroy()
        self.suffix_vars = []
        if not task.suffix_options:
            ttk.Label(self.suffix_frame, text="未辨識到可選後綴").grid(row=0, column=0, sticky="w")
            return

        ordered = sorted(
            task.suffix_options,
            key=lambda item: (
                SUFFIX_ORDER.index(str(item["category"]))
                if str(item["category"]) in SUFFIX_ORDER
                else len(SUFFIX_ORDER),
                str(item["value"]),
            ),
        )
        for row, item in enumerate(ordered):
            var = tk.BooleanVar(value=bool(item["selected"]))
            category = str(item["category"])
            value = str(item["value"])
            ttk.Checkbutton(
                self.suffix_frame,
                text=f"{category}：{value}",
                variable=var,
                command=self._preview_planned_name,
            ).grid(row=row, column=0, sticky="w")
            self.suffix_vars.append((category, value, var))

    def _sync_suffix_selection(self, task: RfaTask) -> None:
        selected_map = {(category, value): var.get() for category, value, var in self.suffix_vars}
        for item in task.suffix_options:
            key = (str(item["category"]), str(item["value"]))
            if key in selected_map:
                item["selected"] = selected_map[key]

    def _preview_planned_name(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        task = self.tasks[selection[0]]
        if not task.result:
            return
        self._sync_suffix_selection(task)
        source_metadata = task.result.get("source_metadata", {})
        preview = generate_planned_name(
            str(task.path),
            system=task.result.get("system"),
            family_name=source_metadata.get("family_name"),
            editable_name=self.base_name_var.get().strip() or task.base_name,
            suffixes=[
                str(item["value"])
                for item in task.suffix_options
                if item["selected"]
            ],
        )
        self.planned_name_var.set(preview)
        task.planned_name = preview
        task.planned_name_manual = False
        self._refresh_duplicate_result(task)
        self.planned_name_var.set(task.planned_name or "")
        self._refresh_row(selection[0])

    def _refresh_duplicate_result(self, task: RfaTask) -> None:
        if not task.planned_name:
            return
        result = find_duplicate_names(self.library_root, task.file_name, task.planned_name)
        result["duplicate_exists"] = (
            result["original_name_exists"] or result["planned_name_exists"]
        )
        if result["duplicate_exists"]:
            task.planned_name = build_available_copy_name(
                self.library_root,
                task.planned_name,
                force_copy=True,
            )
            result["renamed_to"] = task.planned_name
        task.duplicate_result = result

    def _render_duplicate_result(self, task: RfaTask) -> None:
        for item in self.duplicate_preview.get_children():
            self.duplicate_preview.delete(item)
        result = task.duplicate_result
        if not result:
            return
        for path in result.get("original_matches", []):
            self.duplicate_preview.insert(
                "",
                "end",
                values=(Path(path).name, "同原檔名", "已存在"),
            )
        for path in result.get("planned_matches", []):
            self.duplicate_preview.insert(
                "",
                "end",
                values=(Path(path).name, "同預計名稱", "自動改名"),
            )

    def _render_standard_preview(self, task: RfaTask) -> None:
        self.standard_text.delete("1.0", tk.END)
        if not task.result:
            self.standard_text.insert("1.0", "尚未完成分類，無法建立標準化預覽。")
            return
        metadata = task.result.get("source_metadata", {})
        preview = build_parameter_preview(
            metadata.get("family_parameters", []),
            task.result.get("system"),
            metadata.get("family_parameter_details", []),
        )
        lines = [
            f"套用模板：{'、'.join(preview['templates']) or '無'}",
            f"現有參數數量：{preview['existing_count']}",
            "",
            "已存在的標準參數：",
        ]
        lines.extend(f"- {item['name']}" for item in preview["present"])
        lines.extend(["", "缺少的標準參數："])
        lines.extend(
            f"- {item['name']}{'（必填）' if item.get('required') else ''}"
            for item in preview["missing"]
        )
        lines.extend(["", "屬性不符："])
        if preview["mismatches"]:
            lines.extend(
                f"- {item['name']}｜{item['issue']}｜預期 {item['expected']}｜目前 {item['actual']}"
                for item in preview["mismatches"]
            )
        else:
            lines.append("- 無")
        lines.extend(["", "變更草案：", "新增："])
        if preview["actions"]["add"]:
            lines.extend(
                f"- {item['name']}{'（必填）' if item.get('required') else ''}"
                for item in preview["actions"]["add"]
            )
        else:
            lines.append("- 無")
        lines.append("修改：")
        if preview["actions"]["modify"]:
            lines.extend(
                f"- {item['name']}｜{item['reason']}｜{item['actual']} → {item['expected']}"
                for item in preview["actions"]["modify"]
            )
        else:
            lines.append("- 無")
        lines.append("保留：")
        if preview["actions"]["keep"]:
            lines.extend(f"- {item['name']}" for item in preview["actions"]["keep"])
        else:
            lines.append("- 無")
        if preview["parameter_details"]:
            lines.extend(["", "現有參數明細："])
            for item in preview["parameter_details"][:20]:
                kind = "實例" if item.get("is_instance") else "類型"
                lines.append(
                    f"- {item.get('name', '')}｜{kind}｜{item.get('storage_type', '')}｜{item.get('parameter_group', '')}"
                )
        self.standard_text.insert("1.0", "\n".join(lines))

    def _get_selected_ingested_task(self) -> RfaTask | None:
        selection = self.tree.selection()
        if not selection:
            return None
        task = self.tasks[selection[0]]
        if not task.ingested_path:
            messagebox.showerror("尚未入庫", "只允許修改正式入庫後的複製檔。")
            return None
        if not task.result:
            return None
        return task

    def _apply_company_standard(self) -> None:
        task = self._get_selected_ingested_task()
        if not task:
            return
        try:
            added_result, value_result = self._apply_company_standard_to_task(task)
        except Exception as exc:
            messagebox.showerror("套用公司標準失敗", str(exc))
            return
        self._show_selected_detail()
        messagebox.showinfo(
            "套用公司標準完成",
            "已新增：\n"
            + ("\n".join(added_result.get("added_parameters", [])) or "無")
            + "\n\n已更新：\n"
            + ("\n".join(value_result.get("updated_parameters", [])) or "無"),
        )

    def _apply_company_standard_to_task(self, task: RfaTask) -> tuple[dict, dict]:
        metadata = task.result.get("source_metadata", {})
        preview = build_parameter_preview(
            metadata.get("family_parameters", []),
            task.result.get("system"),
            metadata.get("family_parameter_details", []),
        )
        safe_names = [item["name"] for item in preview["actions"]["safe_add"]]
        added_result = (
            request_add_missing_string_parameters(task.ingested_path, safe_names)
            if safe_names
            else {"added_parameters": []}
        )
        values = build_safe_text_values(
            system=task.result.get("system"),
            base_name=task.base_name,
            source_file_name=task.file_name,
        )
        value_result = request_set_string_parameter_values(task.ingested_path, values)
        task.result = refresh_result_metadata_via_revit(
            task.result,
            task.ingested_path,
        )
        refreshed_parameters = set(
            task.result.get("source_metadata", {}).get("family_parameters", [])
        )
        expected_written = set(safe_names) | set(values.keys())
        missing_after_write = sorted(expected_written - refreshed_parameters)
        if missing_after_write:
            raise RuntimeError(
                "公司標準參數寫入後未在 RFA 中讀回："
                + "、".join(missing_after_write)
            )
        task.standardization_result = {
            "added_parameters": list(added_result.get("added_parameters", [])),
            "updated_parameters": list(value_result.get("updated_parameters", [])),
        }
        return added_result, value_result

    def _choose_override_folder(self) -> None:
        if not self.library_root:
            return
        picker = tk.Toplevel(self)
        picker.title("選擇資料夾")
        picker.geometry("520x520")
        picker.transient(self)
        picker.grab_set()

        tree = ttk.Treeview(picker)
        tree.pack(fill="both", expand=True, padx=12, pady=12)

        root = Path(self.library_root)
        item_by_path: dict[Path, str] = {}
        for path in sorted([root] + [p for p in root.rglob("*") if p.is_dir()]):
            parent = "" if path == root else item_by_path[path.parent]
            label = path.name if path != root else root.name
            item_by_path[path] = tree.insert(parent, "end", text=label, open=True)

        def apply_selection() -> None:
            selected = tree.selection()
            if not selected:
                return
            reverse = {item: path for path, item in item_by_path.items()}
            chosen = reverse[selected[0]]
            if chosen == root:
                return
            self.override_var.set(str(chosen.relative_to(root)).replace("/", "\\"))
            picker.destroy()

        ttk.Button(picker, text="選擇", command=apply_selection).pack(pady=(0, 12))

    def _mark_for_review(self) -> None:
        for key in self._selected_keys():
            task = self.tasks[key]
            task.status = "待審核"
            if task.result is None:
                task.result = {"path": "03 管理區\\01 新上傳待審核"}
            self._refresh_row(key)
        self._update_summary()

    def _ingest_selected(self) -> None:
        keys = self._selected_keys(default_all_when_empty=False)
        if not keys:
            messagebox.showerror("無法入庫", "請先選擇要加入族群庫的族群；若要批次處理請先按「全選」。")
            return
        success_count = 0
        errors: list[str] = []
        for key in keys:
            task = self.tasks[key]
            if not task.result:
                errors.append(f"{task.file_name}：尚未完成分類")
                continue
            if task.status in {"待審核", "需確認", "失敗"}:
                errors.append(f"{task.file_name}：目前狀態不可直接入庫")
                continue
            relative_folder = task.approved_path or task.result.get("path")
            try:
                ingest = ingest_copy_only(
                    str(task.path),
                    self.library_root,
                    relative_folder,
                    task.planned_name,
                )
            except IngestError as exc:
                errors.append(f"{task.file_name}：{exc}")
                continue
            task.planned_name = ingest.final_name
            task.ingested_path = str(ingest.destination_path)
            standardization_failed = False
            try:
                self._apply_company_standard_to_task(task)
            except Exception as exc:
                errors.append(f"{task.file_name}：已入庫，但套用公司標準失敗：{exc}")
                standardization_failed = True
            record_ingest(
                library_root=self.library_root,
                source_path=str(task.path),
                final_path=str(ingest.destination_path),
                result=task.result,
                base_name=task.base_name,
                suffix_options=task.suffix_options,
                approved_path=task.approved_path,
                planned_name_manual=task.planned_name_manual,
                duplicate_result=task.duplicate_result,
            )
            task.status = "已入庫待修正" if standardization_failed else "已入庫"
            self._refresh_duplicate_result(task)
            self._refresh_row(key)
            success_count += 1

        self._update_summary()
        if success_count:
            messagebox.showinfo("正式入庫完成", f"已成功入庫 {success_count} 顆族群。")
        if errors:
            messagebox.showwarning("部分族群未入庫", "\n".join(errors[:12]))

    def _export_index(self) -> None:
        if not self.library_root:
            messagebox.showerror("無法匯出", "尚未設定族群庫位置")
            return
        try:
            output_path = export_library_index_xlsx(self.library_root)
        except Exception as exc:
            messagebox.showerror("匯出失敗", str(exc))
            return
        messagebox.showinfo("匯出完成", f"已產生中文索引：\n{output_path}")

    def _select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def _clear_selection(self) -> None:
        self.tree.selection_remove(self.tree.selection())

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for key, task in self.tasks.items():
            if not self._matches_filter(task):
                continue
            classification = task.approved_path or (task.result or {}).get("path", "")
            self.tree.insert(
                "",
                "end",
                iid=key,
                values=(task.file_name, task.planned_name or "", task.status, classification),
            )
            self._refresh_row(key)

    def _matches_filter(self, task: RfaTask) -> bool:
        value = self.visible_filter.get()
        if value == "全部":
            return True
        if value == "等待":
            return task.status in {"等待讀取", "等待 Revit", "讀取中"}
        if value == "已分類":
            return task.status == "已分類"
        if value == "人工審核完成":
            return task.status == "人工審核完成"
        if value == "需確認":
            return task.status in {"需確認", "待審核"}
        if value == "失敗":
            return task.status == "失敗"
        return True

    def _update_summary(self) -> None:
        if not self.tasks:
            self.summary_var.set("尚未加入檔案")
            return
        counts = {
            "已分類": 0,
            "人工審核完成": 0,
            "需確認": 0,
            "待審核": 0,
            "失敗": 0,
        }
        for task in self.tasks.values():
            if task.status in counts:
                counts[task.status] += 1
        self.summary_var.set(
            f"共 {len(self.tasks)} 顆｜已分類 {counts['已分類']}｜人工完成 {counts['人工審核完成']}｜需確認 {counts['需確認'] + counts['待審核']}｜失敗 {counts['失敗']}"
        )


if __name__ == "__main__":
    FamilyClassifierApp().mainloop()
