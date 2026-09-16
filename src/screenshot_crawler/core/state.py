from enum import StrEnum


class PageState(StrEnum):
    CONTENT = "content"
    AD = "ad"
    END = "end"
    NEXT_CONTENT = "next_content"
    LOADING = "loading"
    UNKNOWN = "unknown"
