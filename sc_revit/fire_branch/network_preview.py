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
    overview = current_scale < 0.72
    detailed = current_scale >= 1.02
    return {
        "diameter_box": detailed,
        "diameter_text": not overview,
        "segment_detail": detailed,
        "reducer_label": not overview,
        "junction_label": not overview,
        "main_label": not overview,
    }


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
    ) -> None:
        super().__init__(parent)
        self.title("消防支管路網圖")
        self.geometry("1100x760")
        self.minsize(760, 520)
        self.transient(parent)
        self._analysis = analysis
        self._main_diameter_mm = main_diameter_mm
        self._on_focus = on_focus
        self._layout = build_fire_branch_network_layout(
            analysis,
            main_diameter_mm=main_diameter_mm,
        )
        self._segment_by_id = {
            str(item["segment_id"]): item for item in self._layout["segments"]
        }
        self._scale = 1.0
        self._zoom_percent_var = tk.StringVar(value="100%")
        self._selected_segment_id: str | None = None
        self._saved_copy = False
        self._svg_path = self._create_svg(batch_id)
        self._status_var = tk.StringVar(
            value="滑鼠滾輪縮放｜按住左鍵拖動｜雙擊管段可回到 Revit 定位"
        )

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(toolbar, textvariable=self._status_var).grid(
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

        canvas_frame = ttk.Frame(self)
        canvas_frame.grid(row=1, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)
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
        self.canvas.bind("<Double-1>", self._focus_segment)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._draw()
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
                font=("Microsoft JhengHei UI", 9, "bold"),
                tags=("diagram", "lane", "lane-text"),
            )
        main_width = float(main.get("stroke_width") or 9.0)
        self.canvas.create_line(
            main["x1"],
            main["y1"],
            main["x2"],
            main["y2"],
            fill="#d7d7d7",
            width=main_width + 4,
            capstyle="round",
            tags=("diagram", "main", "main-casing"),
        )
        self.canvas.create_line(
            main["x1"],
            main["y1"],
            main["x2"],
            main["y2"],
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
            font=("Microsoft JhengHei UI", 10, "bold"),
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
                fill=segment["color"],
                width=pipe_width,
                dash=dash,
                capstyle="round",
                tags=("diagram", "segment", segment_tag, pipe_tag),
            )
            center_x = float(segment["label_x"])
            label_y = float(segment["label_y"])
            label_fill = "#fff8dc" if segment["review_required"] else "#ffffff"
            label_outline = "#d6a700" if segment["review_required"] else "#cfcfcf"
            self.canvas.create_rectangle(
                center_x - 73,
                label_y - 24,
                center_x + 73,
                label_y + 20,
                fill=label_fill,
                outline=label_outline,
                width=1,
                tags=("diagram", "segment-label", "diameter-box", segment_tag),
            )
            self.canvas.create_text(
                center_x,
                label_y - 5,
                text=segment["diameter_label"],
                fill="#111111",
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
        for reducer in self._layout["reducers"]:
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
                tags=("diagram", "reducer"),
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
                tags=("diagram", "reducer"),
            )
            self.canvas.create_text(
                x,
                y + 43,
                text=reducer["label"],
                fill="#333333",
                font=("Microsoft JhengHei UI", 8),
                tags=("diagram", "reducer", "reducer-label"),
            )
        for segment in self._layout["segments"]:
            if segment.get("is_sprinkler_terminal"):
                self._draw_terminal_marker(segment, f"segment:{segment['segment_id']}")
        for junction in self._layout["junctions"]:
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
                tags=("diagram", "junction"),
            )
            self.canvas.create_line(
                x - 7,
                y,
                x + 7,
                y,
                fill=outline,
                width=3,
                capstyle="round",
                tags=("diagram", "junction"),
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
                    tags=("diagram", "junction"),
                )
            self.canvas.create_text(
                x + 18,
                y - 16,
                anchor="w",
                text=f"{title}｜{junction['label']}",
                fill="#333333",
                font=("Microsoft JhengHei UI", 9, "bold"),
                tags=("diagram", "junction", "junction-label"),
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
                font=("Microsoft JhengHei UI", 9, "bold"),
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
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _focus_segment(self, _event) -> str:
        current = self.canvas.find_withtag("current")
        if not current:
            return "break"
        segment_id = None
        for tag in self.canvas.gettags(current[0]):
            if tag.startswith("segment:"):
                segment_id = tag.split(":", 1)[1]
                break
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

    def _select_segment(self, segment_id: str) -> None:
        if self._selected_segment_id:
            previous = self._segment_by_id.get(self._selected_segment_id)
            if previous is not None:
                self.canvas.itemconfigure(
                    f"casing:{self._selected_segment_id}",
                    fill="#d0d0d0",
                    width=max(
                        2.0,
                        (float(previous["stroke_width"]) + 4) * self._scale,
                    ),
                )
        selected = self._segment_by_id.get(segment_id)
        if selected is None:
            return
        self._selected_segment_id = segment_id
        self.canvas.itemconfigure(
            f"casing:{segment_id}",
            fill="#f0a000",
            width=max(
                3.0,
                (float(selected["stroke_width"]) + 7) * self._scale,
            ),
        )

    def _refresh_scaled_styles(self) -> None:
        visual_scale = max(0.75, min(2.4, self._scale))
        self._zoom_percent_var.set(f"{self._scale * 100:.0f}%")
        fonts = {
            "lane-text": (9, "bold"),
            "main-label": (10, "bold"),
            "diameter-text": (10, "bold"),
            "segment-detail": (8, "normal"),
            "reducer-label": (8, "normal"),
            "orientation-text": (9, "bold"),
        }
        for tag, (base_size, weight) in fonts.items():
            size = max(7, round(base_size * visual_scale))
            self.canvas.itemconfigure(
                tag,
                font=("Microsoft JhengHei UI", size, weight),
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
        if self._scale < 0.72:
            self._status_var.set(
                "總覽模式｜以管線粗細、顏色、橘色異徑點與虛線快速檢查；滾輪放大可看管徑"
            )
            return
        if self._scale < 1.02:
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
