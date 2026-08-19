import json
import queue

from django.http import StreamingHttpResponse


def sse(request):
    q = _bus().subscribe()

    def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    data = q.get(timeout=15)
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            _bus().unsubscribe(q)

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _bus():
    from ..events import bus

    return bus
