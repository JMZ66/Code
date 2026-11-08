import sys

from bidreview.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        from bidreview.gui import main as gui_main

        raise SystemExit(gui_main())
    raise SystemExit(main())
