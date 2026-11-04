"""Child process for crash tests. Not a test module."""

from __future__ import annotations

import sys
import time
from pathlib import Path


def main() -> None:
    mode, src, db, cid, ready, user, password = sys.argv[1:8]
    sys.path.insert(0, src)
    ready_path = Path(ready)
    try:
        from chem_wh.app_context import AppContext

        ctx = AppContext(db)
        if mode == "open-tx":
            conn = ctx.db.conn
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE containers SET quantity=12345 WHERE id=?", (int(cid),))
            ready_path.write_text("ready", encoding="utf-8")
            time.sleep(60)
        elif mode == "commit-then-sleep":
            operator = ctx.auth.authenticate(user, password)
            ctx.stock.post_transaction(
                operator=operator,
                tx_type="issue",
                container_id=int(cid),
                quantity=1,
                remark="已提交后被结束进程",
            )
            ready_path.write_text("ready", encoding="utf-8")
            time.sleep(60)
        else:
            ready_path.write_text("ERROR:unknown mode", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        ready_path.write_text("ERROR:" + str(exc), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
