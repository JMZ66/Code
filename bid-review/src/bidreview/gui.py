"""Small Tkinter window. The review itself is the same read-only engine."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from bidreview.engine import review


class ReviewApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("招投标文件审查助手")
        root.geometry("920x640")
        self.template_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.basis_var = tk.StringVar()
        self.files: list[tuple[str, str]] = []

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="模板 DOCX").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.template_var, width=80).grid(row=0, column=1, sticky="ew")
        ttk.Button(frame, text="浏览", command=self.pick_template).grid(row=0, column=2, padx=4)

        ttk.Label(frame, text="输出目录").grid(row=1, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.out_var, width=80).grid(row=1, column=1, sticky="ew")
        ttk.Button(frame, text="浏览", command=self.pick_out).grid(row=1, column=2, padx=4)

        ttk.Label(frame, text="外部依据（可选，如 GB/T 50314）").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.basis_var, width=80).grid(row=2, column=1, sticky="ew")

        self.tree = ttk.Treeview(frame, columns=("role", "path"), show="headings", height=12)
        self.tree.heading("role", text="角色")
        self.tree.heading("path", text="文件")
        self.tree.column("role", width=120)
        self.tree.column("path", width=680)
        self.tree.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=8)

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="添加文件", command=self.add_files).pack(side="left")
        ttk.Button(buttons, text="移除所选", command=self.remove_selected).pack(side="left", padx=6)
        ttk.Label(buttons, text="角色").pack(side="left", padx=(12, 4))
        self.role_var = tk.StringVar(value="tender")
        role = ttk.Combobox(
            buttons,
            textvariable=self.role_var,
            width=16,
            values=("tender", "budget", "technical", "procurement", "contract", "attachment", "conforming", "other"),
            state="readonly",
        )
        role.pack(side="left")
        ttk.Button(buttons, text="设为套用模板", command=self.mark_conforming).pack(side="left", padx=6)
        ttk.Button(buttons, text="开始审查", command=self.execute).pack(side="left", padx=12)

        self.log = tk.Text(frame, height=14, wrap="word")
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=8)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)
        frame.rowconfigure(5, weight=1)
        self._write("只读审查。不会修改原文件，也不会联网。")

    def _write(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def pick_template(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Word", "*.docx")])
        if path:
            self.template_var.set(path)

    def pick_out(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.out_var.set(path)

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("审查文件", "*.docx *.pdf *.xlsx")])
        for path in paths:
            self.files.append((self.role_var.get() or "other", path))
            self.tree.insert("", "end", values=(self.role_var.get() or "other", path))

    def add_path(self, role: str, path: str) -> None:
        self.files.append((role, path))
        self.tree.insert("", "end", values=(role, path))

    def remove_selected(self) -> None:
        selected = set(self.tree.selection())
        kept = []
        for item, pair in zip(self.tree.get_children(), self.files):
            if item not in selected:
                kept.append(pair)
        for item in selected:
            self.tree.delete(item)
        self.files = kept

    def mark_conforming(self) -> None:
        selected = {self.tree.item(item, "values")[1] for item in self.tree.selection()}
        if not selected:
            self._write("请先在列表中选择要套用模板的文件。")
            return
        updated = []
        for role, path in self.files:
            updated.append(("conforming" if path in selected else role, path))
        self.files = updated
        for item in self.tree.get_children():
            self.tree.delete(item)
        for role, path in self.files:
            self.tree.insert("", "end", values=(role, path))

    def execute(self) -> None:
        template = self.template_var.get().strip()
        out = self.out_var.get().strip()
        if not template or not Path(template).is_file():
            self._write("请先选择模板 DOCX。")
            return
        if not out:
            self._write("请先选择输出目录。")
            return
        if not self.files:
            self._write("请先添加至少一个文件。")
            return
        rules = {}
        basis = self.basis_var.get().strip()
        if basis:
            rules = {"external_basis": [{"title": basis}]}
        documents = [(Path(path), role, "") for role, path in self.files]
        conforming = {Path(path).name for role, path in self.files if role == "conforming"}
        try:
            result = review(
                template=Path(template),
                documents=documents,
                conforming=conforming,
                rules=rules,
                out_dir=Path(out),
            )
        except Exception as exc:
            self._write(f"审查没有完成：{exc}")
            return
        self._write(f"审查完成。问题 {len(result.findings)} 条。原文件未修改：{'是' if result.inputs_unchanged else '否'}。")
        self._write(f"报告目录：{result.out_dir}")
        for finding in result.findings[:30]:
            self._write(f"{finding.finding_id} [{finding.category}] {finding.title}")
        if len(result.findings) > 30:
            self._write("其余问题见报告。")


def main() -> int:
    root = tk.Tk()
    ReviewApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
