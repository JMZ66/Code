"""本程序自己的异常。界面把这些异常转成中文说明。"""


class LCMSError(Exception):
    """所有可向分析人员说明的错误的基类。"""


class PolarityMismatch(LCMSError):
    """比较两侧极性不一致，且用户没有明确允许混合。"""


class EnergyMismatch(LCMSError):
    """比较两侧碰撞能量不一致，且用户没有明确允许混合。"""


class RawFileChanged(LCMSError):
    """读完之后原始文件的哈希和读之前不同。"""


class BackupError(LCMSError):
    """备份或恢复失败。当前数据库应保持原样。"""


class ConfirmationError(LCMSError):
    """缺少明确的人工确认动作或确认依据。"""


class ConverterUnavailable(LCMSError):
    """用户还没有安装或指定外部转换程序。"""


class UnsupportedFormat(LCMSError):
    """扩展名不是本程序能直接读取的开放格式。"""
