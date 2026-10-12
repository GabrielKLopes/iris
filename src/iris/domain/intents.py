from enum import Enum


class Intent(str, Enum):
    OPEN_APP = "open_app"
    NONE = "none"
