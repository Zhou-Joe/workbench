from django.urls import path

from . import views

app_name = "hub"

urlpatterns = [
    path("", views.home, name="home"),
    path("project/new/", views.project_create, name="project_create"),
    path("project/<slug>/", views.project_detail, name="project"),
    path("project/<slug>/rescan/", views.project_rescan, name="project_rescan"),
    path("project/<slug>/phases/add/", views.phase_add, name="phase_add"),
    path(
        "project/<slug>/phase/<int:phase_id>/rename/",
        views.phase_rename,
        name="phase_rename",
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
    path("settings/", views.settings_view, name="settings"),
    path("settings/lm-status/", views.lm_status, name="lm_status"),
    path("events/", views.sse, name="sse"),
]
