from __future__ import annotations


class ValidationError(Exception):
    """The export cannot be trusted; processing stops and the user is told why.

    `message` is Hebrew and shown to the accountant as-is.
    """

    def __init__(self, message: str, *, file: str | None = None, line: int | None = None):
        self.message = message
        self.file = file
        self.line = line
        super().__init__(str(self))

    def __str__(self) -> str:
        where = []
        if self.file:
            where.append(self.file)
        if self.line is not None:
            where.append(f"שורה {self.line}")
        prefix = f"[{', '.join(where)}] " if where else ""
        return prefix + self.message
