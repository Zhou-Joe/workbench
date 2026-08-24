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
from .ask import ask, ask_clear, ask_folder
from .capture import capture, capture_file, capture_skip, inbox
from .download import download_file, download_folder, download_zip
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
