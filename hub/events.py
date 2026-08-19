"""In-process publish/subscribe bus feeding the Server-Sent Events stream."""

import queue
import threading


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = []

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def publish(self, type_, **payload):
        data = dict(payload)
        data["type"] = type_
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass  # slow consumer drops events; UI also polls on interval


bus = EventBus()


def publish_doc_event(document, state):
    bus.publish(
        "document",
        state=state,
        doc_id=document.pk,
        filename=document.filename,
        phase_id=document.phase_id,
        project_id=document.phase.project_id,
    )


def publish_simple(type_):
    bus.publish(type_)
