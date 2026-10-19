"""One refusal type for the developer platform: a safe code and an HTTP status."""


class IntegrationError(ValueError):
    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
