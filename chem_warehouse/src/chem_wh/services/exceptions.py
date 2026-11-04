class AppError(Exception):
    """Base application error."""


class AuthError(AppError):
    pass


class PermissionError(AppError):
    pass


class ValidationError(AppError):
    pass


class StockError(AppError):
    pass
