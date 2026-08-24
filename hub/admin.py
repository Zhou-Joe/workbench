from django.contrib import admin

from .models import (
    AppSettings,
    ArchiveMove,
    Document,
    DocumentSeries,
    ExtractionJob,
    Milestone,
    Phase,
    PhaseDigest,
    Project,
    Question,
    Tag,
    Task,
    WeeklyReport,
)

admin.site.site_header = "Ride Program Hub — admin"


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "code", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Phase)
class PhaseAdmin(admin.ModelAdmin):
    list_display = ("project", "order", "name", "slug")
    list_filter = ("project",)


@admin.register(DocumentSeries)
class DocumentSeriesAdmin(admin.ModelAdmin):
    list_display = ("title", "phase", "created_at")
    list_filter = ("phase__project",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "phase",
        "series",
        "revision_number",
        "is_latest",
        "doc_kind",
        "extraction_tier",
        "extraction_status",
        "ingested_at",
    )
    list_filter = ("phase__project", "doc_kind", "extraction_tier", "extraction_status")
    search_fields = ("filename", "file_path")


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ("date", "title", "mtype", "status", "project", "phase", "document")
    list_filter = ("project", "mtype", "status")
    search_fields = ("title", "evidence")


@admin.register(PhaseDigest)
class PhaseDigestAdmin(admin.ModelAdmin):
    list_display = ("phase", "model_used", "updated_at")


@admin.register(ExtractionJob)
class ExtractionJobAdmin(admin.ModelAdmin):
    list_display = ("kind", "status", "document", "series", "phase", "attempts", "created_at")
    list_filter = ("kind", "status")


@admin.register(ArchiveMove)
class ArchiveMoveAdmin(admin.ModelAdmin):
    list_display = ("document", "from_path", "to_path", "moved_at", "undone")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "start_date", "end_date", "completed_at")
    list_filter = ("status", "project")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("question", "project", "status", "created_at")
    list_filter = ("status", "project")


@admin.register(WeeklyReport)
class WeeklyReportAdmin(admin.ModelAdmin):
    list_display = ("project", "model_used", "created_at")
    list_filter = ("project",)


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ("workspace_root", "lm_base_url", "lm_model", "archive_mode", "watch_enabled")
