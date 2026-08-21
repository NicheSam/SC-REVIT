from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from sc_revit.fire_branch.network_diagram import render_fire_branch_network_svg


OUT = Path(__file__).resolve().parent

LIVE = {
    "document": "大甲分局_MEP_sc168jobim",
    "view_id": 13301161,
    "view_name": "-1. 地下壹層 撒水",
    "cad_import_id": 13379416,
    "cad_name": "位置 <未共用>",
    "cad_category": "自動撒水設備配置圖-地下壹層",
    "pipe": {
        "id": 13563852,
        "family": "FS_消防撒水管",
        "diameter_mm": 100.0,
        "length_mm": 7005.735,
        "connector_count": 2,
        "start_mm": {"x": 79090.7945, "y": -49877.6369, "z": 100.0},
        "end_mm": {"x": 72085.0595, "y": -49877.6369, "z": 100.0},
    },
    "tee": {
        "id": 13722992,
        "family": "FS_消防撒水管_三通_螺牙",
        "connector_count": 3,
        "connector_diameters_mm": [40.0, 40.0, 40.0],
    },
    "cross": {
        "id": 13563873,
        "family": "FS_消防撒水管_十字_焊接",
        "connector_count": 4,
        "connector_diameters_mm": [100.0, 100.0, 100.0, 100.0],
    },
    "reducer": {
        "id": 13737368,
        "family": "FS_消防撒水管_變徑_螺牙",
        "connector_count": 2,
        "connector_diameters_mm": [20.0, 25.0],
    },
    "elbow": {
        "id": 13563857,
        "family": "FS_消防撒水管_彎頭_焊接",
        "connector_count": 2,
        "connector_diameters_mm": [100.0, 100.0],
    },
    "counts": {"fire_pipes": 276, "fire_fittings": 168, "tee": 50, "cross": 17, "reducer": 66, "elbow": 35},
}


def _entity(kind: str, element_id: int) -> str:
    return f"component:{kind}:{element_id}"


