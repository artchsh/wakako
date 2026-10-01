class GscError(Exception):
    """A user-facing error. The CLI reports it and exits with `exit_code`.

    `code` is a stable machine-readable string; `hint` is an optional next step.
    """

    code = "error"
    exit_code = 1

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class UsageError(GscError):
    code = "usage"
    exit_code = 2


class AuthError(GscError):
    code = "auth"
    exit_code = 3


class PermissionDenied(GscError):
    code = "permission"
    exit_code = 4


class QuotaError(GscError):
    code = "quota"
    exit_code = 5
