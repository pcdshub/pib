from __future__ import annotations

import datetime
import logging
import os
import pathlib

MODULE_PATH = pathlib.Path(__file__).resolve().parent


logger = logging.getLogger(__name__)


def dt_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).astimezone()


def get_host_arch() -> str:
    """Get the EPICS host architecture."""
    return os.environ["EPICS_HOST_ARCH"]
