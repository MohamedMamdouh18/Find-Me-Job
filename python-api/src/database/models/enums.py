import enum


class AiStatus(str, enum.Enum):
    FIT = "fit"
    NOT_FIT = "not_fit"


class UserStatus(str, enum.Enum):
    NEW = "new"
    APPLIED = "applied"
    WONT_APPLY = "wont_apply"
