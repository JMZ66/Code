"""保证质谱本体解析不访问网络。

pyteomics 5 在打开 mzML 时会通过 psims 加载 PSI-MS 受控词表。
psims 自带词表副本，但默认仍会先尝试联网。这里在任何读取之前
关掉远程访问，只使用随 psims 安装的本地副本。
"""

from __future__ import annotations


_configured = False


def enforce_offline_ontology() -> None:
    """关闭 psims 的在线词表下载。可重复调用。"""
    global _configured
    if _configured:
        return
    try:
        from psims.controlled_vocabulary.controlled_vocabulary import obo_cache
    except Exception:
        _configured = True
        return
    obo_cache.use_remote = False
    obo_cache.user_agent_emulation = False
    _configured = True
