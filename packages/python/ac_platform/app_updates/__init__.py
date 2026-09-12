"""Authenticated learner app-release updates and durable read receipts."""

from ac_platform.app_updates.application import AppUpdatesApplication
from ac_platform.app_updates.catalogue import CURRENT_ARTIFACT_RELEASES

__all__ = ["AppUpdatesApplication", "CURRENT_ARTIFACT_RELEASES"]
