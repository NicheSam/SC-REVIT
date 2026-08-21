from __future__ import annotations

import os
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Callable

from .network_diagram import (
    build_fire_branch_network_layout,
    write_fire_branch_network_svg,
)
from .topology_plan import revise_topology_plan, validate_topology_plan


MIN_ZOOM_SCALE = 0.35
MAX_ZOOM_SCALE = 4.0
READABLE_ZOOM_SCALE = 1.0


def next_zoom_scale(current: float, direction: int) -> float:
    """Return the next scale without trapping a fitted view below the minimum."""

    current_scale = max(0.01, float(current or 1.0))
    if direction > 0:
        if current_scale < MIN_ZOOM_SCALE:
            return MIN_ZOOM_SCALE
        return min(MAX_ZOOM_SCALE, current_scale * 1.16)
    if current_scale <= MIN_ZOOM_SCALE:
        return current_scale
    return max(MIN_ZOOM_SCALE, current_scale / 1.16)


def semantic_zoom_visibility(scale: float) -> dict[str, bool]:
    """Return which engineering labels remain readable at the current scale."""

    current_scale = max(0.01, float(scale or 1.0))
    # Canvas coordinates scale with the drawing, but Tk font sizes do not need
    # to.  At an overview scale a complete label set is visual noise; at a
    # close scale it becomes useful evidence.  Keep fitting labels out of the
    # drawing until the user has deliberately zoomed in.
    overview = current_scale < 0.92
    detailed = current_scale >= 1.18
    return {
        # Labels are text-only now; keep the key for compatibility with older
        # canvas items but never recreate the large fixed card.
        "diameter_box": False,
        "diameter_text": not overview,
        "segment_detail": detailed,
        # Fitting details appear in the selection panel.  Rendering them at
        # every node overlaps the pipe labels, even on otherwise readable CAD
        # routes.
        "reducer_label": False,
        "junction_label": False,
        "main_label": not overview,
    }


