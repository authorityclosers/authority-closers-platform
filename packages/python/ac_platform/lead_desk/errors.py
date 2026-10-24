"""The Lead Desk's refusal: a status and words the person can act on. Its own module, so
the store and the modules it uses (the task writer) can all raise it."""


class DeskError(Exception):
    """A refusal the person can act on; the message is shown as is."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
