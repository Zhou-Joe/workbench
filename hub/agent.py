"""LangChain tool-using agent over the ride project workspace.

The agent gets tools to browse projects/phases/folders, read extracted
document text, search full text, and query the milestone ledger — it
decides for itself which files to open. Documents it actually reads are
collected so the answer can carry real citations.

Model: LM Studio's OpenAI-compatible endpoint (init_chat_model with
model_provider="openai" and a custom base_url). Requires a tool-calling
capable model (e.g. Qwen3).
"""

from . import workspace
from .models import AppSettings, Document, Milestone, Phase, Project

READ_CHARS = 6_000
LIST_LIMIT = 60


def run_agent_question(question_text, project=None):
    """Returns (answer_text, [Document, ...] actually read/searched)."""
    from langchain.agents import create_agent
    from langchain.chat_models import init_chat_model

    settings = AppSettings.load()
    if not settings.lm_model:
        raise RuntimeError("No model configured — set it on the Settings screen.")

    collector = {}

    def remember(doc):
        collector.setdefault(doc.pk, doc)

    model = init_chat_model(
        model=settings.lm_model,
        model_provider="openai",
        base_url=settings.lm_base_url,
        api_key="lm-studio",
        temperature=settings.lm_temperature,
        timeout=240,
    )
    agent = create_agent(
        model,
        tools=_build_tools(settings, project, remember),
        system_prompt=_system_prompt(project),
    )
    result = agent.invoke({"messages": [("user", question_text)]})
    answer = result["messages"][-1].content
    if hasattr(answer, "text"):  # content blocks on some model integrations
        answer = answer.text
    return answer, list(collector.values())


def _system_prompt(project):
    scope = f"the project '{project.name}'" if project else "all projects"
    return (
        "You are a document agent for a ride development engineer. Answer the "
        f"engineer's question using ONLY information from {scope}, retrieved "
        "with your tools. Workflow: list structure or search first, then READ "
        "the most relevant documents before answering. Cite the documents you "
        "used by filename in square brackets, e.g. [minutes.docx]. If nothing "
        "in the documents answers the question, say so plainly and name the "
        f"document kind that would. You are limited to {scope}. Be concrete: "
        "names, dates, numbers. Answer in the language of the question."
    )


def _build_tools(settings, project, remember):
    """Plain functions with type hints + docstrings — create_agent accepts
    these directly as tools. Each returns a string for the model."""

    scope_projects = (
        Project.objects.filter(pk=project.pk) if project else Project.objects.all()
    )

    def list_projects_and_phases() -> str:
        """List every available project with its phases and document counts.
        Call this first when you don't know where to look."""
        lines = []
        for p in scope_projects.prefetch_related("phases"):
            lines.append(f"PROJECT {p.slug} — {p.name}")
            for ph in p.phases.all():
                n = ph.documents.count()
                lines.append(f"  phase {ph.order:02d} {ph.slug} — {n} docs")
        return "\n".join(lines) or "(no projects)"

    def list_folder(project_slug: str, phase_order: int, path: str = "") -> str:
        """List folders and files inside one phase folder (or a sub-folder of
        it). path is the sub-folder relative to the phase root, e.g.
        '01-incoming/vendor-a'. Returns file paths usable with read_document."""
        try:
            phase = Phase.objects.get(
                project__slug=project_slug, order=phase_order
            )
        except Phase.DoesNotExist:
            return f"error: no phase {phase_order} in project '{project_slug}'"
        if project and phase.project_id != project.pk:
            return "error: phase is outside the allowed project"
        try:
            base = workspace.phase_dir(settings, phase.project, phase).resolve()
            cur = workspace.safe_subpath(base, path)
        except (RuntimeError, OSError) as exc:
            return f"error: {exc}"
        if not cur.is_dir():
            return "error: folder not found"
        from pathlib import Path

        ws_root = Path(settings.expanded_workspace_root()).resolve()
        lines = []
        for child in sorted(cur.iterdir(), key=lambda p: p.name.lower())[:LIST_LIMIT]:
            if child.name.startswith(".") or child.name == workspace.ARCHIVE_DIR:
                continue
            rel = child.relative_to(ws_root).as_posix()
            if child.is_dir():
                lines.append(f"DIR  {rel}/")
            elif child.is_file():
                doc = Document.objects.filter(file_path=rel).first()
                state = doc.extraction_status if doc else "not-indexed"
                lines.append(f"FILE {rel} ({state})")
        return "\n".join(lines) or "(empty folder)"

    def read_document(path: str) -> str:
        """Read the extracted text of one document. path is the full
        workspace-relative path as shown by list_folder, e.g.
        'carousel/04-detail-design-and-review/01-incoming/report.pdf'."""
        doc = Document.objects.select_related("phase", "phase__project").filter(
            file_path=path.strip()
        ).first()
        if doc is None:
            return "error: document not found — use list_folder to get exact paths"
        if project and doc.phase.project_id != project.pk:
            return "error: document is outside the allowed project"
        remember(doc)
        text = (doc.extracted_text or "").strip()
        if not text:
            return f"[{doc.filename}] has no extracted text (metadata-only file)"
        if len(text) > READ_CHARS:
            text = text[:READ_CHARS] + "\n[…truncated…]"
        return f"[{doc.filename}]\n{text}"

    def search_documents(query: str) -> str:
        """Full-text search across extracted documents (filenames and
        content). Returns matching paths with context — then use
        read_document on the best hits."""
        q = query.strip()
        if len(q) < 2:
            return "error: query too short"
        docs = (
            Document.objects.filter(extracted_text__icontains=q)
            | Document.objects.filter(filename__icontains=q)
        ).select_related("phase", "phase__project").order_by("-ingested_at")
        if project:
            docs = docs.filter(phase__project=project)
        lines = []
        for doc in docs[:8]:
            remember(doc)
            text = (doc.extracted_text or "").lower()
            idx = text.find(q.lower())
            snippet = ""
            if idx >= 0:
                snippet = doc.extracted_text[max(0, idx - 80) : idx + 120].replace(
                    "\n", " "
                )
            lines.append(f"{doc.file_path} :: {snippet}")
        return "\n".join(lines) or "(no matches)"

    def get_milestones(project_slug: str = "", milestone_type: str = "") -> str:
        """Query the milestone ledger (dates, gates, decisions, issues,
        risks, actions) with their source documents. milestone_type is one
        of: gate, decision, deliverable, issue, risk, action."""
        qs = Milestone.objects.exclude(status="dismissed").select_related(
            "phase", "phase__project", "document"
        )
        if project:
            qs = qs.filter(project=project)
        elif project_slug:
            qs = qs.filter(project__slug=project_slug)
        if milestone_type:
            qs = qs.filter(mtype=milestone_type)
        lines = []
        for m in qs.order_by("-date", "-pk")[:40]:
            date = m.date.isoformat() if m.date else "no-date"
            src = m.document.filename if m.document else "?"
            lines.append(f"{date} [{m.mtype}] {m.title} — source: {src}")
        return "\n".join(lines) or "(no milestones)"

    return [
        list_projects_and_phases,
        list_folder,
        read_document,
        search_documents,
        get_milestones,
    ]
