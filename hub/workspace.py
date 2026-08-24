"""Filesystem layout: scaffolding, renames, archival — the only code that
touches the workspace on disk. The app never modifies file contents."""

import shutil
from pathlib import Path

from django.utils.text import slugify

ARCHIVE_DIR = "_archive"
SETTINGS_NAME = "settings"

# Default sub-folders created inside every new phase (and addable at will)
PHASE_SUBFOLDER_TEMPLATE = ("01-incoming", "02-working", "03-issued")


def project_root(settings, project):
    root = settings.expanded_workspace_root()
    if not root:
        raise RuntimeError("Workspace root is not configured — set it on the Settings screen.")
    return Path(root) / project.slug


def phase_dir(settings, project, phase):
    return project_root(settings, project) / phase.folder_name


def archive_dir(settings, project, phase):
    return phase_dir(settings, project, phase) / ARCHIVE_DIR


def scaffold_project(settings, project, phases):
    """Create the project folder tree for the given Phase objects."""
    root = settings.expanded_workspace_root()
    if not root:
        raise RuntimeError("Workspace root is not configured — set it on the Settings screen.")
    (Path(root) / project.slug).mkdir(parents=True, exist_ok=True)
    for phase in phases:
        pdir = phase_dir(settings, project, phase)
        pdir.mkdir(parents=True, exist_ok=True)
        for sub in PHASE_SUBFOLDER_TEMPLATE:
            (pdir / sub).mkdir(exist_ok=True)


def safe_subpath(base_dir, path_str):
    """Validate a user-supplied relative path ('a/b') against base_dir.
    Unsafe segments are dropped; the result always resolves to base_dir or
    something strictly inside it (separator-bounded check, symlink-proof)."""
    import os

    segments = [
        s
        for s in (path_str or "").strip("/").split("/")
        if s and not s.startswith(".") and s not in ("..", ARCHIVE_DIR)
    ]
    candidate = base_dir.joinpath(*segments) if segments else base_dir
    resolved = candidate.resolve()
    base = base_dir.resolve()
    if resolved == base or str(resolved).startswith(str(base) + os.sep):
        return resolved
    return base


def folder_item_count(path):
    """Recursive item count for a folder row, Finder-style."""
    count = 0
    for child in path.rglob("*"):
        rel = child.relative_to(path)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if ARCHIVE_DIR in rel.parts:
            continue
        if child.is_file():
            count += 1
    return count


def create_subfolder(settings, project, phase, path_str, name):
    """Create a folder inside path_str. The name may contain '/' to create
    nested levels in one step ('vendor/reports'); returns the created path."""
    base = safe_subpath(phase_dir(settings, project, phase), path_str)
    segments = []
    existing = {p.name for p in base.iterdir() if p.is_dir()}
    for raw in name.split("/"):
        if raw.startswith(".") or raw in ("..", ARCHIVE_DIR):
            continue
        slug = slugify_folder(raw, existing)
        if not slug:
            continue
        segments.append(slug)
        existing = set()  # deeper level starts fresh
    if not segments:
        return ""
    base.joinpath(*segments).mkdir(parents=True, exist_ok=True)
    return "/".join(segments)


def sync_phase_dirs(settings, project):
    """After add/rename/reorder: rename existing phase folders to their new
    order/slug, then create any missing ones. Document paths are rewritten
    to follow folder renames so the index never orphans. File contents are
    untouched."""
    root = project_root(settings, project)
    if not root.exists():
        scaffold_project(settings, project, project.phases.all())
        return
    expected = {ph.folder_name for ph in project.phases.all()}
    # Pass 1: rename old folders whose NN-slug no longer matches a phase.
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name == ARCHIVE_DIR:
            continue
        if child.name in expected:
            continue
        stem = child.name.split("-", 1)[-1] if "-" in child.name else child.name
        owner = next((ph for ph in project.phases.all() if ph.slug == stem), None)
        if owner is None:
            continue
        dest = root / owner.folder_name
        if dest == child:
            continue
        if dest.exists():
            tmp = root / f".tmp-{child.name}"
            child.rename(tmp)
            child = tmp
        child.rename(dest)
        _rewrite_document_prefix(project, f"{project.slug}/{child.name}/", f"{project.slug}/{dest.name}/")
    # Pass 2: create folders for phases that do not have one yet.
    for phase in project.phases.all():
        (root / phase.folder_name).mkdir(parents=True, exist_ok=True)


def _rewrite_document_prefix(project, old_prefix, new_prefix):
    """Keep Document.file_path (and archive rows) pointing at real files
    after a phase folder rename."""
    from django.db.models import Value
    from django.db.models.functions import Replace

    from .models import ArchiveMove, Document

    Document.objects.filter(file_path__startswith=old_prefix).update(
        file_path=Replace("file_path", Value(old_prefix), Value(new_prefix))
    )
    ArchiveMove.objects.filter(from_path__startswith=old_prefix).update(
        from_path=Replace("from_path", Value(old_prefix), Value(new_prefix))
    )
    ArchiveMove.objects.filter(to_path__startswith=old_prefix).update(
        to_path=Replace("to_path", Value(old_prefix), Value(new_prefix))
    )


def unique_folder_name(path):
    """Return path, suffixed -1, -2… if it already exists."""
    if not path.exists():
        return path
    i = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def archive_file(settings, document):
    """Move a superseded revision into its phase's _archive/ folder.
    Returns (from_rel, to_rel) relative to the workspace root."""
    root = Path(settings.expanded_workspace_root())
    src = root / document.file_path
    if not src.exists():
        return None
    dest_dir = archive_dir(settings, document.phase.project, document.phase)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_folder_name(dest_dir / src.name)
    shutil.move(str(src), str(dest))
    return str(src.relative_to(root)), str(dest.relative_to(root))


def restore_file(settings, from_rel, to_rel):
    """Undo an archive move."""
    root = Path(settings.expanded_workspace_root())
    src = root / to_rel
    dest = root / from_rel
    if not src.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return True


def slugify_folder(name, existing):
    base = slugify(name) or "phase"
    slug = base
    i = 2
    while slug in existing:
        slug = f"{base}-{i}"
        i += 1
    return slug
