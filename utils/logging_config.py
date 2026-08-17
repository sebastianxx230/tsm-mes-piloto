import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from flask import g, has_request_context, request


class JsonFormatter(logging.Formatter):
    CONTEXT_FIELDS = (
        'request_id',
        'method',
        'path',
        'status',
        'duration_ms',
        'user_id',
        'ot_id',
        'packing_list_id',
        'photo_id',
        'reason',
    )

    def format(self, record):
        payload = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if has_request_context() and getattr(g, 'request_id', None):
            payload['request_id'] = g.request_id
        for field in self.CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_structured_logging(app):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)

    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(level)
    app.logger.propagate = False

    @app.before_request
    def start_request_log():
        supplied_request_id = request.headers.get('X-Request-ID', '').strip()
        g.request_id = supplied_request_id[:100] or str(uuid.uuid4())
        g.request_started_at = time.perf_counter()

    @app.after_request
    def finish_request_log(response):
        request_id = getattr(g, 'request_id', None)
        if not request_id:
            supplied_request_id = request.headers.get('X-Request-ID', '').strip()
            request_id = supplied_request_id[:100] or str(uuid.uuid4())
            g.request_id = request_id
        started_at = getattr(g, 'request_started_at', time.perf_counter())
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers['X-Request-ID'] = request_id
        app.logger.info(
            'request_completed',
            extra={
                'method': request.method,
                'path': request.path,
                'status': response.status_code,
                'duration_ms': duration_ms,
            },
        )
        return response
