from django.db import models
from django.utils.text import slugify


class Project(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    code = models.CharField(max_length=32, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def current_phase(self):
        """The latest phase that has any confirmed or extracted milestone."""
        phases = self.phases.all()
        if not phases:
            return None
        best = None
        for phase in phases:
            if phase.milestones.exclude(status="dismissed").exists():
                best = phase
        return best or phases.first()


class Phase(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="phases"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    order = models.PositiveSmallIntegerField()
    extraction_focus = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "order"], name="uniq_phase_order_per_project"
            ),
            models.UniqueConstraint(
                fields=["project", "slug"], name="uniq_phase_slug_per_project"
            ),
        ]

    def __str__(self):
        return f"{self.project.name} / {self.order:02d} {self.name}"

    @property
    def folder_name(self):
        return f"{self.order:02d}-{self.slug}"


class DocumentSeries(models.Model):
    phase = models.ForeignKey(
        Phase, on_delete=models.CASCADE, related_name="series"
    )
    title = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name_plural = "document series"

    def __str__(self):
        return self.title


class Document(models.Model):
    class Kind(models.TextChoices):
        PDF = "pdf"
        OFFICE = "office"
        EMAIL = "email"
        CAD = "cad"
        IMAGE = "image"
        OTHER = "other"

    class Tier(models.TextChoices):
        MINERU = "mineru"
        NATIVE = "native"
        EMAIL = "email"
        METADATA = "metadata"

    class Status(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        DONE = "done"
        FAILED = "failed"

    phase = models.ForeignKey(
        Phase, on_delete=models.CASCADE, related_name="documents"
    )
    series = models.ForeignKey(
        DocumentSeries,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revisions",
    )
    revision_number = models.PositiveIntegerField(null=True, blank=True)
    is_latest = models.BooleanField(default=True)
    file_path = models.CharField(
        max_length=1024, help_text="POSIX path relative to the workspace root"
    )
    filename = models.CharField(max_length=300)
    extension = models.CharField(max_length=16, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    file_mtime = models.DateTimeField(null=True, blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    doc_kind = models.CharField(max_length=8, choices=Kind, default=Kind.OTHER)
    doc_type_label = models.CharField(
        max_length=200, blank=True, help_text="LLM-classified document type"
    )
    extraction_tier = models.CharField(
        max_length=10, choices=Tier, blank=True
    )
    extraction_status = models.CharField(
        max_length=10, choices=Status, default=Status.PENDING
    )
    quality_note = models.CharField(
        max_length=300,
        blank=True,
        help_text="Set when extraction used a fallback path",
    )
    extracted_text = models.TextField(blank=True)
    digest_contribution = models.TextField(blank=True)
    delta_summary = models.TextField(blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)
    extracted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-ingested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["phase", "file_path", "checksum"],
                name="uniq_doc_path_checksum_per_phase",
            )
        ]

    def __str__(self):
        return self.filename

    @property
    def is_archived(self):
        parts = self.file_path.split("/")
        return len(parts) >= 2 and parts[-2] == "_archive"

    @property
    def location(self):
        """Sub-folder path inside the phase, e.g. 'structural/calcs' ('' at phase root)."""
        prefix = f"{self.phase.project.slug}/{self.phase.folder_name}/"
        if self.file_path.startswith(prefix):
            rest = self.file_path[len(prefix):]
            return rest.rpartition("/")[0]
        return ""


class Milestone(models.Model):
    class MType(models.TextChoices):
        GATE = "gate"
        DECISION = "decision"
        DELIVERABLE = "deliverable"
        ISSUE = "issue"
        RISK = "risk"
        ACTION = "action"

    class Status(models.TextChoices):
        EXTRACTED = "extracted"
        CONFIRMED = "confirmed"
        EDITED = "edited"
        DISMISSED = "dismissed"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="milestones"
    )
    phase = models.ForeignKey(
        Phase, on_delete=models.CASCADE, related_name="milestones"
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="milestones",
        null=True,
        blank=True,
    )
    date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=400)
    mtype = models.CharField(max_length=12, choices=MType, default=MType.GATE)
    status = models.CharField(
        max_length=10, choices=Status, default=Status.EXTRACTED
    )
    confidence = models.FloatField(default=0.0)
    evidence = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "pk"]

    def __str__(self):
        return f"{self.title} [{self.mtype}]"


class PhaseDigest(models.Model):
    phase = models.OneToOneField(
        Phase, on_delete=models.CASCADE, related_name="digest"
    )
    content = models.TextField(blank=True, help_text="Markdown")
    model_used = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"digest: {self.phase}"


class ExtractionJob(models.Model):
    class Kind(models.TextChoices):
        PARSE = "parse"
        LLM = "llm"
        DIGEST = "digest"
        DELTA = "delta"

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="jobs",
        null=True,
        blank=True,
    )
    series = models.ForeignKey(
        DocumentSeries,
        on_delete=models.CASCADE,
        related_name="delta_jobs",
        null=True,
        blank=True,
    )
    phase = models.ForeignKey(
        Phase, on_delete=models.CASCADE, related_name="digest_jobs", null=True, blank=True
    )
    kind = models.CharField(max_length=8, choices=Kind)
    status = models.CharField(
        max_length=8, choices=Status, default=Status.QUEUED
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        target = self.document or self.series or self.phase
        return f"{self.kind}:{target}"


class ArchiveMove(models.Model):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="moves"
    )
    from_path = models.CharField(max_length=1024)
    to_path = models.CharField(max_length=1024)
    moved_at = models.DateTimeField(auto_now_add=True)
    undone = models.BooleanField(default=False)
    undone_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.from_path} -> {self.to_path}"


class AppSettings(models.Model):
    class ArchiveMode(models.TextChoices):
        MOVE = "move"
        DB_ONLY = "db_only"

    workspace_root = models.CharField(
        max_length=1024, blank=True, help_text="Absolute path, e.g. ~/RideProjects"
    )
    lm_base_url = models.CharField(
        max_length=300, default="http://localhost:1234/v1"
    )
    lm_model = models.CharField(max_length=200, blank=True)
    lm_temperature = models.FloatField(default=0.2)
    lm_max_tokens = models.PositiveIntegerField(default=2048)
    mineru_path = models.CharField(max_length=300, default="mineru")
    mineru_timeout = models.PositiveIntegerField(default=900)
    archive_mode = models.CharField(
        max_length=8, choices=ArchiveMode, default=ArchiveMode.MOVE
    )
    watch_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "app settings"

    def expanded_workspace_root(self):
        from pathlib import Path

        raw = self.workspace_root.strip()
        if not raw:
            return None
        return str(Path(raw).expanduser())


def make_phase(project, name, order, extraction_focus=""):
    return Phase.objects.create(
        project=project,
        name=name,
        slug=slugify(name),
        order=order,
        extraction_focus=extraction_focus,
    )