def main_context_render_segments(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the selected main geometry for the Tk canvas.

    The SVG writer already prefers ``main_segments``.  The interactive preview
    must use the same geometry; otherwise an L/U-shaped main is replaced by the
    old synthetic straight guide line and the preview disagrees with the SVG.
    """

    context_segments = [
        dict(item)
        for item in (layout.get("main_segments") or [])
        if isinstance(item, dict)
    ]
    if context_segments:
        return context_segments
    main = layout.get("main")
    return [dict(main)] if isinstance(main, dict) else []


class FireBranchNetworkPreview(tk.Toplevel):
    """Simple pan-and-zoom schematic backed by the same data as the SVG export."""

    def __init__(
        self,
        parent,
        *,
        analysis: dict[str, Any],
        main_diameter_mm: float | None = None,
        batch_id: str = "preview",
        on_focus: Callable[[dict[str, Any]], None] | None = None,
        on_plan_changed: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("消防支管路網圖")
        self.geometry("1100x760")
        self.minsize(760, 520)
        self.transient(parent)
        self._analysis = analysis
        self._main_diameter_mm = main_diameter_mm
        self._on_focus = on_focus
        self._on_plan_changed = on_plan_changed
        initial_plan = analysis.get("topology_plan")
        self._plan_history = [initial_plan] if isinstance(initial_plan, dict) else []
        self._plan_history_index = 0
        self._route_decisions = self._reviewable_route_decisions(
            self._route_decisions_from(analysis)
        )
        self._selected_route_decision_index: int | None = None
        self._route_candidate_labels: dict[str, str] = {}
        self._layout = build_fire_branch_network_layout(
            analysis,
            main_diameter_mm=main_diameter_mm,
        )
        self._sync_canvas_contract_from_layout()
        self._segment_by_id = {
            str(item["segment_id"]): item for item in self._layout["segments"]
        }
        self._scale = 1.0
        self._zoom_percent_var = tk.StringVar(value="100%")
        self._selection_var = tk.StringVar(
            value="目前未選取管段、接頭或異徑。點選圖形後，這裡會顯示可修改的對象。"
        )
        self._plan_validation_var = tk.StringVar(value="計畫檢查：尚未執行")
        self._selected_segment_id: str | None = None
        self._selected_junction_index: int | None = None
        self._selected_reducer_index: int | None = None
        self._pan_origin: tuple[int, int] | None = None
        self._pan_moved = False
        self._saved_copy = False
        self._svg_path = self._create_svg(batch_id)
        cad_verified = bool(self._layout.get("cad_verified"))
        self._status_var = tk.StringVar(
            value=(
                "CAD 路徑未驗證｜本圖僅供示意，不可用於建模｜滑鼠滾輪縮放｜"
                "按住左鍵拖動｜雙擊管段可回到 Revit 定位"
                if not cad_verified
                else "滑鼠滾輪縮放｜按住左鍵拖動｜雙擊管段可回到 Revit 定位"
            )
        )

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(
            toolbar,
            textvariable=self._status_var,
            font=("Microsoft JhengHei UI", 11, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Button(toolbar, text="－", width=3, command=lambda: self._zoom_button(-1)).grid(
            row=0,
            column=1,
            padx=(8, 0),
        )
        ttk.Label(toolbar, textvariable=self._zoom_percent_var, width=6, anchor="center").grid(
            row=0,
            column=2,
        )
        ttk.Button(toolbar, text="＋", width=3, command=lambda: self._zoom_button(1)).grid(
            row=0,
            column=3,
        )
        ttk.Button(toolbar, text="全圖", command=self._fit_to_window).grid(
            row=0,
            column=4,
            padx=(8, 0),
        )
        ttk.Button(toolbar, text="可讀大小", command=self._show_readable_view).grid(
            row=0,
            column=5,
            padx=(8, 0),
        )
        ttk.Button(toolbar, text="另存 SVG", command=self._save_svg).grid(
            row=0,
            column=6,
            padx=(8, 0),
        )
        ttk.Button(toolbar, text="關閉", command=self._close).grid(
            row=0,
            column=7,
            padx=(8, 0),
        )

        editor = ttk.Frame(self, padding=(10, 0, 10, 8))
        editor.grid(row=1, column=0, sticky="ew")
        editor.columnconfigure(0, weight=1)
        self._plan_revision_var = tk.StringVar(value=self._plan_revision_text())
        plan_status = ttk.Frame(editor)
        plan_status.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        plan_status.columnconfigure(0, weight=1)
        ttk.Label(
            plan_status,
            textvariable=self._plan_revision_var,
            font=("Microsoft JhengHei UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            plan_status,
            textvariable=self._selection_var,
            wraplength=680,
            justify="left",
            foreground="#4d5b66",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(
            plan_status,
            textvariable=self._plan_validation_var,
            foreground="#174a63",
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))

        editor_controls = ttk.LabelFrame(editor, text="選取後修正", padding=(8, 5))
        editor_controls.grid(row=1, column=0, sticky="ew")
        editor_controls.columnconfigure(0, weight=1)
        editor_controls.columnconfigure(1, weight=1)
        editor_controls.columnconfigure(2, weight=1)
        diameter_group = ttk.Frame(editor_controls)
        ttk.Label(diameter_group, text="選取管段").grid(row=0, column=0, sticky="w")
        self._edit_diameter_var = tk.StringVar()
        self._edit_diameter_combo = ttk.Combobox(
            diameter_group,
            textvariable=self._edit_diameter_var,
            state="readonly",
            width=9,
            values=["20 mm", "25 mm", "32 mm", "40 mm", "50 mm", "65 mm", "80 mm", "100 mm"],
        )
        self._edit_diameter_combo.grid(row=0, column=1, padx=(6, 0))
        self._apply_edit_button = ttk.Button(
            diameter_group,
            text="修改管徑",
            command=self._apply_segment_diameter,
            state="disabled",
        )
        self._apply_edit_button.grid(row=0, column=2, padx=(6, 0))

        self._editor_groups = {
            "segment": diameter_group,
        }
        self._hide_editor_groups()
        history_row = ttk.Frame(editor)
        history_row.grid(row=2, column=0, sticky="e", pady=(6, 0))
        self._undo_button = ttk.Button(
            history_row, text="復原修正", command=self._undo_plan, state="disabled"
        )
        self._undo_button.grid(row=0, column=0)
        self._redo_button = ttk.Button(
            history_row, text="重做修正", command=self._redo_plan, state="disabled"
        )
        self._redo_button.grid(row=0, column=1, padx=(6, 0))

        canvas_row = 2
        if self._route_decisions:
            route_editor = ttk.LabelFrame(
                self, text="路徑分岔（僅在 CAD 證據不唯一時需要確認）", padding=(8, 6)
            )
            self._route_editor = route_editor
            route_editor.grid(row=2, column=0, sticky="ew")
            route_editor.columnconfigure(1, weight=1)
            route_editor.columnconfigure(3, weight=2)
            ttk.Label(route_editor, text="灑水頭／分岔").grid(row=0, column=0, sticky="w")
            self._route_decision_var = tk.StringVar()
            self._route_decision_combo = ttk.Combobox(
                route_editor,
                textvariable=self._route_decision_var,
                state="readonly",
                width=30,
            )
            self._route_decision_combo.grid(row=0, column=1, sticky="ew", padx=(6, 8))
            self._route_decision_combo.bind(
                "<<ComboboxSelected>>", self._on_route_decision_selected
            )
            ttk.Label(route_editor, text="要連接的主管路徑").grid(row=0, column=2, sticky="w")
            self._route_candidate_var = tk.StringVar()
            self._route_candidate_combo = ttk.Combobox(
                route_editor,
                textvariable=self._route_candidate_var,
                state="readonly",
                width=44,
            )
            self._route_candidate_combo.grid(row=0, column=3, sticky="ew", padx=(6, 8))
            self._apply_route_button = ttk.Button(
                route_editor,
                text="採用路徑",
                command=self._apply_route_candidate,
                state="disabled",
            )
            self._apply_route_button.grid(row=0, column=4)
            canvas_row = 3
            self.rowconfigure(2, weight=0)

        canvas_frame = ttk.Frame(self)
        canvas_frame.grid(row=canvas_row, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)
        self.rowconfigure(canvas_row, weight=1)
        self.canvas = tk.Canvas(
            canvas_frame,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#b7b7b7",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        x_scroll = ttk.Scrollbar(
            canvas_frame,
            orient="horizontal",
            command=self.canvas.xview,
        )
        y_scroll = ttk.Scrollbar(
            canvas_frame,
            orient="vertical",
            command=self.canvas.yview,
        )
        x_scroll.grid(row=1, column=0, sticky="ew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(
            xscrollcommand=x_scroll.set,
            yscrollcommand=y_scroll.set,
        )

        self.canvas.bind("<MouseWheel>", self._zoom)
        self.bind("<MouseWheel>", self._zoom, add="+")
        self.bind("<Control-plus>", lambda _event: self._zoom_button(1))
        self.bind("<Control-minus>", lambda _event: self._zoom_button(-1))
        self.canvas.bind("<ButtonPress-1>", self._pan_start)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._select_canvas_item)
        self.canvas.bind("<Double-1>", self._focus_segment)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._draw()
        self._refresh_route_controls()
        self._check_current_plan()
        self.after(80, self._show_readable_view)

    @property
    def svg_path(self) -> Path:
        return self._svg_path

    def _create_svg(self, batch_id: str) -> Path:
        safe_batch = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in str(batch_id or "preview")
        )
        runtime = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        ) / "RevitFamilyClassifier" / "runtime" / "fire_branch_network"
        return write_fire_branch_network_svg(
            runtime / f"fire_branch_network_{safe_batch}.svg",
            self._analysis,
            main_diameter_mm=self._main_diameter_mm,
        )

    def _draw(self) -> None:
        self.canvas.delete("all")
        main = self._layout["main"]
        for lane in self._layout["row_lanes"]:
            fill = "#fafafa" if int(lane["position"]) % 2 == 0 else "#ffffff"
            self.canvas.create_rectangle(
                lane["x"],
                lane["y"],
                float(lane["x"]) + float(lane["width"]),
                float(lane["y"]) + float(lane["height"]),
                fill=fill,
                outline="#ececec",
                width=1,
                tags=("diagram", "lane"),
            )
            self.canvas.create_text(
                lane["label_x"],
                lane["label_y"],
                anchor="center",
                text=f"{lane['label']}　{lane['segment_count']} 段",
                fill="#666666",
                font=("Microsoft JhengHei UI", 11, "bold"),
                tags=("diagram", "lane", "lane-text"),
            )
        main_width = float(main.get("stroke_width") or 9.0)
        main_segments = main_context_render_segments(self._layout)
        for main_segment in main_segments:
            self.canvas.create_line(
                main_segment["x1"],
                main_segment["y1"],
                main_segment["x2"],
                main_segment["y2"],
                fill="#d7d7d7",
                width=main_width + 4,
                capstyle="round",
                tags=("diagram", "main", "main-casing"),
            )
            self.canvas.create_line(
                main_segment["x1"],
                main_segment["y1"],
                main_segment["x2"],
                main_segment["y2"],
                fill="#34495e",
                width=main_width,
                capstyle="round",
                tags=("diagram", "main", "main-pipe"),
            )
        self.canvas.create_text(
            main["label_x"],
            main["label_y"],
            anchor="w",
            text=main["label"],
            fill="#222222",
            font=("Microsoft JhengHei UI", 12, "bold"),
            tags=("diagram", "main", "main-label"),
        )
        for segment in self._layout["segments"]:
            segment_tag = f"segment:{segment['segment_id']}"
            pipe_tag = f"pipe:{segment['segment_id']}"
            casing_tag = f"casing:{segment['segment_id']}"
            dash = (10, 7) if segment["review_required"] else None
            pipe_width = float(segment["stroke_width"])
            self.canvas.create_line(
                segment["x1"],
                segment["y1"],
                segment["x2"],
                segment["y2"],
                fill="#d0d0d0",
                width=pipe_width + 4,
                dash=dash,
                capstyle="round",
                tags=("diagram", "segment", segment_tag, casing_tag),
            )
            self.canvas.create_line(
                segment["x1"],
                segment["y1"],
                segment["x2"],
                segment["y2"],
                # Use the resolved display colour.  ``color`` is the raw CAD
                # evidence and may be the neutral fallback when CAD matching
                # is incomplete; using it here made every interactive pipe
                # appear grey even when the SVG had diameter colours.
                fill=(
                    segment.get("display_color")
                    or segment.get("color")
                    or "#8a8a8a"
                ),
                width=pipe_width,
                dash=dash,
                capstyle="round",
                tags=("diagram", "segment", segment_tag, pipe_tag),
            )
            center_x = float(segment["label_x"])
            label_y = float(segment["label_y"])
            sequence = int(segment.get("sequence") or 0)
            if segment.get("branch_axis") == "x":
                label_y += -18 if sequence % 2 == 0 else 18
            else:
                center_x += -18 if sequence % 2 == 0 else 18
            self.canvas.create_text(
                center_x,
                label_y - 5,
                text=segment["diameter_label"],
                fill="#a15c00" if segment["review_required"] else "#111111",
                font=("Microsoft JhengHei UI", 10, "bold"),
                tags=("diagram", "segment-label", "diameter-text", segment_tag),
            )
            self.canvas.create_text(
                center_x,
                label_y + 12,
                text=f"{segment['length_label']}｜{segment['evidence_label']}",
                fill="#666666",
                font=("Microsoft JhengHei UI", 8),
                tags=("diagram", "segment-label", "segment-detail", segment_tag),
            )
        for reducer_index, reducer in enumerate(self._layout["reducers"]):
            plan_reducer_index = int(reducer.get("plan_index", reducer_index))
            x = reducer["x"]
            y = reducer["y"]
            lead_x1, lead_y1 = reducer["lead_start"]
            lead_x2, lead_y2 = reducer["lead_end"]
            lead_width = float(reducer["lead_stroke_width"])
            reducer_segment_id = str(reducer["source_segment_id"])
            self.canvas.create_line(
                lead_x1,
                lead_y1,
                lead_x2,
                lead_y2,
                fill="#d0d0d0",
                width=lead_width + 4,
                capstyle="round",
                tags=(
                    "diagram",
                    "reducer",
                    "reducer-lead",
                    f"reducer-lead-casing:{reducer_segment_id}",
                ),
            )
            self.canvas.create_line(
                lead_x1,
                lead_y1,
                lead_x2,
                lead_y2,
                fill=reducer["lead_color"],
                width=lead_width,
                capstyle="round",
                tags=(
                    "diagram",
                    "reducer",
                    "reducer-lead",
                    f"reducer-lead-pipe:{reducer_segment_id}",
                ),
            )
            self.canvas.create_oval(
                x - 15,
                y - 15,
                x + 15,
                y + 15,
                fill="#fff3e0",
                outline="#e57400",
                width=2,
                tags=("diagram", "reducer", f"reducer:{plan_reducer_index}"),
            )
            self.canvas.create_polygon(
                x - 9,
                y - 9,
                x + 9,
                y - 5,
                x + 9,
                y + 5,
                x - 9,
                y + 9,
                fill="#ffffff",
                outline="#b95700",
                width=2,
                tags=("diagram", "reducer", f"reducer:{plan_reducer_index}"),
            )
            self.canvas.create_text(
                x,
                y + 43,
                text=reducer["label"],
                fill="#333333",
                font=("Microsoft JhengHei UI", 9),
                tags=("diagram", "reducer", "reducer-label", f"reducer:{plan_reducer_index}"),
            )
        for segment in self._layout["segments"]:
            if segment.get("is_sprinkler_terminal"):
                self._draw_terminal_marker(segment, f"segment:{segment['segment_id']}")
        # Keep the same rendering contract as: for junction in self._layout["junctions"]
        for junction_index, junction in enumerate(self._layout["junctions"]):
            plan_junction_index = int(junction.get("plan_index", junction_index))
            x = float(junction["x"])
            y = float(junction["y"])
            review = bool(junction["review_required"])
            outline = "#d97706" if review else "#176b54"
            fill = "#fff7df" if review else "#e9f7f1"
            kind = str(junction.get("kind") or "")
            if review:
                title = "待確認四通" if "cross" in kind else "待確認三通"
            elif kind == "reducing_cross":
                title = "異徑四通"
            elif kind == "cross":
                title = "四通"
            elif kind == "reducing_tee":
                title = "異徑三通"
            else:
                title = "三通"
            self.canvas.create_oval(
                x - 12,
                y - 12,
                x + 12,
                y + 12,
                fill=fill,
                outline=outline,
                width=3,
                tags=("diagram", "junction", f"junction:{plan_junction_index}"),
            )
            self.canvas.create_line(
                x - 7,
                y,
                x + 7,
                y,
                fill=outline,
                width=3,
                capstyle="round",
                tags=("diagram", "junction", f"junction:{plan_junction_index}"),
            )
            if "cross" in kind:
                self.canvas.create_line(
                    x,
                    y - 8,
                    x,
                    y + 8,
                    fill=outline,
                    width=3,
                    capstyle="round",
                    tags=("diagram", "junction", f"junction:{plan_junction_index}"),
                )
            junction_label_x = x + 18
            junction_label_y = y - 16 if junction_index % 2 == 0 else y + 28
            junction_anchor = "w"
            if junction_index % 4 == 3:
                junction_label_x = x - 18
                junction_anchor = "e"
            self.canvas.create_text(
                junction_label_x,
                junction_label_y,
                anchor=junction_anchor,
                text=f"{title}｜{str(junction['label'])}",
                fill=outline,
                font=("Microsoft JhengHei UI", 9, "bold"),
                tags=("diagram", "junction", "junction-label", f"junction:{plan_junction_index}"),
            )
        self._draw_orientation_compass()
        self._update_scrollregion()

    def _draw_terminal_marker(self, segment: dict[str, Any], segment_tag: str) -> None:
        x = float(segment["x2"])
        y = float(segment["y2"])
        if segment.get("branch_axis") == "y":
            self.canvas.create_line(
                x,
                y,
                x + 20,
                y,
                fill="#444444",
                width=2,
                tags=("diagram", segment_tag),
            )
            self.canvas.create_oval(
                x + 21,
                y - 9,
                x + 34,
                y + 9,
                fill="#ffffff",
                outline="#333333",
                width=2,
                tags=("diagram", segment_tag),
            )
            return
        self.canvas.create_line(
            x,
            y,
            x,
            y + 20,
            fill="#444444",
            width=2,
            tags=("diagram", segment_tag),
        )
        self.canvas.create_oval(
            x - 9,
            y + 21,
            x + 9,
            y + 34,
            fill="#ffffff",
            outline="#333333",
            width=2,
            tags=("diagram", segment_tag),
        )

    def _draw_orientation_compass(self) -> None:
        orientation = self._layout["orientation"]
        center_x = float(self._layout["width"]) - 58.0
        center_y = 54.0
        for label, color, vector in (
            ("北", "#334e68", orientation["north_screen"]),
            ("東", "#8a5a00", orientation["east_screen"]),
        ):
            dx = float(vector["x"])
            dy = float(vector["y"])
            self.canvas.create_line(
                center_x,
                center_y,
                center_x + dx * 22.0,
                center_y + dy * 22.0,
                fill=color,
                width=2,
                arrow="last",
                tags=("diagram", "orientation"),
            )
            self.canvas.create_text(
                center_x + dx * 32.0,
                center_y + dy * 32.0,
                text=label,
                fill=color,
                font=("Microsoft JhengHei UI", 11, "bold"),
                tags=("diagram", "orientation", "orientation-text"),
            )
            opposite_label = "南" if label == "北" else "西"
            self.canvas.create_text(
                center_x - dx * 32.0,
                center_y - dy * 32.0,
                text=opposite_label,
                fill="#667788",
                font=("Microsoft JhengHei UI", 9, "bold"),
                tags=("diagram", "orientation", "orientation-text"),
            )

    def _zoom(self, event) -> str:
        direction = 1 if event.delta > 0 else -1
        canvas_x = event.x_root - self.canvas.winfo_rootx()
        canvas_y = event.y_root - self.canvas.winfo_rooty()
        self._set_zoom(next_zoom_scale(self._scale, direction), canvas_x, canvas_y)
        return "break"

    def _zoom_button(self, direction: int) -> str:
        self._set_zoom(
            next_zoom_scale(self._scale, direction),
            self.canvas.winfo_width() / 2,
            self.canvas.winfo_height() / 2,
        )
        return "break"

    def _set_zoom(self, target_scale: float, screen_x: float, screen_y: float) -> None:
        current_scale = max(0.01, float(self._scale or 1.0))
        target = max(0.05, min(MAX_ZOOM_SCALE, float(target_scale)))
        if abs(target - current_scale) <= 0.000001:
            return
        factor = target / current_scale
        x = self.canvas.canvasx(screen_x)
        y = self.canvas.canvasy(screen_y)
        self.canvas.scale("diagram", x, y, factor, factor)
        self._scale = target
        self._refresh_scaled_styles()
        self._apply_semantic_zoom()
        self._update_scrollregion()

    def _pan_start(self, event) -> None:
        self._pan_origin = (event.x, event.y)
        self._pan_moved = False
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event) -> None:
        if self._pan_origin is not None:
            dx = abs(event.x - self._pan_origin[0])
            dy = abs(event.y - self._pan_origin[1])
            self._pan_moved = self._pan_moved or dx >= 4 or dy >= 4
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _focus_segment(self, _event) -> str:
        current = self.canvas.find_withtag("current")
        if not current:
            return "break"
        segment_id = None
        junction_index = None
        reducer_index = None
        for tag in self.canvas.gettags(current[0]):
            if tag.startswith("segment:"):
                segment_id = tag.split(":", 1)[1]
            elif tag.startswith("junction:"):
                junction_index = int(tag.split(":", 1)[1])
            elif tag.startswith("reducer:"):
                reducer_index = int(tag.split(":", 1)[1])
        if junction_index is not None:
            self._select_junction(junction_index)
            return "break"
        if reducer_index is not None:
            self._select_reducer(reducer_index)
            return "break"
        segment = self._segment_by_id.get(str(segment_id or ""))
        if segment is None:
            return "break"
        self._status_var.set(
            f"第 {segment['row_index'] + 1} 排／第 {segment['sequence'] + 1} 段｜"
            f"{segment['diameter_label']}｜{segment['evidence_label']}"
        )
        self._select_segment(str(segment_id))
        if self._on_focus is not None:
            self._on_focus(segment["source"])
        return "break"

    def _select_canvas_item(self, event) -> None:
        """Give a single click an explicit M4 selection target.

        Tk's ``current`` tag is only reliable while the pointer is over the
        canvas item.  Resolving the nearest item on release also makes the
        selection feedback work after panning and at lower zoom levels.
        """

        if self._pan_moved:
            self._pan_origin = None
            return
        self._pan_origin = None

        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        items = self.canvas.find_overlapping(x - 5, y - 5, x + 5, y + 5)
        if not items:
            self._selection_var.set("目前未選取管段、接頭或異徑。")
            return
        for item_id in reversed(items):
            tags = self.canvas.gettags(item_id)
            for tag in tags:
                if tag.startswith("junction:"):
                    self._select_junction(int(tag.split(":", 1)[1]))
                    return
                if tag.startswith("reducer:"):
                    self._select_reducer(int(tag.split(":", 1)[1]))
                    return
                if tag.startswith("segment:"):
                    self._select_segment(tag.split(":", 1)[1])
                    return

    def _check_current_plan(self) -> dict[str, Any]:
        if not self._plan_history:
            result = {"status": "not_available", "issues": []}
            self._plan_validation_var.set("計畫檢查：目前沒有可檢查的計畫")
            return result
        plan = self._plan_history[self._plan_history_index]
        result = validate_topology_plan(plan)
        issues = list(result.get("issues") or [])
        if result.get("status") == "valid":
            self._plan_validation_var.set(
                "計畫檢查：通過｜正式建立時會自動安全檢核"
            )
            self._status_var.set("計畫檢查通過；正式建立時會先自動安全檢核。")
        else:
            messages = "；".join(str(item.get("message") or item) for item in issues[:2])
            suffix = f"｜{messages}" if messages else ""
            self._plan_validation_var.set(
                f"計畫檢查：未通過（{len(issues)} 項）{suffix}"
            )
            self._status_var.set("目前計畫仍有問題，修正前不應送入 Revit。")
        self._analysis["topology_plan_validation"] = result
        return result

    def _select_junction(self, index: int) -> None:
        if not self._plan_history:
            return
        junctions = self._plan_history[self._plan_history_index].get("junctions") or []
        if index < 0 or index >= len(junctions):
            return
        labels = {
            "tee": "三通",
            "reducing_tee": "異徑三通",
            "endpoint_tee": "端點三通",
            "reducing_endpoint_tee": "異徑端點三通",
            "cross": "四通",
            "reducing_cross": "異徑四通",
        }
        self._clear_canvas_selection()
        self._selected_junction_index = index
        self.canvas.itemconfigure(f"junction:{index}", state="normal")
        self._highlight_canvas_tag(f"junction:{index}")
        junction = junctions[index]
        self._selection_var.set(
            f"已選取接頭 {junction.get('plan_entity_id') or '-'}｜"
            f"類型：{labels.get(str(junctions[index].get('kind') or ''), '待確認')}｜"
            f"主管段：{junction.get('main_segment_id') or '-'}"
        )
        self._status_var.set(
            f"已選取第 {index + 1} 個接頭｜接頭由管段管徑自動推導，不能單獨修改。"
        )

    def _select_reducer(self, index: int) -> None:
        if not self._plan_history:
            return
        reducers = self._plan_history[self._plan_history_index].get("reducers") or []
        if index < 0 or index >= len(reducers):
            return
        reducer = reducers[index]
        self._clear_canvas_selection()
        self._selected_reducer_index = index
        self.canvas.itemconfigure(f"reducer:{index}", state="normal")
        self._highlight_canvas_tag(f"reducer:{index}")
        self._selection_var.set(
            f"已選取異徑 {reducer.get('plan_entity_id') or '-'}｜"
            f"{float(reducer.get('from_diameter_mm') or 0):g} mm → "
            f"{float(reducer.get('to_diameter_mm') or 0):g} mm｜"
            f"第 {int(reducer.get('row_index') or 0) + 1} 排"
        )
        self._status_var.set(
            f"已選取第 {index + 1} 個異徑｜異徑由前後管段管徑自動推導，不能單獨修改。"
        )

    @staticmethod
    def _route_decisions_from(source: dict[str, Any]) -> list[dict[str, Any]]:
        direct = source.get("route_candidate_decisions")
        if isinstance(direct, list):
            return [item for item in direct if isinstance(item, dict)]
        plan = source.get("topology_plan") or {}
        evidence = plan.get("evidence") if isinstance(plan, dict) else {}
        decisions = evidence.get("route_candidate_decisions") if isinstance(evidence, dict) else None
        return [item for item in (decisions or []) if isinstance(item, dict)]

    @staticmethod
    def _reviewable_route_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Only expose a choice when CAD evidence genuinely offers a choice."""

        return [
            item
            for item in decisions
            if len(item.get("candidates") or {}) > 1
            and str(item.get("status") or "").casefold()
            not in {"resolved", "selected", "accepted", "single_candidate"}
        ]

    def _refresh_route_controls(self) -> None:
        decision_combo = getattr(self, "_route_decision_combo", None)
        candidate_combo = getattr(self, "_route_candidate_combo", None)
        if decision_combo is None or candidate_combo is None:
            return
        plan = self._plan_history[self._plan_history_index] if self._plan_history else {}
        evidence = plan.get("evidence") if isinstance(plan, dict) else {}
        decisions = (
            evidence.get("route_candidate_decisions")
            if isinstance(evidence, dict)
            else None
        )
        if not isinstance(decisions, list):
            decisions = self._route_decisions
        self._route_decisions = self._reviewable_route_decisions(
            [item for item in decisions if isinstance(item, dict)]
        )
        decision_labels = [
            (
                f"灑水頭 {item.get('sprinkler_id') or '-'}｜"
                f"候選 {len(item.get('candidates') or {})}｜"
                f"{item.get('status') or '待核對'}"
            )
            for item in self._route_decisions
        ]
        decision_combo.configure(values=decision_labels)
        if not decision_labels:
            route_editor = getattr(self, "_route_editor", None)
            if route_editor is not None:
                route_editor.grid_remove()
            self._route_decision_var.set("")
            candidate_combo.configure(values=[])
            self._route_candidate_var.set("")
            self._apply_route_button.configure(state="disabled")
            return
        route_editor = getattr(self, "_route_editor", None)
        if route_editor is not None:
            route_editor.grid()
        if self._selected_route_decision_index is None or self._selected_route_decision_index >= len(decision_labels):
            self._selected_route_decision_index = 0
        decision_combo.current(self._selected_route_decision_index)
        self._refresh_route_candidate_values()

    def _on_route_decision_selected(self, _event=None) -> None:
        combo = getattr(self, "_route_decision_combo", None)
        if combo is None:
            return
        index = combo.current()
        self._selected_route_decision_index = index if index >= 0 else None
        self._refresh_route_candidate_values()

    def _refresh_route_candidate_values(self) -> None:
        combo = getattr(self, "_route_candidate_combo", None)
        if combo is None or self._selected_route_decision_index is None:
            return
        if self._selected_route_decision_index >= len(self._route_decisions):
            return
        decision = self._route_decisions[self._selected_route_decision_index]
        self._route_candidate_labels = {}
        labels: list[str] = []
        candidates = decision.get("candidates") or {}
        for candidate_id, candidate in sorted(candidates.items(), key=lambda item: str(item[0])):
            candidate = candidate if isinstance(candidate, dict) else {}
            metrics = candidate.get("metrics") or {}
            rank = candidate.get("rank") or metrics.get("rank") or "-"
            coverage = float(metrics.get("cad_coverage_ratio") or 0)
            selected = str(candidate_id) == str(decision.get("selected_candidate_id") or "")
            label = (
                f"{'目前採用' if selected else '替代'}｜排名 {rank}｜"
                f"主管 {candidate.get('main_pipe_id') or '-'}｜CAD 覆蓋 {coverage:.0%}"
            )
            self._route_candidate_labels[label] = str(candidate_id)
            labels.append(label)
        combo.configure(values=labels)
        selected_id = str(decision.get("selected_candidate_id") or "").strip()
        selected_label = next(
            (label for label, candidate_id in self._route_candidate_labels.items() if candidate_id == selected_id),
            labels[0] if labels else "",
        )
        self._route_candidate_var.set(selected_label)
        self._apply_route_button.configure(state="normal" if labels else "disabled")

    def _apply_route_candidate(self) -> None:
        if not self._plan_history or self._selected_route_decision_index is None:
            return
        candidate_id = self._route_candidate_labels.get(self._route_candidate_var.get(), "")
        if not candidate_id or self._selected_route_decision_index >= len(self._route_decisions):
            return
        decision = self._route_decisions[self._selected_route_decision_index]
        try:
            current = self._plan_history[self._plan_history_index]
            revised = revise_topology_plan(
                current,
                {
                    "type": "choose_route_candidate",
                    "plan_id": current.get("plan_id"),
                    "expected_revision": current.get("revision"),
                    "expected_hash": current.get("plan_hash"),
                    "target_id": candidate_id,
                    "candidate_id": candidate_id,
                    "sprinkler_id": decision.get("sprinkler_id"),
                    "reason": "GUI 使用者修正 CAD 路徑候選",
                },
            )
        except (TypeError, ValueError) as exc:
            self._status_var.set(f"修改 CAD 路徑未套用：{exc}")
            return
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            self._status_var.set(f"修改 CAD 路徑未套用：{detail}；原預覽仍保留。")
            return
        self._append_plan_revision(
            revised,
            selection=("route", self._selected_route_decision_index),
            change_message=f"已採用灑水頭 {decision.get('sprinkler_id') or '-'} 的路徑；圖面已更新。",
        )

    def _select_segment(self, segment_id: str) -> None:
        self._clear_canvas_selection()
        selected = self._segment_by_id.get(segment_id)
        if selected is None:
            return
        self._selected_segment_id = segment_id
        self.canvas.itemconfigure(f"segment:{segment_id}", state="normal")
        self.canvas.itemconfigure(
            f"casing:{segment_id}",
            fill="#f0a000",
            width=max(
                3.0,
                (float(selected["stroke_width"]) + 7) * self._scale,
            ),
        )
        diameter = selected.get("source", {}).get("diameter_mm")
        if diameter is not None:
            self._edit_diameter_var.set(f"{float(diameter):g} mm")
        self._apply_edit_button.configure(
            state="normal" if self._plan_history else "disabled"
        )
        self._show_editor_group("segment")
        self._selection_var.set(
            f"已選取管段 {selected.get('segment_id') or segment_id}｜"
            f"{selected.get('diameter_label') or '待確認'}｜"
            f"{selected.get('length_label') or '-'}｜"
            f"判定依據：{selected.get('evidence_label') or '待確認'}"
        )
        self._status_var.set("已選取管段｜只顯示可用的管徑修正。")

    def _plan_revision_text(self) -> str:
        if not self._plan_history:
            return "目前為預覽模式｜尚未建立可編輯計畫"
        return "目前為預覽模式｜選取物件後可修正，修改會立即更新圖面"

    def _apply_segment_diameter(self) -> None:
        if not self._plan_history or not self._selected_segment_id:
            return
        try:
            diameter = float(
                str(self._edit_diameter_var.get() or "0").replace("mm", "").strip()
            )
            current = self._plan_history[self._plan_history_index]
            revised = revise_topology_plan(
                current,
                {
                    "type": "change_segment_diameter",
                    "plan_id": current.get("plan_id"),
                    "expected_revision": current.get("revision"),
                    "expected_hash": current.get("plan_hash"),
                    "target_id": f"segment:{self._selected_segment_id}",
                    "diameter_mm": diameter,
                    "reason": "GUI 使用者修正",
                },
            )
        except (TypeError, ValueError) as exc:
            self._status_var.set(f"修改管徑未套用：{exc}")
            return
        except Exception as exc:
            # Keep unexpected plan/data errors inside the Tk callback too.
            detail = str(exc).strip() or type(exc).__name__
            self._status_var.set(f"修改管徑未套用：{detail}；原預覽仍保留。")
            return
        self._append_plan_revision(
            revised,
            selection=("segment", self._selected_segment_id),
            change_message=f"管段管徑已更新為 {diameter:g} mm；圖面與計畫已重繪。",
        )

    def _append_plan_revision(
        self,
        revised: dict[str, Any],
        *,
        selection: tuple[str, Any] | None = None,
        change_message: str | None = None,
    ) -> bool:
        """Commit an edit only after the preview can be rebuilt safely.

        Tk callbacks must not allow a layout/SVG exception to escape.  In the
        packaged GUI that used to terminate the preview window (and sometimes
        the whole GUI), making a valid diameter edit look like a crash.  Keep
        the previous revision until the new one has been applied, and restore
        it when the rebuild fails.
        """

        previous_history = self._plan_history
        previous_index = self._plan_history_index
        previous_plan = (
            previous_history[previous_index]
            if previous_history and 0 <= previous_index < len(previous_history)
            else None
        )
        self._plan_history = previous_history[: previous_index + 1] + [revised]
        self._plan_history_index = previous_index + 1
        try:
            self._use_plan(revised, selection=selection, change_message=change_message)
        except Exception as exc:  # Tk callback boundary: never crash the GUI.
            self._plan_history = previous_history
            self._plan_history_index = previous_index
            detail = str(exc).strip() or type(exc).__name__
            self._status_var.set(f"修改未套用：{detail}；原預覽仍保留。")
            if previous_plan is not None:
                try:
                    self._use_plan(
                        previous_plan,
                        change_message=None,
                        notify_parent=False,
                    )
                except Exception as restore_exc:
                    restore_detail = (
                        str(restore_exc).strip() or type(restore_exc).__name__
                    )
                    self._status_var.set(
                        f"修改未套用：{detail}；原預覽重繪失敗：{restore_detail}。"
                    )
            return False
        return True

    def _undo_plan(self) -> None:
        if self._plan_history_index <= 0:
            return
        self._plan_history_index -= 1
        self._use_plan(self._plan_history[self._plan_history_index], change_message="已復原上一個修正。")

    def _redo_plan(self) -> None:
        if self._plan_history_index >= len(self._plan_history) - 1:
            return
        self._plan_history_index += 1
        self._use_plan(self._plan_history[self._plan_history_index], change_message="已重做下一個修正。")

    def _use_plan(
        self,
        plan: dict[str, Any],
        *,
        selection: tuple[str, Any] | None = None,
        change_message: str | None = None,
        notify_parent: bool = True,
    ) -> None:
        view_state = self._capture_canvas_view()
        self._analysis["topology_plan"] = plan
        self._analysis["segments"] = list(plan.get("segments") or [])
        self._analysis["main_context_segments"] = list(plan.get("main_segments") or [])
        self._analysis["junctions"] = list(plan.get("junctions") or [])
        self._analysis["reducers"] = list(plan.get("reducers") or [])
        self._layout = build_fire_branch_network_layout(
            self._analysis,
            main_diameter_mm=self._main_diameter_mm,
        )
        self._sync_canvas_contract_from_layout()
        self._segment_by_id = {
            str(item["segment_id"]): item for item in self._layout["segments"]
        }
        self._selected_segment_id = None
        self._selected_junction_index = None
        self._selected_reducer_index = None
        self._draw()
        self._restore_canvas_view(view_state)
        self._refresh_route_controls()
        self._plan_revision_var.set(self._plan_revision_text())
        self._undo_button.configure(
            state="normal" if self._plan_history_index > 0 else "disabled"
        )
        self._redo_button.configure(
            state=(
                "normal"
                if self._plan_history_index < len(self._plan_history) - 1
                else "disabled"
            )
        )
        self._clear_canvas_selection()
        if selection:
            kind, target = selection
            if kind == "segment" and target:
                self._select_segment(str(target))
            elif kind == "junction" and isinstance(target, int):
                self._select_junction(target)
            elif kind == "reducer" and isinstance(target, int):
                self._select_reducer(target)
        # The Tk canvas is the live preview.  An SVG file is only an export;
        # an export failure must not discard a visible edit or close the GUI.
        try:
            self._svg_path = self._create_svg(str(plan.get("plan_id") or "preview"))
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            self._status_var.set(f"圖面已更新，但 SVG 同步失敗：{detail}。")
        try:
            self._check_current_plan()
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            self._plan_validation_var.set(f"計畫檢查暫時失敗：{detail}")
            self._status_var.set(f"圖面已更新，但計畫檢查失敗：{detail}。")
        if change_message:
            self._status_var.set(change_message)
        if notify_parent and self._on_plan_changed is not None:
            try:
                self._on_plan_changed(plan)
            except Exception as exc:
                # Keep the preview usable even if the parent window cannot
                # refresh its summary immediately.
                detail = str(exc).strip() or type(exc).__name__
                self._status_var.set(f"圖面已更新，但主畫面同步失敗：{detail}。")

    def _sync_canvas_contract_from_layout(self) -> None:
        contract = self._layout.get("canvas_contract")
        if isinstance(contract, dict) and "network_canvas_contract" not in self._analysis:
            self._analysis["network_canvas_contract"] = contract

    def _capture_canvas_view(self) -> dict[str, Any] | None:
        if not hasattr(self, "canvas"):
            return None
        try:
            return {
                "scale": float(self._scale or 1.0),
                "xview": self.canvas.xview(),
                "yview": self.canvas.yview(),
            }
        except Exception:
            return None

    def _restore_canvas_view(self, state: dict[str, Any] | None) -> None:
        if not state or not hasattr(self, "canvas"):
            self._refresh_scaled_styles()
            self._apply_semantic_zoom()
            return
        try:
            target_scale = max(
                0.05,
                min(MAX_ZOOM_SCALE, float(state.get("scale") or 1.0)),
            )
        except (TypeError, ValueError):
            target_scale = 1.0
        self._scale = 1.0
        if abs(target_scale - 1.0) > 0.000001:
            self.canvas.scale("diagram", 0.0, 0.0, target_scale, target_scale)
        self._scale = target_scale
        self._refresh_scaled_styles()
        self._apply_semantic_zoom()
        self._update_scrollregion()
        try:
            xview = state.get("xview") or (0.0, 1.0)
            yview = state.get("yview") or (0.0, 1.0)
            self.canvas.xview_moveto(float(xview[0]))
            self.canvas.yview_moveto(float(yview[0]))
        except Exception:
            pass

    def _hide_editor_groups(self) -> None:
        for group in getattr(self, "_editor_groups", {}).values():
            group.grid_remove()

    def _show_editor_group(self, kind: str) -> None:
        self._hide_editor_groups()
        group = getattr(self, "_editor_groups", {}).get(kind)
        if group is not None:
            group.grid(row=0, column=0, columnspan=3, sticky="w")

    def _clear_canvas_selection(self) -> None:
        if hasattr(self, "canvas"):
            self.canvas.delete("selection-halo")
        if self._selected_segment_id:
            previous = self._segment_by_id.get(self._selected_segment_id)
            if previous is not None and hasattr(self, "canvas"):
                self.canvas.itemconfigure(
                    f"casing:{self._selected_segment_id}",
                    fill="#d0d0d0",
                    width=max(2.0, (float(previous["stroke_width"]) + 4) * self._scale),
                )
        self._selected_segment_id = None
        self._selected_junction_index = None
        self._selected_reducer_index = None
        if hasattr(self, "_apply_edit_button"):
            self._apply_edit_button.configure(state="disabled")
        self._hide_editor_groups()
        if hasattr(self, "canvas"):
            self._apply_semantic_zoom()

    def _highlight_canvas_tag(self, tag: str) -> None:
        bbox = self.canvas.bbox(tag)
        if not bbox:
            return
        padding = max(7, round(8 * self._scale))
        self.canvas.create_rectangle(
            bbox[0] - padding,
            bbox[1] - padding,
            bbox[2] + padding,
            bbox[3] + padding,
            outline="#f0a000",
            width=max(2, round(2 * self._scale)),
            tags=("diagram", "selection-halo"),
        )

    def _refresh_scaled_styles(self) -> None:
        self._zoom_percent_var.set(f"{self._scale * 100:.0f}%")
        fonts = {
            "lane-text": (11, "bold"),
            "main-label": (12, "bold"),
            "diameter-text": (10, "bold"),
            "segment-detail": (8, "normal"),
            "reducer-label": (9, "normal"),
            "junction-label": (9, "bold"),
            "orientation-text": (11, "bold"),
        }
        for tag, (base_size, weight) in fonts.items():
            # Text must follow the drawing scale.  Clamping keeps labels
            # readable at overview/detail extremes without recreating cards.
            scaled_size = max(7, min(18, round(base_size * self._scale)))
            self.canvas.itemconfigure(
                tag,
                font=("Microsoft JhengHei UI", scaled_size, weight),
            )
        main_width = float(self._layout["main"].get("stroke_width") or 9.0)
        self.canvas.itemconfigure(
            "main-casing",
            width=max(2.0, (main_width + 4) * self._scale),
        )
        self.canvas.itemconfigure(
            "main-pipe",
            width=max(2.0, main_width * self._scale),
        )
        for segment in self._layout["segments"]:
            segment_id = str(segment["segment_id"])
            pipe_width = float(segment["stroke_width"])
            self.canvas.itemconfigure(
                f"pipe:{segment_id}",
                width=max(1.5, pipe_width * self._scale),
            )
            self.canvas.itemconfigure(
                f"casing:{segment_id}",
                width=max(2.0, (pipe_width + 4) * self._scale),
            )
        for reducer in self._layout["reducers"]:
            source_segment_id = str(reducer["source_segment_id"])
            lead_width = float(reducer["lead_stroke_width"])
            self.canvas.itemconfigure(
                f"reducer-lead-pipe:{source_segment_id}",
                width=max(1.5, lead_width * self._scale),
            )
            self.canvas.itemconfigure(
                f"reducer-lead-casing:{source_segment_id}",
                width=max(2.0, (lead_width + 4) * self._scale),
            )

    def _apply_semantic_zoom(self) -> None:
        visibility = semantic_zoom_visibility(self._scale)
        for name, visible in visibility.items():
            self.canvas.itemconfigure(
                name.replace("_", "-"),
                state="normal" if visible else "hidden",
            )
        if self._scale < 0.92:
            self._status_var.set(
                "總覽模式｜以管線粗細、顏色、橘色異徑點與虛線快速檢查；滾輪放大可看管徑"
            )
            return
        if self._scale < 1.18:
            self._status_var.set("管徑模式｜已顯示管徑；繼續放大可看長度與判定依據")
            return
        self._status_var.set(
            "詳細模式｜滑鼠滾輪縮放｜按住左鍵拖動｜雙擊管段可回到 Revit 定位"
        )

    def _fit_to_window(self) -> None:
        self.update_idletasks()
        self._scale = 1.0
        self._draw()
        bbox = self.canvas.bbox("diagram")
        if not bbox:
            return
        available_width = max(100, self.canvas.winfo_width() - 50)
        available_height = max(100, self.canvas.winfo_height() - 50)
        drawing_width = max(1, bbox[2] - bbox[0])
        drawing_height = max(1, bbox[3] - bbox[1])
        factor = min(1.0, available_width / drawing_width, available_height / drawing_height)
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        if factor != 1.0:
            self.canvas.scale("diagram", center_x, center_y, factor, factor)
        self._scale = factor
        self._refresh_scaled_styles()
        self._apply_semantic_zoom()
        self._update_scrollregion()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _show_readable_view(self) -> None:
        self.update_idletasks()
        self._scale = 1.0
        self._draw()
        target_scale = min(1.0, max(READABLE_ZOOM_SCALE, self._fit_scale()))
        if target_scale != 1.0:
            bbox = self.canvas.bbox("diagram")
            if bbox:
                center_x = (bbox[0] + bbox[2]) / 2
                center_y = (bbox[1] + bbox[3]) / 2
                self.canvas.scale(
                    "diagram",
                    center_x,
                    center_y,
                    target_scale,
                    target_scale,
                )
        self._scale = target_scale
        self._refresh_scaled_styles()
        self._apply_semantic_zoom()
        self._update_scrollregion()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _fit_scale(self) -> float:
        bbox = self.canvas.bbox("diagram")
        if not bbox:
            return 1.0
        available_width = max(100, self.canvas.winfo_width() - 50)
        available_height = max(100, self.canvas.winfo_height() - 50)
        drawing_width = max(1, bbox[2] - bbox[0])
        drawing_height = max(1, bbox[3] - bbox[1])
        return min(
            1.0,
            available_width / drawing_width,
            available_height / drawing_height,
        )

    def _update_scrollregion(self) -> None:
        bbox = self.canvas.bbox("diagram")
        if bbox:
            padding = 40
            self.canvas.configure(
                scrollregion=(
                    bbox[0] - padding,
                    bbox[1] - padding,
                    bbox[2] + padding,
                    bbox[3] + padding,
                )
            )

    def _save_svg(self) -> None:
        target = filedialog.asksaveasfilename(
            parent=self,
            title="另存消防支管路網圖",
            defaultextension=".svg",
            filetypes=[("SVG 向量圖", "*.svg")],
            initialfile=self._svg_path.name,
        )
        if not target:
            return
        shutil.copyfile(self._svg_path, target)
        self._saved_copy = True
        self._status_var.set(f"已另存 SVG：{target}")

    def _close(self) -> None:
        try:
            self._svg_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.destroy()
