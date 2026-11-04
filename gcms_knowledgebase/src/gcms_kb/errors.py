class GCMSError(Exception):
    """本程序可向实验人员展示的错误。"""


class EmptyRun(GCMSError):
    pass


class OriginalModified(GCMSError):
    pass


class UnsafePath(GCMSError):
    pass


class ConverterNotConfigured(GCMSError):
    pass


class ConversionFailed(GCMSError):
    pass


class CorruptBackup(GCMSError):
    pass


class SchemaError(GCMSError):
    pass


class ValidationError(GCMSError):
    pass
