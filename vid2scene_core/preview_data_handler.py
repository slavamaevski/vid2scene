import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)

class PreviewDataHandler(FileSystemEventHandler):
    def __init__(self, on_new_preview):
        super().__init__()
        self.on_new_preview = on_new_preview

    def on_closed(self, event):
        if not event.is_directory:
            self.on_new_preview(event.src_path)