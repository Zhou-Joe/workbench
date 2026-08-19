from .portfolio import home, project_create
from .project import (
    phase_add,
    phase_rename,
    phase_move,
    project_decisions,
    project_detail,
    project_report,
    project_rescan,
)
from .search import search
from .phase import phase_detail, phase_folder_new
from .upload import phase_upload
from .docs import (
    assign_new_series,
    assign_predecessor,
    series_stack,
    series_delta,
    undo_archive,
)
from .download import download_file, download_folder, download_zip
from .preview import preview
from .milestones import milestone_action, milestone_edit
from .settings_view import lm_status, settings_view
from .sse import sse

__all__ = [
    "home",
    "project_create",
    "project_detail",
    "project_decisions",
    "project_report",
    "search",
    "phase_add",
    "phase_rename",
    "phase_move",
    "project_rescan",
    "phase_detail",
    "phase_folder_new",
    "phase_upload",
    "assign_new_series",
    "assign_predecessor",
    "series_stack",
    "series_delta",
    "undo_archive",
    "milestone_action",
    "milestone_edit",
    "download_file",
    "download_folder",
    "download_zip",
    "preview",
    "settings_view",
    "lm_status",
    "sse",
]
