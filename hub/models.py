from django.db import models
from django.utils.text import slugify


class Protocol(models.Model):
    """A named phase template for creating projects (e.g. the six-phase
    ride development lifecycle). Projects copy phases from a protocol at
    creation time; editing a protocol never changes existing projects."""

    name = models.CharField(max_length=200)
    description = models.CharField(max_length=400, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self):
        suffix = " · default" if self.is_default else ""
        return f"{self.name}{suffix}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Protocol.objects.exclude(pk=self.pk).update(is_default=False)


class ProtocolPhase(models.Model):
    protocol = models.ForeignKey(
        Protocol, on_delete=models.CASCADE, related_name="phases"
    )
    name = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField()
    extraction_focus = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["protocol", "order"], name="uniq_protocol_phase_order"
            ),
        ]

    def __str__(self):
        return f"{self.protocol.name} / {self.order:02d} {self.name}"


class Project(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    code = models.CharField(max_length=32, blank=True)
    description = models.TextField(blank=True)
    protocol = models.ForeignKey(
        Protocol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def current_phase(self):
        """The phase the project is currently in. Explicit close-out wins:
        the first phase after the last closed one. Falls back to the latest
        phase with milestones, else the first phase."""
        phases = list(self.phases.all())
        if not phases:
            return None
        closed_orders = [p.order for p in phases if p.closed_at]
        if closed_orders:
            for phase in phases:
                if phase.order > max(closed_orders):
                    return phase
            return phases[-1]
        best = None
        for phase in phases:
            if phase.milestones.exclude(status="dismissed").exists():
                best = phase
        return best or phases[0]


class Phase(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="phases"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    order = models.PositiveSmallIntegerField()
    extraction_focus = models.TextField(blank=True)
    closed_at = models.DateTimeField(
        null=True, blank=True, help_text="Set when the phase is closed out"
    )
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


class Tag(models.Model):
    name = models.SlugField(max_length=40, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


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
    tags = models.ManyToManyField(Tag, blank=True, related_name="documents")
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
    depends_on = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="blocks"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_blocked(self):
        """A milestone is blocked while any dependency is not yet confirmed."""
        return self.depends_on.exclude(
            status__in=["confirmed", "edited"]
        ).exists()

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


class Task(models.Model):
    """User-authored work item (planned → current → done), distinct from
    extracted Milestones: tasks are what you intend to do."""

    class Status(models.TextChoices):
        PLANNED = "planned"
        CURRENT = "current"
        DONE = "done"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="tasks"
    )
    title = models.CharField(max_length=300)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=8, choices=Status, default=Status.PLANNED
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["end_date", "pk"]

    def __str__(self):
        return self.title

    @property
    def percent(self):
        """Time progress through the task window (100 when done)."""
        from datetime import date as _date

        today = _date.today()
        if self.status == self.Status.DONE:
            return 100
        if not self.start_date or not self.end_date:
            return None
        if self.start_date >= self.end_date:
            return 100 if today >= self.end_date else 0
        span = (self.end_date - self.start_date).days
        elapsed = (today - self.start_date).days
        return max(0, min(100, round(elapsed / span * 100)))

    @property
    def overdue(self):
        from datetime import date as _date

        return (
            self.status != self.Status.DONE
            and bool(self.end_date)
            and _date.today() > self.end_date
        )


class SavedSearch(models.Model):
    """A pinned query; the dashboard flags when new documents match it."""

    name = models.CharField(max_length=200)
    query = models.CharField(max_length=300)
    last_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.query})"


class Capture(models.Model):
    """Quick note dumped from anywhere — the LLM suggests where to file it."""

    class Status(models.TextChoices):
        INBOX = "inbox"
        FILED = "filed"
        SKIPPED = "skipped"

    text = models.TextField()
    status = models.CharField(max_length=8, choices=Status, default=Status.INBOX)
    suggested_project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    suggested_phase = models.ForeignKey(
        Phase, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    rationale = models.CharField(max_length=400, blank=True)
    filed_path = models.CharField(max_length=1024, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="captures")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.text[:60]


class Question(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="questions",
        null=True,
        blank=True,
    )
    folder_path = models.CharField(
        max_length=1024,
        blank=True,
        help_text="Workspace-relative folder the question was asked from",
    )
    question = models.TextField()
    answer = models.TextField(blank=True)
    citations = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=8, choices=Status, default=Status.QUEUED
    )
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.question[:80]


class ExtractionJob(models.Model):
    class Kind(models.TextChoices):
        PARSE = "parse"
        LLM = "llm"
        DIGEST = "digest"
        DELTA = "delta"
        REPORT = "report"
        ASK = "ask"
        CAPTURE = "capture"

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
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="report_jobs", null=True, blank=True
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="jobs",
        null=True,
        blank=True,
    )
    capture = models.ForeignKey(
        Capture,
        on_delete=models.CASCADE,
        related_name="jobs",
        null=True,
        blank=True,
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


class WeeklyReport(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="reports"
    )
    content = models.TextField(blank=True, help_text="Markdown report body")
    model_used = models.CharField(max_length=200, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"report {self.project} {self.created_at:%Y-%m-%d}"


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
