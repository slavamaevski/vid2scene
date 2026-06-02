import traceback
import logging

logger = logging.getLogger(__name__)

class ExceptionLoggingMiddleware:
    """
    Middleware to log exceptions with stack traces.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        logger.error(f"Unhandled exception: {exception}")
        logger.error(traceback.format_exc())
        return None