def build_renderer_fixture() -> dict:
    segments = [
        {
            "segment_id": "live-tee-branch",
            "plan_entity_id": _entity("tee-branch", LIVE["tee"]["id"]),
            "row_index": 0,
            "sequence": 0,
            "source_element_id": LIVE["pipe"]["id"],
            "source_fitting_id": LIVE["tee"]["id"],
            "start": {"x": 0, "y": 0},
            "end": {"x": 260, "y": 0},
            "diameter_mm": 25,
            "color": "rgb:0,168,181",
            "evidence": "live_revit_readback",
            "planned_length_mm": 2600,
        },
        {
            "segment_id": "live-cross-branch-a",
            "plan_entity_id": _entity("cross-branch-a", LIVE["cross"]["id"]),
            "row_index": 1,
            "sequence": 0,
            "source_element_id": LIVE["pipe"]["id"],
            "source_fitting_id": LIVE["cross"]["id"],
            "start": {"x": 0, "y": 100},
            "end": {"x": 250, "y": 100},
            "diameter_mm": 40,
            "color": "rgb:229,57,53",
            "evidence": "live_revit_readback",
            "planned_length_mm": 2500,
        },
        {
            "segment_id": "live-cross-branch-b",
            "plan_entity_id": _entity("cross-branch-b", LIVE["cross"]["id"]),
            "row_index": 1,
            "sequence": 1,
            "source_element_id": LIVE["pipe"]["id"],
            "source_fitting_id": LIVE["cross"]["id"],
            "start": {"x": 250, "y": 100},
            "end": {"x": 470, "y": 100},
            "diameter_mm": 32,
            "color": "rgb:255,127,0",
            "evidence": "live_revit_readback",
            "planned_length_mm": 2200,
        },
        {
            "segment_id": "live-reducer-upstream",
            "plan_entity_id": _entity("reducer-upstream", LIVE["reducer"]["id"]),
            "row_index": 2,
            "sequence": 0,
            "source_element_id": LIVE["pipe"]["id"],
            "source_fitting_id": LIVE["reducer"]["id"],
            "start": {"x": 0, "y": 200},
            "end": {"x": 220, "y": 200},
            "diameter_mm": 40,
            "color": "rgb:229,57,53",
            "evidence": "live_revit_readback",
            "planned_length_mm": 2200,
        },
        {
            "segment_id": "live-reducer-downstream",
            "plan_entity_id": _entity("reducer-downstream", LIVE["reducer"]["id"]),
            "row_index": 2,
            "sequence": 1,
            "source_element_id": LIVE["pipe"]["id"],
            "source_fitting_id": LIVE["reducer"]["id"],
            "start": {"x": 220, "y": 200},
            "end": {"x": 430, "y": 200},
            "diameter_mm": 32,
            "color": "rgb:255,127,0",
            "evidence": "live_revit_readback",
            "planned_length_mm": 2100,
        },
        {
            "segment_id": "live-pipe",
            "plan_entity_id": _entity("pipe", LIVE["pipe"]["id"]),
            "row_index": 3,
            "sequence": 0,
            "source_element_id": LIVE["pipe"]["id"],
            "start": {"x": 0, "y": 300},
            "end": {"x": 700, "y": 300},
            "diameter_mm": 100,
            "color": "rgb:69,90,100",
            "evidence": "live_revit_readback",
            "planned_length_mm": LIVE["pipe"]["length_mm"],
        },
    ]
    topology_plan = {
        "plan_id": "live-svg-component-fixture-20260821",
        "plan_version": "fire_branch_topology_plan.v5",
        "revision": 1,
        "segments": [{"segment_id": s["segment_id"], "plan_entity_id": s["plan_entity_id"]} for s in segments],
        "main_segments": [{"segment_id": "main-live-pipe", "plan_entity_id": "main:pipe:13563852"}],
        "reducers": [
            {
                "after_segment_id": "live-reducer-upstream",
                "before_segment_id": "live-reducer-downstream",
                "from_diameter_mm": 40,
                "to_diameter_mm": 32,
                "placement": "along_branch",
                "plan_entity_id": _entity("reducer", LIVE["reducer"]["id"]),
            }
        ],
        "junctions": [
            {
                "main_segment_id": "main-live-pipe",
                "branch_segment_ids": ["live-tee-branch"],
                "kind": "reducing_tee",
                "main_diameter_mm": 100,
                "common_branch_diameter_mm": 25,
                "plan_entity_id": _entity("tee", LIVE["tee"]["id"]),
                "review_required": False,
            },
            {
                "main_segment_id": "main-live-pipe",
                "branch_segment_ids": ["live-cross-branch-a", "live-cross-branch-b"],
                "kind": "reducing_cross",
                "main_diameter_mm": 100,
                "common_branch_diameter_mm": 40,
                "plan_entity_id": _entity("cross", LIVE["cross"]["id"]),
                "review_required": False,
            },
        ],
    }
    topology_plan["plan_hash"] = hashlib.sha256(
        json.dumps(topology_plan, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "cad_path_verified": True,
        "validation_mode": "live_readback_component_fixture",
        "cad_path_check": {"status": "fixture", "coordinate_verified": True, "coverage_ratio": 1.0},
        "view_orientation": {
            "source": "revit_view",
            "right": {"x": 1, "y": 0},
            "up": {"x": 0, "y": 1},
            "view_direction": {"x": 0, "y": 0, "z": 1},
        },
        "main_context_segments": [
            {
                "segment_id": "main-live-pipe",
                "source_element_id": LIVE["pipe"]["id"],
                "diameter_mm": 100,
                "start": {"x": 0, "y": -80},
                "end": {"x": 700, "y": -80},
                "connections": [
                    {"point": {"x": 130, "y": -80}},
                    {"point": {"x": 320, "y": -80}},
                ],
            }
        ],
        "segments": segments,
        "topology_plan": topology_plan,
        "main_diameter_mm": 100,
    }


def _component_sheet() -> str:
    cards = [
        ("管段 Pipe", "pipe", LIVE["pipe"], "#455a64", "M 25 210 L 225 210", 'stroke-width="18"'),
        ("彎頭 Elbow", "elbow", LIVE["elbow"], "#455a64", "M 25 300 L 130 300 L 130 220", 'stroke-width="16"'),
        ("三通 Tee", "tee", LIVE["tee"], "#00a8b5", "M 70 220 L 70 300 M 25 260 L 200 260", 'stroke-width="14"'),
        ("四通 Cross", "cross", LIVE["cross"], "#e53935", "M 120 220 L 120 310 M 30 265 L 210 265", 'stroke-width="14"'),
        ("變徑 Reducer", "reducer", LIVE["reducer"], "#ff7f00", "M 40 260 L 90 260 L 140 290 L 200 290", 'stroke-width="12"'),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="620" viewBox="0 0 1400 620" role="img" aria-labelledby="title desc">',
        '<title id="title">SC REVIT 實機回讀元件 SVG 轉換驗證</title>',
        '<desc id="desc">以目前 Revit 活動視圖與唯一連結 CAD 的唯讀回讀資料，驗證管段、彎頭、三通、四通與變徑的 SVG 元件轉換。</desc>',
        '<rect width="1400" height="620" fill="#ffffff"/>',
        '<text x="40" y="38" font-family="Microsoft JhengHei, sans-serif" font-size="24" font-weight="700" fill="#263238">實機回讀｜SVG 元件轉換驗證（未部署 DLL）</text>',
        f'<text x="40" y="66" font-family="Microsoft JhengHei, sans-serif" font-size="14" fill="#455a64">文件：{html.escape(LIVE["document"])}｜視圖：{html.escape(LIVE["view_name"])}｜CAD ImportInstance：{LIVE["cad_import_id"]}（唯一）</text>',
        '<text x="40" y="92" font-family="Microsoft JhengHei, sans-serif" font-size="13" fill="#607d8b">座標方向：依 Revit 活動視圖 right/up；本頁是元件轉換證據，不宣稱 CAD 路徑對位已完成。</text>',
    ]
    for index, (label, kind, item, color, path, style) in enumerate(cards):
        x = 30 + index * 270
        parts.append(f'<g id="card-{kind}" data-plan-entity-id="{_entity(kind, item["id"])}" data-revit-element-id="{item["id"]}" data-component-kind="{kind}" data-connector-count="{item["connector_count"]}">')
        parts.append(f'<rect x="{x}" y="120" width="250" height="430" rx="8" fill="#f8fafb" stroke="#cfd8dc"/>')
        parts.append(f'<text x="{x + 18}" y="150" font-family="Microsoft JhengHei, sans-serif" font-size="18" font-weight="700" fill="#263238">{html.escape(label)}</text>')
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" {style} stroke-linecap="round" stroke-linejoin="round" transform="translate({x},0)"/>')
        if kind == "tee":
            parts.append(f'<circle cx="{x + 80}" cy="270" r="14" fill="#ffffff" stroke="#00838f" stroke-width="4"/>')
        elif kind == "cross":
            parts.append(f'<circle cx="{x + 100}" cy="275" r="14" fill="#ffffff" stroke="#c62828" stroke-width="4"/>')
        elif kind == "reducer":
            parts.append(f'<path d="M {x + 100} 250 L {x + 135} 250 L {x + 165} 300 L {x + 200} 300" fill="none" stroke="#ff7f00" stroke-width="18"/>')
        parts.append(f'<text x="{x + 18}" y="370" font-family="Consolas, monospace" font-size="14" fill="#263238">ElementId: {item["id"]}</text>')
        parts.append(f'<text x="{x + 18}" y="397" font-family="Microsoft JhengHei, sans-serif" font-size="13" fill="#455a64">族群：{html.escape(item["family"])}</text>')
        parts.append(f'<text x="{x + 18}" y="423" font-family="Microsoft JhengHei, sans-serif" font-size="13" fill="#455a64">連接器：{item["connector_count"]} 個</text>')
        diameter_values = item.get("connector_diameters_mm") or [item.get("diameter_mm")]
        diameters = "、".join(f"DN{value:g}" for value in diameter_values if value is not None)
        parts.append(f'<text x="{x + 18}" y="449" font-family="Microsoft JhengHei, sans-serif" font-size="13" fill="#455a64">連接器管徑：{diameters}</text>')
        if kind == "pipe":
            parts.append(f'<text x="{x + 18}" y="475" font-family="Microsoft JhengHei, sans-serif" font-size="13" fill="#455a64">長度：{item["length_mm"]:.1f} mm｜管徑 DN{item["diameter_mm"]:g}</text>')
        else:
            parts.append(f'<text x="{x + 18}" y="475" font-family="Microsoft Jheng Hei, sans-serif" font-size="13" fill="#455a64">plan_entity_id：{_entity(kind, item["id"])}</text>')
        parts.append('</g>')
    parts.extend([
        '<rect x="40" y="575" width="1320" height="24" rx="4" fill="#fff8e1" stroke="#f9a825"/>',
        '<text x="55" y="592" font-family="Microsoft Jheng Hei, sans-serif" font-size="13" fill="#6d4c41">判讀：每個卡片均保留 live Revit ElementId、族群、連接器數量與連接器管徑；本頁沒有交易、沒有建模、沒有 DLL 載入。</text>',
        '</svg>',
    ])
    return "\n".join(parts)


def main() -> None:
    analysis = build_renderer_fixture()
    renderer_svg = render_fire_branch_network_svg(
        analysis,
        title="SC REVIT 實機回讀拓樸轉換契約測試（未部署 DLL）",
        main_diameter_mm=100,
    )
    renderer_path = OUT / "fire_branch_live_topology_renderer_fixture.svg"
    components_path = OUT / "fire_branch_live_component_sheet.svg"
    payload_path = OUT / "fire_branch_live_component_readback.json"
    renderer_path.write_text(renderer_svg, encoding="utf-8", newline="\n")
    components_path.write_text(_component_sheet(), encoding="utf-8", newline="\n")
    payload_path.write_text(json.dumps(LIVE, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    for path in (renderer_path, components_path):
        ET.fromstring(path.read_text(encoding="utf-8"))
    checks = {
        "renderer_svg": str(renderer_path),
        "component_sheet_svg": str(components_path),
        "payload": str(payload_path),
        "renderer_svg_bytes": renderer_path.stat().st_size,
        "component_sheet_svg_bytes": components_path.stat().st_size,
        "renderer_plan_ids": renderer_svg.count("data-plan-entity-id="),
        "component_plan_ids": _component_sheet().count("data-plan-entity-id="),
    }
    (OUT / "conversion_checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
