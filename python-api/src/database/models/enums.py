import enum


class AiStatus(str, enum.Enum):
    FIT = "fit"
    NOT_FIT = "not_fit"


class UserStatus(str, enum.Enum):
    NEW = "new"
    APPLIED = "applied"
    EMAIL_SENT = "email_sent"
    REFERRAL = "referral"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WONT_APPLY = "wont_apply"


APPLIED_BUCKET = {
    UserStatus.APPLIED,
    UserStatus.EMAIL_SENT,
    UserStatus.REFERRAL,
}
