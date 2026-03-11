"""Core PortalMetrics class for flask-portal-metrics.

This module provides the main entry point for the flask-portal-metrics
package, handling initialization, configuration, and coordination of
all tracking features.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from flask import Flask, Blueprint
from flask_sqlalchemy import SQLAlchemy

from .models import create_models
from .middleware import MetricsMiddleware
from .exports import create_export_blueprint, PowerBIExporter

logger = logging.getLogger(__name__)


class PortalMetricsConfig:
    """Configuration container for PortalMetrics.

    Attributes:
        schema: Database schema for analytics tables
        track_forms: Enable form interaction tracking
        track_performance: Enable performance metrics
        sample_rate: Fraction of requests to track (0.0 to 1.0)
        exclude_endpoints: Endpoints to exclude from tracking
        exclude_paths: Path prefixes to exclude from tracking
        hash_ip: Hash IP addresses for privacy
        sensitive_fields: Form field names to never track
        retention_days: Days to retain data (0 = no auto-cleanup)
        enable_export_endpoint: Enable Power BI export endpoint
        export_endpoint: URL for export endpoint
        async_enabled: Use async writes (requires Celery)
    """

    def __init__(
        self,
        schema: Optional[str] = None,
        track_forms: bool = True,
        track_performance: bool = True,
        sample_rate: float = 1.0,
        exclude_endpoints: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        hash_ip: bool = False,
        sensitive_fields: Optional[List[str]] = None,
        retention_days: int = 90,
        enable_export_endpoint: bool = True,
        export_endpoint: str = "/api/metrics/powerbi",
    ):
        self.schema = schema
        self.track_forms = track_forms
        self.track_performance = track_performance
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.exclude_endpoints = exclude_endpoints or ["static"]
        self.exclude_paths = exclude_paths or []
        self.hash_ip = hash_ip
        self.sensitive_fields = sensitive_fields or [
            "password",
            "token",
            "secret",
            "credit_card",
            "cvv",
            "ssn",
            "social_security",
            "api_key",
            "private_key",
        ]
        self.retention_days = retention_days
        self.enable_export_endpoint = enable_export_endpoint
        self.export_endpoint = export_endpoint
        self.async_enabled = False
        self._celery = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "schema": self.schema,
            "track_forms": self.track_forms,
            "track_performance": self.track_performance,
            "sample_rate": self.sample_rate,
            "exclude_endpoints": self.exclude_endpoints,
            "exclude_paths": self.exclude_paths,
            "hash_ip": self.hash_ip,
            "sensitive_fields": self.sensitive_fields,
            "retention_days": self.retention_days,
            "enable_export_endpoint": self.enable_export_endpoint,
            "export_endpoint": self.export_endpoint,
            "async_enabled": self.async_enabled,
        }


class PortalMetrics:
    """Main class for flask-portal-metrics.

    Provides drop-in user activity tracking for Flask applications
    with Power BI integration.

    Example (direct initialization):
        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        from flask_portal_metrics import PortalMetrics

        app = Flask(__name__)
        db = SQLAlchemy(app)
        metrics = PortalMetrics(app, db)

    Example (app factory pattern):
        # extensions.py
        from flask_sqlalchemy import SQLAlchemy
        from flask_portal_metrics import PortalMetrics

        db = SQLAlchemy()
        metrics = PortalMetrics(db=db)

        # __init__.py
        from .extensions import db, metrics

        def create_app():
            app = Flask(__name__)
            db.init_app(app)
            metrics.init_app(app)
            return app

    Attributes:
        app: Flask application instance
        db: SQLAlchemy database instance
        config: PortalMetricsConfig instance
        models: Dictionary of SQLAlchemy model classes
    """

    def __init__(
        self,
        app: Optional[Flask] = None,
        db: Optional[SQLAlchemy] = None,
        schema: Optional[str] = None,
        track_forms: bool = True,
        track_performance: bool = True,
        sample_rate: float = 1.0,
        exclude_endpoints: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
        hash_ip: bool = False,
        sensitive_fields: Optional[List[str]] = None,
        retention_days: int = 90,
        enable_export_endpoint: bool = True,
        export_endpoint: str = "/api/metrics/powerbi",
    ):
        """Initialize PortalMetrics.

        Args:
            app: Flask application (optional, can use init_app later)
            db: SQLAlchemy database instance (can be passed here for app factory pattern)
            schema: Database schema for analytics tables
            track_forms: Enable form interaction tracking
            track_performance: Enable performance metrics
            sample_rate: Fraction of requests to track (0.0 to 1.0)
            exclude_endpoints: Endpoints to exclude from tracking
            exclude_paths: Path prefixes to exclude from tracking
            hash_ip: Hash IP addresses for privacy
            sensitive_fields: Form field names to never track
            retention_days: Days to retain data (0 = no auto-cleanup)
            enable_export_endpoint: Enable Power BI export endpoint
            export_endpoint: URL for export endpoint
        """
        self.app: Optional[Flask] = None
        self.db: Optional[SQLAlchemy] = db  # Store db if passed for app factory pattern
        self.models: Dict[str, Any] = {}
        self._middleware: Optional[MetricsMiddleware] = None
        self._exporter: Optional[PowerBIExporter] = None
        self._static_bp: Optional[Blueprint] = None

        # Create configuration
        self.config = PortalMetricsConfig(
            schema=schema,
            track_forms=track_forms,
            track_performance=track_performance,
            sample_rate=sample_rate,
            exclude_endpoints=exclude_endpoints,
            exclude_paths=exclude_paths,
            hash_ip=hash_ip,
            sensitive_fields=sensitive_fields,
            retention_days=retention_days,
            enable_export_endpoint=enable_export_endpoint,
            export_endpoint=export_endpoint,
        )

        if app is not None:
            self.init_app(app, db)

    def init_app(self, app: Flask, db: Optional[SQLAlchemy] = None) -> None:
        """Initialize PortalMetrics with Flask application.

        This method can be used for deferred initialization when
        using application factories.

        Args:
            app: Flask application instance
            db: SQLAlchemy database instance (optional if passed to __init__)
        """
        self.app = app

        # Use provided db, or fall back to db passed during __init__
        if db is not None:
            self.db = db

        if self.db is None:
            raise RuntimeError(
                "PortalMetrics requires a SQLAlchemy db instance. "
                "Pass it to __init__(db=db) or init_app(app, db)."
            )

        # Validate configuration
        self._validate_config(app)

        # Create models
        self.models = create_models(db, self.config.schema)

        # Initialize middleware
        self._middleware = MetricsMiddleware(
            portal_metrics=self,
            exclude_endpoints=self.config.exclude_endpoints,
            exclude_paths=self.config.exclude_paths,
            sample_rate=self.config.sample_rate,
            hash_ip=self.config.hash_ip,
        )
        self._middleware.init_app(app)

        # Initialize exporter
        self._exporter = PowerBIExporter(self)

        # Register blueprints
        if self.config.enable_export_endpoint:
            export_bp = create_export_blueprint(self)
            app.register_blueprint(export_bp)

        # Register static files blueprint
        self._register_static_blueprint(app)

        # Store instance on app
        if not hasattr(app, "extensions"):
            app.extensions = {}
        app.extensions["portal_metrics"] = self

        logger.info(
            f"PortalMetrics initialized with sample_rate={self.config.sample_rate}, "
            f"schema={self.config.schema}"
        )

    def _validate_config(self, app: Flask) -> None:
        """Validate configuration and log warnings.

        Args:
            app: Flask application instance
        """
        if not app.config.get("SECRET_KEY"):
            logger.warning(
                "No SECRET_KEY set in Flask config. " "IP hashing will use default salt."
            )

        if self.config.sample_rate < 1.0:
            logger.info(f"Sampling enabled: tracking {self.config.sample_rate * 100}% of requests")

        if self.config.retention_days > 0:
            logger.info(f"Data retention: {self.config.retention_days} days")

    def _register_static_blueprint(self, app: Flask) -> None:
        """Register blueprint for serving static JavaScript files.

        Args:
            app: Flask application instance
        """
        import os

        static_folder = os.path.join(os.path.dirname(__file__), "static")

        self._static_bp = Blueprint(
            "portal_metrics",
            __name__,
            static_folder=static_folder,
            static_url_path="/portal-metrics/static",
        )
        app.register_blueprint(self._static_bp)

    def _record_user_activity(self, data: Dict[str, Any]) -> None:
        """Record user activity to database.

        Args:
            data: Activity data dictionary
        """
        try:
            UserActivity = self.models.get("UserActivity")
            if not UserActivity:
                return

            if self.config.async_enabled and self.config._celery:
                # Queue for async processing
                self._async_record_activity.delay(data)
            else:
                # Synchronous write
                activity = UserActivity(**data)
                self.db.session.add(activity)
                self.db.session.commit()

        except Exception as e:
            logger.error(f"Error recording user activity: {e}", exc_info=True)
            try:
                self.db.session.rollback()
            except Exception:
                pass

    def _record_page_metrics(self, data: Dict[str, Any]) -> None:
        """Record page metrics to database.

        Args:
            data: Page metrics data dictionary
        """
        try:
            PageMetrics = self.models.get("PageMetrics")
            if not PageMetrics:
                return

            # Sanitize and validate data
            clean_data = {
                "user_id": data.get("user_id"),
                "session_id": data.get("session_id"),
                "page_url": data.get("page_url", "")[:2048],
                "page_title": data.get("page_title", "")[:512] if data.get("page_title") else None,
                "time_on_page_ms": data.get("time_on_page_ms"),
                "scroll_depth_percent": data.get("scroll_depth_percent"),
                "viewport_width": data.get("viewport_width"),
                "viewport_height": data.get("viewport_height"),
                "screen_width": data.get("screen_width"),
                "screen_height": data.get("screen_height"),
                "timestamp": datetime.utcnow(),
            }

            metrics = PageMetrics(**clean_data)
            self.db.session.add(metrics)
            self.db.session.commit()

        except Exception as e:
            logger.error(f"Error recording page metrics: {e}", exc_info=True)
            try:
                self.db.session.rollback()
            except Exception:
                pass

    def _record_form_metrics(self, data: Dict[str, Any]) -> None:
        """Record form metrics to database.

        Args:
            data: Form metrics data dictionary
        """
        try:
            FormMetrics = self.models.get("FormMetrics")
            if not FormMetrics or not self.config.track_forms:
                return

            # Skip sensitive fields
            field_name = data.get("field_name")
            if field_name and any(
                sensitive in field_name.lower() for sensitive in self.config.sensitive_fields
            ):
                return

            clean_data = {
                "user_id": data.get("user_id"),
                "session_id": data.get("session_id"),
                "form_name": data.get("form_name", "unknown")[:256],
                "field_name": field_name[:256] if field_name else None,
                "interaction_type": data.get("interaction_type", "unknown")[:64],
                "completion_status": data.get("completion_status"),
                "error_message": (
                    data.get("error_message", "")[:1024] if data.get("error_message") else None
                ),
                "page_url": data.get("page_url", "")[:2048] if data.get("page_url") else None,
                "time_to_complete_ms": data.get("time_to_complete_ms"),
                "timestamp": datetime.utcnow(),
            }

            metrics = FormMetrics(**clean_data)
            self.db.session.add(metrics)
            self.db.session.commit()

        except Exception as e:
            logger.error(f"Error recording form metrics: {e}", exc_info=True)
            try:
                self.db.session.rollback()
            except Exception:
                pass

    def track_event(
        self,
        name: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track a custom application event.

        Args:
            name: Event name
            user_id: Optional user identifier
            session_id: Optional session identifier
            metadata: Optional metadata dictionary

        Example:
            metrics.track_event(
                'document_upload',
                user_id=current_user.id,
                metadata={'file_type': 'pdf', 'file_size': 1024}
            )
        """
        try:
            CustomEvent = self.models.get("CustomEvent")
            if not CustomEvent:
                return

            # Get user/session from context if not provided
            if user_id is None:
                user_id = self._middleware._get_user_id() if self._middleware else None
            if session_id is None:
                session_id = self._middleware._get_session_id() if self._middleware else None

            from flask import request

            page_url = None
            try:
                page_url = request.url
            except RuntimeError:
                pass

            event = CustomEvent(
                event_name=name[:256],
                user_id=str(user_id)[:256] if user_id else None,
                session_id=str(session_id)[:256] if session_id else None,
                metadata_json=json.dumps(metadata) if metadata else None,
                page_url=page_url[:2048] if page_url else None,
                timestamp=datetime.utcnow(),
            )

            self.db.session.add(event)
            self.db.session.commit()

        except Exception as e:
            logger.error(f"Error tracking custom event: {e}", exc_info=True)
            try:
                self.db.session.rollback()
            except Exception:
                pass

    def export_for_powerbi(
        self,
        date_range: Optional[Tuple[str, str]] = None,
        tables: Optional[List[str]] = None,
        aggregation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Export data for Power BI consumption.

        Args:
            date_range: Tuple of (start_date, end_date) in YYYY-MM-DD format
            tables: List of tables to export
            aggregation: Aggregation level (daily, weekly, monthly, None)

        Returns:
            Dict containing exported data

        Example:
            data = metrics.export_for_powerbi(
                date_range=('2026-01-01', '2026-03-10'),
                tables=['user_activity', 'page_metrics'],
                aggregation='daily'
            )
        """
        if not self._exporter:
            raise RuntimeError("PortalMetrics not initialized. Call init_app first.")

        return self._exporter.export_all(date_range, tables, aggregation)

    def get_daily_summary(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """Get daily summary statistics.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of daily summary records

        Example:
            summary = metrics.get_daily_summary('2026-01-01', '2026-03-10')
        """
        if not self._exporter:
            raise RuntimeError("PortalMetrics not initialized. Call init_app first.")

        return self._exporter.get_daily_summary(start_date, end_date)

    def cleanup_old_data(self, days: Optional[int] = None) -> Dict[str, int]:
        """Remove data older than specified days.

        Args:
            days: Number of days to retain (uses config.retention_days if not specified)

        Returns:
            Dict with count of deleted records per table
        """
        days = days or self.config.retention_days
        if days <= 0:
            return {}

        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = {}

        try:
            for name, model in self.models.items():
                count = model.query.filter(model.timestamp < cutoff).delete()
                deleted[name] = count

            self.db.session.commit()
            logger.info(f"Cleaned up data older than {days} days: {deleted}")

        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}", exc_info=True)
            self.db.session.rollback()

        return deleted

    def delete_user_data(self, user_id: str) -> Dict[str, int]:
        """Delete all data for a specific user (GDPR compliance).

        Args:
            user_id: User identifier to delete

        Returns:
            Dict with count of deleted records per table
        """
        deleted = {}

        try:
            for name, model in self.models.items():
                count = model.query.filter(model.user_id == str(user_id)).delete()
                deleted[name] = count

            self.db.session.commit()
            logger.info(f"Deleted data for user {user_id}: {deleted}")

        except Exception as e:
            logger.error(f"Error deleting user data: {e}", exc_info=True)
            self.db.session.rollback()

        return deleted

    def export_user_data(self, user_id: str) -> Dict[str, List[Dict]]:
        """Export all data for a specific user (GDPR data portability).

        Args:
            user_id: User identifier to export

        Returns:
            Dict with all records per table for the user
        """
        exported = {}

        try:
            for name, model in self.models.items():
                records = model.query.filter(model.user_id == str(user_id)).all()
                exported[name] = [record.to_dict() for record in records]

        except Exception as e:
            logger.error(f"Error exporting user data: {e}", exc_info=True)

        return exported

    def enable_async(self, celery) -> None:
        """Enable async database writes using Celery.

        Args:
            celery: Celery application instance

        Example:
            from celery import Celery
            celery = Celery('tasks', broker='redis://localhost:6379/0')
            metrics.enable_async(celery)
        """
        self.config.async_enabled = True
        self.config._celery = celery

        # Register Celery task
        @celery.task(name="portal_metrics.record_activity")
        def _async_record_activity(data):
            """Celery task for async activity recording."""
            try:
                UserActivity = self.models.get("UserActivity")
                if UserActivity:
                    activity = UserActivity(**data)
                    self.db.session.add(activity)
                    self.db.session.commit()
            except Exception as e:
                logger.error(f"Async record error: {e}")

        self._async_record_activity = _async_record_activity
        logger.info("Async processing enabled with Celery")

    @property
    def stats(self) -> Dict[str, Any]:
        """Get current statistics.

        Returns:
            Dict with current session statistics
        """
        try:
            UserActivity = self.models.get("UserActivity")
            PageMetrics = self.models.get("PageMetrics")
            FormMetrics = self.models.get("FormMetrics")
            CustomEvent = self.models.get("CustomEvent")

            today = datetime.utcnow().date()

            return {
                "total_activities": UserActivity.query.count() if UserActivity else 0,
                "total_page_views": PageMetrics.query.count() if PageMetrics else 0,
                "total_form_interactions": FormMetrics.query.count() if FormMetrics else 0,
                "total_custom_events": CustomEvent.query.count() if CustomEvent else 0,
                "today_activities": (
                    UserActivity.query.filter(
                        self.db.func.date(UserActivity.timestamp) == today
                    ).count()
                    if UserActivity
                    else 0
                ),
                "config": self.config.to_dict(),
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}
