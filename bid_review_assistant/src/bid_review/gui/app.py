"""Windows 离线中文图形界面（tkinter，无网络）。"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


def run_gui(
    initial_files: list[str] | None = None,
    template: str | None = None,
    output: str | None = None,
) -> None:
    root = tk.Tk()
    root.title("招投标文件审查助手 1.0（只读·离线）")
    root.geometry("860x560")
    root.minsize(720, 480)

    files_var = tk.Variable(value=list(initial_files or []))
    template_var = tk.StringVar(value=template or "")
    output_var = tk.StringVar(value=output or str(Path.cwd() / "审查输出"))
    status_var = tk.StringVar(value="就绪。本工具不会修改原始文件，也不会上传数据。")

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        frm,
        text="招投标文件审查助手",
        font=("Microsoft YaHei UI", 16, "bold"),
    ).pack(anchor="w")
    ttk.Label(
        frm,
        text="导入 DOCX / PDF / XLSX，对照模板做格式与跨文件一致性只读核查。",
        wraplength=800,
    ).pack(anchor="w", pady=(0, 8))

    list_frame = ttk.LabelFrame(frm, text="待审查文件", padding=8)
    list_frame.pack(fill=tk.BOTH, expand=True)
    listbox = tk.Listbox(list_frame, listvariable=files_var, height=12)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    listbox.config(yscrollcommand=scroll.set)

    def add_files() -> None:
        paths = filedialog.askopenfilenames(
            title="选择招标相关文件",
            filetypes=[
                ("招标文件", "*.docx *.pdf *.xlsx"),
                ("Word", "*.docx"),
                ("PDF", "*.pdf"),
                ("Excel", "*.xlsx"),
                ("全部", "*.*"),
            ],
        )
        if not paths:
            return
        current = list(files_var.get())
        for p in paths:
            if p not in current:
                current.append(p)
        files_var.set(current)

    def remove_selected() -> None:
        sel = list(listbox.curselection())
        current = list(files_var.get())
        for i in reversed(sel):
            del current[i]
        files_var.set(current)

    btn_row = ttk.Frame(frm)
    btn_row.pack(fill=tk.X, pady=6)
    ttk.Button(btn_row, text="添加文件", command=add_files).pack(side=tk.LEFT)
    ttk.Button(btn_row, text="移除选中", command=remove_selected).pack(side=tk.LEFT, padx=6)

    tmpl_row = ttk.Frame(frm)
    tmpl_row.pack(fill=tk.X, pady=4)
    ttk.Label(tmpl_row, text="官方模板:").pack(side=tk.LEFT)
    ttk.Entry(tmpl_row, textvariable=template_var).pack(
        side=tk.LEFT, fill=tk.X, expand=True, padx=6
    )

    def pick_template() -> None:
        path = filedialog.askopenfilename(
            title="选择官方 Word 模板",
            filetypes=[("Word 模板", "*.docx")],
        )
        if path:
            template_var.set(path)

    ttk.Button(tmpl_row, text="浏览…", command=pick_template).pack(side=tk.LEFT)

    out_row = ttk.Frame(frm)
    out_row.pack(fill=tk.X, pady=4)
    ttk.Label(out_row, text="输出目录:").pack(side=tk.LEFT)
    ttk.Entry(out_row, textvariable=output_var).pack(
        side=tk.LEFT, fill=tk.X, expand=True, padx=6
    )

    def pick_output() -> None:
        path = filedialog.askdirectory(title="选择报告输出目录")
        if path:
            output_var.set(path)

    ttk.Button(out_row, text="浏览…", command=pick_output).pack(side=tk.LEFT)

    progress = ttk.Progressbar(frm, mode="indeterminate")
    progress.pack(fill=tk.X, pady=8)
    ttk.Label(frm, textvariable=status_var, wraplength=800).pack(anchor="w")

    def do_review() -> None:
        files = list(files_var.get())
        if not files:
            messagebox.showwarning("提示", "请先添加至少一个文件。")
            return
        out = output_var.get().strip() or str(Path.cwd() / "审查输出")
        tmpl = template_var.get().strip() or None
        progress.start(12)
        status_var.set("正在只读审查…")

        def worker() -> None:
            err: Exception | None = None
            summary = {}
            intact = True
            report = ""
            try:
                from bid_review.pipeline import run_review

                result, paths = run_review(files, out, tmpl)
                summary = result.summary()
                intact = all(i.unchanged for i in result.integrity)
                report = paths.get("html") or paths.get("markdown") or ""
            except Exception as exc:  # noqa: BLE001
                err = exc

            def done() -> None:
                progress.stop()
                if err is not None:
                    status_var.set(f"失败：{err}")
                    messagebox.showerror("审查失败", str(err))
                    return
                status_var.set(
                    f"完成。摘要={summary}；原文件未改动={'是' if intact else '否'}；报告={report}"
                )
                messagebox.showinfo(
                    "审查完成",
                    f"问题摘要：{summary}\n原文件 SHA-256 未改动：{'是' if intact else '否'}\n报告目录：{out}",
                )

            root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    ttk.Button(frm, text="开始只读审查", command=do_review).pack(anchor="e", pady=8)
    root.mainloop()
