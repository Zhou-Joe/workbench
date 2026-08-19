"""Global context for the masthead: attention badges."""

from .models import Capture, ExtractionJob


def masthead(request):
    try:
        return {
            "inbox_count": Capture.objects.filter(status="inbox").count(),
            "jobs_failed": ExtractionJob.objects.filter(status="failed").count(),
        }
    except Exception:
        return {"inbox_count": 0, "jobs_failed": 0}
