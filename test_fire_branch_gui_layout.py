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
        self.assertIn('ttk.LabelFrame(left_panel, text="4. 選取撒水頭', body)
        self.assertIn('ttk.LabelFrame(right_panel, text="建立前檢查"', body)
        self.assertIn('ttk.LabelFrame(right_panel, text="5. 管徑分段"', body)
        self.assertIn('text="查看分析與檢查結果"', body)
        self.assertIn("command=self._open_fire_analysis_result", body)
        self.assertNotIn("textvariable=self.fire_analysis_summary_var,\n            justify=\"left\",\n            wraplength=340", body)

    def test_fire_branch_actions_stack_in_the_right_panel(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")
        start = source.index("    def _build_fire_branch_tab")
        end = source.index("    def _toggle_fire_technical_info", start)
        body = source[start:end]

        self.assertIn("action_frame = ttk.Frame(right_panel)", body)
        self.assertIn("self.fire_preview_button.grid(", body)
        self.assertIn("self.fire_sandbox_button.grid(", body)
        self.assertIn("self.fire_commit_button.grid(", body)
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
        self.assertIn("檢查內容包含完整路網、管徑、管件與灑水頭連通性", source)
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

        self.assertIn('text="查看路網圖"', source)
        self.assertIn("command=self._open_fire_branch_network_preview", source)
        self.assertIn('state="normal" if diameter_analysis.get("segments") else "disabled"', source)
        self.assertIn("FireBranchNetworkPreview", source)

    def test_analysis_summary_opens_in_a_separate_window(self) -> None:
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("def _open_fire_analysis_result", source)
        self.assertIn('window.title("分析與檢查結果")', source)
        self.assertIn("textvariable=self.fire_analysis_summary_var", source)


if __name__ == "__main__":
    unittest.main()
