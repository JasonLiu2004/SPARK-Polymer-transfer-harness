"""Structured download outcomes, shared by CLI and harness."""
from datetime import datetime, timezone
import socket
import ssl
from urllib.error import HTTPError, URLError


class DownloadError(ValueError):
    def __init__(self, record):
        self.record = record
        super().__init__(record['message'])


def failure_record(url, exc, resolved_url=None, stage='download'):
    status = None
    category, retryable, action = 'unknown_error', False, 'inspect_error'
    if isinstance(exc, HTTPError):
        status, resolved_url = exc.code, exc.geturl()
        category = {401: 'authentication_required', 403: 'access_denied',
                    404: 'not_found', 410: 'gone', 429: 'rate_limited'}.get(status, 'http_error')
        retryable = status in (408, 429) or status >= 500
        if status >= 500:
            category = 'server_error'
        action = 'retry_with_backoff' if retryable else 'find_alternative_source_or_manual_download'
    else:
        cause = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(cause, (TimeoutError, socket.timeout)):
            category, retryable, action = 'timeout', True, 'retry_with_backoff'
        elif isinstance(cause, ssl.SSLError):
            category, action = 'tls_error', 'check_certificate_and_network'
        elif isinstance(exc, URLError) or isinstance(cause, ConnectionError):
            category, retryable, action = 'network_error', True, 'check_network_then_retry'
        elif stage == 'validate_pdf':
            category, action = 'invalid_pdf', 'find_alternative_source'
        elif stage == 'save_file':
            category, action = 'local_io_error', 'check_output_directory'
        elif isinstance(exc, ValueError):
            category, action = 'invalid_request_or_size_limit', 'check_url_and_download_limit'
    return {'url': url, 'resolved_url': resolved_url, 'status': 'failed', 'stage': stage,
            'error_category': category, 'http_status': status, 'retryable': retryable,
            'next_action': action, 'message': str(exc),
            'attempted_at': datetime.now(timezone.utc).isoformat()}
