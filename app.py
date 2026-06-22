from tkinter import Tk, filedialog, messagebox

from library_validator import validate_library_root
from workflow import classify_rfa_via_revit
from rfa_reader import RfaReaderError


def choose_library_root() -> str | None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    selected_path = filedialog.askdirectory(title="選擇族群庫根目錄")
    validation = validate_library_root(selected_path)

    if not validation["valid"]:
        missing = validation.get("missing_paths", [])
        detail = ""
        if missing:
            detail = "\n\n缺少必要結構：\n" + "\n".join(f"- {path}" for path in missing[:8])
            if len(missing) > 8:
                detail += f"\n- 另有 {len(missing) - 8} 項..."
        messagebox.showerror("族群庫路徑錯誤", f"{validation['error']}{detail}")
        return None

    messagebox.showinfo("族群庫已載入", f"已選擇：\n{validation['root']}")
    return str(validation["root"])


def choose_and_classify_rfa() -> None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    selected_path = filedialog.askopenfilename(
        title="選擇要分類的 RFA",
        filetypes=[("Revit Family", "*.rfa")],
    )
    if not selected_path:
        return

    try:
        result = classify_rfa_via_revit(selected_path)
    except RfaReaderError as exc:
        messagebox.showerror("RFA 讀取失敗", str(exc))
        return

    messagebox.showinfo(
        "分類結果",
        f"狀態：{result['status']}\n建議位置：\n{result['path']}",
    )


if __name__ == "__main__":
    if choose_library_root():
        choose_and_classify_rfa()
