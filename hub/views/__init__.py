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
from .search import search, search_delete, search_save
from .phase import phase_close, phase_detail, phase_folder_new, phase_reopen
from .upload import phase_upload
from .docs import (
    assign_new_series,
    assign_predecessor,
    series_stack,
    series_delta,
    undo_archive,
)
from .ask import ask, ask_clear, ask_folder
from .capture import capture, capture_file, capture_skip, inbox
from .diff import series_diff
from .download import download_file, download_folder, download_zip
from .export import project_export
from .jobs import job_retry, jobs
from .palette import palette
from .preview import preview
from .tasks import task_delete, task_edit, task_new, task_panel, task_status
from .protocols import (
    protocol_default,
    protocol_delete,
    protocol_new,
    protocol_phase_add,
    protocol_phase_delete,
    protocol_phase_move,
    protocol_phase_rename,
    protocols,
)
from .timeline import project_calendar, project_timeline
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
    "search_save",
    "search_delete",
    "series_diff",
    "project_export",
    "phase_add",
    "phase_rename",
    "phase_move",
    "project_rescan",
    "phase_detail",
    "phase_folder_new",
    "phase_close",
    "phase_reopen",
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
    "ask",
    "ask_clear",
    "ask_folder",
    "capture",
    "capture_file",
    "capture_skip",
    "inbox",
    "palette",
    "protocols",
    "protocol_new",
    "protocol_default",
    "protocol_delete",
    "protocol_phase_add",
    "protocol_phase_rename",
    "protocol_phase_move",
    "protocol_phase_delete",
    "project_calendar",
    "project_timeline",
    "task_panel",
    "task_new",
    "task_status",
    "task_edit",
    "task_delete",
    "jobs",
    "job_retry",
    "settings_view",
    "lm_status",
    "sse",
]
