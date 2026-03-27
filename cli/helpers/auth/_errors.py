class AuthError(Exception):
    """Raised when authentication cannot be obtained."""


class AuthScriptInvalid(AuthError):
    """Raised when the auth script is invalid."""

    def __init__(self, msg: str = "Generated auth script is invalid"):
        super().__init__(msg)


class AuthScriptError(AuthError):
    """Raised when the auth script fails at runtime (fixable by LLM)."""

    def __init__(self, msg: str = "Auth script crashed at runtime"):
        super().__init__(msg)


class AuthScriptNotFound(AuthError):
    """Raised when analyze was not run."""

    def __init__(self, msg: str = "Auth script not found, run 'spectral auth analyze-acquire' or 'spectral auth analyze-refresh' first"):
        super().__init__(msg)
