from __future__ import annotations


class IngestionError(Exception):
    """A fetch/extract failure with a machine-readable code. Never converted into empty content."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class FetchError(IngestionError):
    pass


class ExtractionError(IngestionError):
    pass
