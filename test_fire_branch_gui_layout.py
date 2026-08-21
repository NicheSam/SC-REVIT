import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GUI_SOURCE = ROOT / "gui_app.py"


class FireBranchGuiLayoutTests(unittest.TestCase):
    def test_fire_branch_uses_two_columns_with_selection_on_the_left(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        start = source.index("    def _build_fire_branch_tab")
        end = source.index("    def _toggle_fire_technical_info", start)
        body = source[start:end]

        self.assertIn("fire_workspace = ttk.Panedwindow(parent", body)
        self.assertIn("left_panel = ttk.Frame(fire_workspace)", body)
        self.assertIn("right_panel = ttk.Frame(fire_workspace", body)
        self.assertIn("fire_workspace.add(left_panel, weight=3)", body)
        self.assertIn("fire_workspace.add(right_panel, weight=2)", body)
        self.assertIn('text="4. 選取撒水頭（Revit 內框選或多選後讀取）"', body)
        self.assertIn('text="目前狀態"', body)
        self.assertIn('text="5. 分析與計畫結果"', body)
        self.assertIn('text="查看分析結果與異常"', body)
        self.assertIn("command=self._open_fire_analysis_result", body)
        self.assertIn("self.fire_selection_detail_var", body)
        self.assertIn("self.fire_result_selection_var", body)

    def test_fire_branch_actions_stack_in_the_right_panel(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        start = source.index("    def _build_fire_branch_tab")
        end = source.index("    def _toggle_fire_technical_info", start)
        body = source[start:end]

        self.assertIn("action_frame = ttk.Frame(right_panel)", body)
        self.assertIn("self.fire_preview_button.grid(", body)
        self.assertIn("self.fire_commit_button.grid(", body)
        self.assertNotIn("self.fire_sandbox_button.grid(", body)
        self.assertNotIn("self.fire_preview_button.pack(", body)

    def test_fire_branch_context_loads_automatically_without_a_button(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        start = source.index("    def _build_fire_branch_tab")
        end = source.index("    def _toggle_fire_technical_info", start)
        body = source[start:end]

        self.assertIn("self.after(250, self._load_fire_branch_context)", source)
        self.assertIn("開啟頁面後會自動載入", body)
        self.assertNotIn('text="讀取管路資料"', body)

    def test_fire_branch_has_a_taller_default_window(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('elif self.app_mode == "fire_branch":', source)
        self.assertIn('self.geometry("1360x820")', source)
        self.assertIn('self.minsize(1080, 700)', source)

    def test_diameter_analysis_separates_horizontal_and_drop_reducers(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('text="管徑分段"', source)
        self.assertIn('text="水平沿程變徑"', source)
        self.assertIn('text="落水管規則"', source)
        self.assertIn('"三通出口短管"', source)
        self.assertIn('"落水變徑"', source)
        self.assertIn('"DN25 落水段"', source)
        self.assertIn('"接入位置的水平支管管徑"', source)
        self.assertIn('"固定 DN25／1 吋"', source)
        self.assertIn("計畫檢查", source)
        self.assertIn("def _populate_fire_diameter_analysis", source)
        self.assertIn("self._populate_fire_diameter_analysis(", source)
        self.assertIn('"line_color_reference": "線段顏色"', source)
        self.assertIn("self.fire_diameter_segment_tree.bind(", source)
        self.assertIn('"<Double-1>"', source)
        self.assertIn("def _focus_fire_diameter_segment", source)

    def test_fire_preview_reuses_revit_linked_cad_coordinate_anchors(self) -> None:
        source = (ROOT / "gui_app.py").read_text(encoding="utf-8")

        self.assertIn('payload["cad_coordinate_anchors"]', source)
        self.assertIn('block_filter=""', source)

    def test_fire_branch_has_on_demand_network_preview(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('text="2. 查看路網圖／修正計畫"', source)
        self.assertIn("command=self._open_fire_branch_network_preview", source)
        self.assertIn('state="normal" if diameter_analysis.get("segments") else "disabled"', source)
        self.assertIn("FireBranchNetworkPreview", source)

    def test_analysis_summary_opens_in_a_separate_window(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("def _open_fire_analysis_result", source)
        self.assertIn('window.title("分析與檢查結果")', source)
        self.assertIn('text="摘要"', source)
        self.assertIn('text="計畫資訊"', source)
        self.assertIn('text="候選與異常"', source)
        self.assertIn("複製完整報告", source)

    def test_fire_branch_has_explicit_selection_feedback(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('"<<TreeviewSelect>>", self._on_fire_sprinkler_selection_changed', source)
        self.assertIn('"<<TreeviewSelect>>", self._on_fire_diameter_selection_changed', source)
        self.assertIn("def _on_fire_sprinkler_selection_changed", source)
        self.assertIn("def _on_fire_diameter_selection_changed", source)
        self.assertIn("def _on_fire_reducer_selection_changed", source)

    def test_fire_preview_exposes_selected_object_editor(self) -> None:
        source = (ROOT / "sc_revit/fire_branch/network_preview.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def _check_current_plan", source)
        self.assertIn('text="選取後修正"', source)
        self.assertIn("self._editor_groups", source)
        self.assertIn("def _show_editor_group", source)
        self.assertIn("def _highlight_canvas_tag", source)
        self.assertIn("validate_topology_plan", source)
        self.assertIn('"<ButtonRelease-1>", self._select_canvas_item', source)
        self.assertIn("self._pan_moved", source)
        self.assertIn("if self._pan_moved:", source)

    def test_invalid_topology_revision_cannot_enter_revit_preflight(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        start = source.index("    def _accept_fire_topology_plan_revision")
        end = source.index("    def _focus_fire_network_segment", start)
        body = source[start:end]

        self.assertIn('validation_status == "invalid"', body)
        self.assertIn('self.fire_sandbox_button.configure(state="disabled")', body)
        self.assertIn("拓樸修正仍有問題", body)

    def test_network_preview_edits_do_not_close_the_preview_window(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        reset_start = source.index("    def _reset_fire_sandbox_approval")
        reset_end = source.index("    def _analyze_fire_branch_selection", reset_start)
        reset_body = source[reset_start:reset_end]
        accept_start = source.index("    def _accept_fire_topology_plan_revision")
        accept_end = source.index("    def _focus_fire_network_segment", accept_start)
        accept_body = source[accept_start:accept_end]

        self.assertIn("close_network_preview: bool = True", reset_body)
        self.assertIn("if close_network_preview:", reset_body)
        self.assertIn("network_window._close()", reset_body)
        self.assertIn("close_network_preview=False", accept_body)


if __name__ == "__main__":
    unittest.main()
