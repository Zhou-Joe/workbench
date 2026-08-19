"""Process all pending extraction jobs once, then exit.

Usage: manage.py process_queue [--watch]
"""

from django.core.management.base import BaseCommand

from hub.worker import Worker


class Command(BaseCommand):
    help = "Process pending extraction jobs (parse/LLM/digest/delta)."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="keep running")

    def handle(self, *args, **options):
        worker = Worker()
        if options["watch"]:
            self.stdout.write("processing queue continuously — Ctrl-C to stop")
            worker.run_forever()
        else:
            worker.run_pending()
            self.stdout.write("queue drained.")
