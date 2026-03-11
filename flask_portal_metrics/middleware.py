"""Flask middleware for automatic request/response tracking.

This module provides middleware that hooks into Flask's request lifecycle
to automatically capture HTTP request metrics without requiring code changes.
"""

import hashlib
import random
import time
import logging
from datetime import datetime
from functools import wraps
from typing import TYPE_CHECKING, Callable, List, Optional, Set

from flask import Flask, g, request, session

if TYPE_CHECKING:
    from .core import PortalMetrics

logger = logging.getLogger(__name__)


class MetricsMiddleware:
    """Middleware for automatic Flask request/response tracking.

    This middleware hooks into Flask's before_request and after_request
    to capture timing, user identification, and request metadata.

    Attributes:
        portal_metrics: Parent PortalMetrics instance
        exclude_endpoints: Set of endpoint names to exclude from tracking
        exclude_paths: Set of path prefixes to exclude
        sample_rate: Fraction of requests to track (0.0 to 1.0)
        hash_ip: Whether to hash IP addresses for privacy
    """

    def __init__(
        self,
        portal_metrics: "PortalMetrics",
        exclude_endpoints: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        sample_rate: float = 1.0,
        hash_ip: bool = False,
    ):
        """Initialize the metrics middleware.

        Args:
            portal_metrics: Parent PortalMetrics instance
            exclude_endpoints: List of endpoint names to skip tracking
            exclude_paths: List of path prefixes to skip tracking
            sample_rate: Fraction of requests to track (default: 1.0 = 100%)
            hash_ip: Hash IP addresses for privacy compliance
        """
        self.portal_metrics = portal_metrics
        self.exclude_endpoints: Set[str] = set(exclude_endpoints or ["static"])
        self.exclude_paths: Set[str] = set(exclude_paths or [])
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.hash_ip = hash_ip
        self._secret_key: Optional[str] = None

    def init_app(self, app: Flask) -> None:
        """Register middleware with Flask application.

        Args:
            app: Flask application instance
        """
        self._secret_key = app.config.get("SECRET_KEY", "default-salt")

        app.before_request(self._before_request)
        app.after_request(self._after_request)

        logger.debug(
            f"MetricsMiddleware initialized with sample_rate={self.sample_rate}, "
            f"exclude_endpoints={self.exclude_endpoints}"
        )

    def _should_track(self) -> bool:
        """Determine if the current request should be tracked.

        Returns:
            bool: True if request should be tracked, False otherwise
        """
        # Check sampling rate
        if self.sample_rate < 1.0 and random.random() > self.sample_rate:
            return False

        # Check excluded endpoints
        endpoint = request.endpoint
        if endpoint and endpoint in self.exclude_endpoints:
            return False

        # Check excluded paths
        path = request.path
        for excluded_path in self.exclude_paths:
            if path.startswith(excluded_path):
                return False

        return True

    def _hash_ip_address(self, ip: str) -> str:
        """Hash an IP address for privacy.

        Args:
            ip: Original IP address

        Returns:
            str: Hashed IP address
        """
        if not ip:
            return ""

        salt = self._secret_key or "default-salt"
        return hashlib.sha256(f"{salt}{ip}".encode()).hexdigest()[:32]

    def _get_client_ip(self) -> str:
        """Get the client's IP address, respecting proxy headers.

        Returns:
            str: Client IP address (optionally hashed)
        """
        # Check for proxy headers (in order of preference)
        ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.headers.get("X-Real-IP", "")
            or request.remote_addr
            or ""
        )

        if self.hash_ip and ip:
            return self._hash_ip_address(ip)

        return ip

    def _get_user_id(self) -> Optional[str]:
        """Get the current user's ID if available.

        Attempts to retrieve user_id from:
        1. Flask g object
        2. Session
        3. Flask-Login current_user

        Returns:
            Optional[str]: User ID or None
        """
        # Check g object
        user_id = getattr(g, "user_id", None) or getattr(g, "current_user_id", None)
        if user_id:
            return str(user_id)

        # Check session
        user_id = session.get("user_id") or session.get("_user_id")
        if user_id:
            return str(user_id)

        # Try Flask-Login integration
        try:
            from flask_login import current_user

            if current_user.is_authenticated:
                return str(
                    getattr(current_user, "id", None) or getattr(current_user, "user_id", None)
                )
        except (ImportError, AttributeError):
            pass

        return None

    def _get_session_id(self) -> str:
        """Get or create a session identifier.

        Returns:
            str: Session identifier
        """
        session_id = session.get("_portal_metrics_session_id")
        if not session_id:
            import uuid

            session_id = str(uuid.uuid4())
            try:
                session["_portal_metrics_session_id"] = session_id
            except RuntimeError:
                # Session is read-only or unavailable
                pass
        return session_id

    def _before_request(self) -> None:
        """Hook called before each request.

        Records the start time and determines if tracking is active.
        """
        g._portal_metrics_start_time = time.perf_counter()
        g._portal_metrics_should_track = self._should_track()

    def _after_request(self, response):
        """Hook called after each request.

        Records the request metrics if tracking is active.

        Args:
            response: Flask response object

        Returns:
            response: Unmodified Flask response object
        """
        try:
            if not getattr(g, "_portal_metrics_should_track", False):
                return response

            # Calculate response time
            start_time = getattr(g, "_portal_metrics_start_time", None)
            response_time_ms = None
            if start_time:
                response_time_ms = (time.perf_counter() - start_time) * 1000

            # Gather request data
            activity_data = {
                "endpoint": request.endpoint,
                "method": request.method,
                "path": request.path,
                "response_code": response.status_code,
                "response_time_ms": response_time_ms,
                "user_id": self._get_user_id(),
                "session_id": self._get_session_id(),
                "ip_address": self._get_client_ip(),
                "user_agent": request.headers.get("User-Agent", "")[:512],
                "referrer": request.headers.get("Referer", "")[:2048],
                "query_string": (
                    request.query_string.decode("utf-8", errors="ignore")[:2048]
                    if request.query_string
                    else None
                ),
                "request_size": request.content_length,
                "response_size": response.content_length,
                "timestamp": datetime.utcnow(),
            }

            # Record the activity
            self.portal_metrics._record_user_activity(activity_data)

        except Exception as e:
            # Never let analytics failures break the application
            logger.error(f"Error recording request metrics: {e}", exc_info=True)

        return response


def track_endpoint(
    portal_metrics: "PortalMetrics",
    event_name: Optional[str] = None,
    metadata_fn: Optional[Callable] = None,
):
    """Decorator to track specific endpoint calls as custom events.

    This decorator can be used to add custom event tracking to specific
    endpoints in addition to the automatic request tracking.

    Args:
        portal_metrics: PortalMetrics instance
        event_name: Custom event name (defaults to endpoint name)
        metadata_fn: Optional function that returns metadata dict

    Returns:
        Decorator function

    Example:
        @app.route('/api/upload')
        @track_endpoint(metrics, 'file_upload', lambda: {'file_type': request.args.get('type')})
        def upload():
            # ...
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            result = f(*args, **kwargs)

            try:
                name = event_name or f.__name__
                metadata = metadata_fn() if metadata_fn else None
                portal_metrics.track_event(name, metadata=metadata)
            except Exception as e:
                logger.error(f"Error tracking endpoint event: {e}", exc_info=True)

            return result

        return wrapper

    return decorator
