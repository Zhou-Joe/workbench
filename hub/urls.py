from django.urls import path

from . import views

app_name = "hub"

urlpatterns = [
    path("", views.home, name="home"),
    path("project/new/", views.project_create, name="project_create"),
    path("project/<slug>/", views.project_detail, name="project"),
    path("project/<slug>/rescan/", views.project_rescan, name="project_rescan"),
    path(
        "project/<slug>/decisions/",
        views.project_decisions,
        name="project_decisions",
    ),
    path("project/<slug>/report/", views.project_report, name="project_report"),
    path("search/", views.search, name="search"),
    path("search/save/", views.search_save, name="search_save"),
    path(
        "search/<int:saved_id>/delete/",
        views.search_delete,
        name="search_delete",
    ),
    path(
        "project/<slug>/export/",
        views.project_export,
        name="project_export",
    ),
    path("series/<int:series_id>/diff/", views.series_diff, name="series_diff"),
    path("inbox/", views.inbox, name="inbox"),
    path("capture/", views.capture, name="capture"),
    path("capture/<int:capture_id>/file/", views.capture_file, name="capture_file"),
    path("capture/<int:capture_id>/skip/", views.capture_skip, name="capture_skip"),
    path("palette/", views.palette, name="palette"),
    path("protocols/", views.protocols, name="protocols"),
    path("protocols/new/", views.protocol_new, name="protocol_new"),
    path(
        "protocols/<int:protocol_id>/default/",
        views.protocol_default,
        name="protocol_default",
    ),
    path(
        "protocols/<int:protocol_id>/delete/",
        views.protocol_delete,
        name="protocol_delete",
    ),
    path(
        "protocols/<int:protocol_id>/phases/add/",
        views.protocol_phase_add,
        name="protocol_phase_add",
    ),
    path(
        "protocols/<int:protocol_id>/phases/<int:phase_id>/rename/",
        views.protocol_phase_rename,
        name="protocol_phase_rename",
    ),
    path(
        "protocols/<int:protocol_id>/phases/<int:phase_id>/move/",
        views.protocol_phase_move,
        name="protocol_phase_move",
    ),
    path(
        "protocols/<int:protocol_id>/phases/<int:phase_id>/delete/",
        views.protocol_phase_delete,
        name="protocol_phase_delete",
    ),
    path(
        "project/<slug>/calendar.ics",
        views.project_calendar,
        name="project_calendar",
    ),
    path(
        "project/<slug>/timeline/",
        views.project_timeline,
        name="project_timeline",
    ),
    path(
        "project/<slug>/tasks/",
        views.task_panel,
        name="task_panel",
    ),
    path("project/<slug>/tasks/new/", views.task_new, name="task_new"),
    path("task/<int:task_id>/status/", views.task_status, name="task_status"),
    path("task/<int:task_id>/edit/", views.task_edit, name="task_edit"),
    path("task/<int:task_id>/delete/", views.task_delete, name="task_delete"),
    path("ask/", views.ask, name="ask"),
    path("ask/clear/", views.ask_clear, name="ask_clear"),
    path(
        "project/<project_slug>/phase/<int:order>/ask/",
        views.ask_folder,
        name="ask_folder",
    ),
    path("jobs/", views.jobs, name="jobs"),
    path("jobs/<int:job_id>/retry/", views.job_retry, name="job_retry"),
    path("project/<slug>/phases/add/", views.phase_add, name="phase_add"),
    path(
        "project/<slug>/phase/<int:phase_id>/rename/",
        views.phase_rename,
        name="phase_rename",
    ),
    path(
        "project/<slug>/phase/<int:phase_id>/close/",
        views.phase_close,
        name="phase_close",
    ),
    path(
        "project/<slug>/phase/<int:phase_id>/reopen/",
        views.phase_reopen,
        name="phase_reopen",
    ),
    path(
        "project/<slug>/phase/<int:phase_id>/move/",
        views.phase_move,
        name="phase_move",
    ),
    path(
        "project/<project_slug>/phase/<int:order>/",
        views.phase_detail,
        name="phase",
    ),
    path(
        "project/<project_slug>/phase/<int:order>/upload/",
        views.phase_upload,
        name="phase_upload",
    ),
    path(
        "project/<project_slug>/phase/<int:order>/folder/new/",
        views.phase_folder_new,
        name="phase_folder_new",
    ),
    path(
        "doc/<int:doc_id>/series/new/",
        views.assign_new_series,
        name="assign_new_series",
    ),
    path(
        "doc/<int:doc_id>/series/assign/",
        views.assign_predecessor,
        name="assign_predecessor",
    ),
    path("move/<int:move_id>/undo/", views.undo_archive, name="undo_archive"),
    path("series/<int:series_id>/", views.series_stack, name="series_stack"),
    path(
        "series/<int:series_id>/delta/",
        views.series_delta,
        name="series_delta",
    ),
    path(
        "milestone/<int:ms_id>/action/",
        views.milestone_action,
        name="milestone_action",
    ),
    path("milestone/<int:ms_id>/edit/", views.milestone_edit, name="milestone_edit"),
    path("download/file/", views.download_file, name="download_file"),
    path("preview/", views.preview, name="preview"),
    path("download/folder/", views.download_folder, name="download_folder"),
    path("download/zip/", views.download_zip, name="download_zip"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/lm-status/", views.lm_status, name="lm_status"),
    path("events/", views.sse, name="sse"),
]
