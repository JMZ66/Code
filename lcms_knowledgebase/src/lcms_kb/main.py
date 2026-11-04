"""程序入口。用户双击 exe 即可，不需要安装 Python。"""

from __future__ import annotations

import sys

from lcms_kb.offline import enforce_offline_ontology


def main(argv: list[str] | None = None) -> int:
    enforce_offline_ontology()
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in args:
        from lcms_kb.selftest import run_self_test
        return run_self_test()
    from lcms_kb.ui.main_window import launch
    return launch()


if __name__ == "__main__":
    sys.exit(main())
