from datetime import datetime
import os

from zoneinfo import ZoneInfo

CV_PATH = "/data/cv.docx"
PARAMS_DIR = "/data/params"

TIMEZONE = ZoneInfo(os.getenv("GENERIC_TIMEZONE", "UTC"))


def now():
    return datetime.now(TIMEZONE)
