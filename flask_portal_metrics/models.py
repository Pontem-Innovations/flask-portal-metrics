"""SQLAlchemy model definitions for flask-portal-metrics.

This module defines the database schema for storing user activity,
page metrics, form interactions, and custom events.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, Index
from sqlalchemy.ext.declarative import declared_attr

if TYPE_CHECKING:
    from flask_sqlalchemy import SQLAlchemy


class MetricsModelMixin:
    """Mixin providing common functionality for metrics models."""

    @declared_attr
    def __tablename__(cls) -> str:
        """Generate table name from class name."""
        # Convert CamelCase to snake_case
        name = cls.__name__
        result = [name[0].lower()]
        for char in name[1:]:
            if char.isupper():
                result.append("_")
                result.append(char.lower())
            else:
                result.append(char)
        return "".join(result)


def create_models(db: "SQLAlchemy", schema: Optional[str] = None):
    """Factory function to create SQLAlchemy models bound to the provided db instance.

    Args:
        db: Flask-SQLAlchemy database instance
        schema: Optional database schema name for table creation

    Returns:
        dict: Dictionary containing model classes
    """

    class UserActivity(db.Model, MetricsModelMixin):
        """Tracks server-side request/response data.

        Records HTTP requests including endpoint, method, response time,
        user identification, and client information.
        """

        __tablename__ = "portal_metrics_user_activity"
        __table_args__ = (
            Index("idx_pm_ua_timestamp", "timestamp"),
            Index("idx_pm_ua_user_id", "user_id"),
            Index("idx_pm_ua_endpoint", "endpoint"),
            Index("idx_pm_ua_session_id", "session_id"),
            {"schema": schema} if schema else {},
        )

        id = Column(Integer, primary_key=True, autoincrement=True)
        endpoint = Column(String(256), nullable=True, index=True)
        method = Column(String(10), nullable=False)
        path = Column(String(2048), nullable=False)
        response_code = Column(Integer, nullable=True)
        response_time_ms = Column(Float, nullable=True)
        user_id = Column(String(256), nullable=True, index=True)
        session_id = Column(String(256), nullable=True, index=True)
        ip_address = Column(String(128), nullable=True)
        user_agent = Column(String(512), nullable=True)
        referrer = Column(String(2048), nullable=True)
        query_string = Column(Text, nullable=True)
        request_size = Column(Integer, nullable=True)
        response_size = Column(Integer, nullable=True)
        timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

        def to_dict(self) -> dict:
            """Convert model to dictionary for JSON serialization."""
            return {
                "id": self.id,
                "endpoint": self.endpoint,
                "method": self.method,
                "path": self.path,
                "response_code": self.response_code,
                "response_time_ms": self.response_time_ms,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "ip_address": self.ip_address,
                "user_agent": self.user_agent,
                "referrer": self.referrer,
                "query_string": self.query_string,
                "request_size": self.request_size,
                "response_size": self.response_size,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            }

    class PageMetrics(db.Model, MetricsModelMixin):
        """Tracks client-side page engagement metrics.

        Records page views, time spent on page, scroll depth,
        and other client-side engagement data.
        """

        __tablename__ = "portal_metrics_page_metrics"
        __table_args__ = (
            Index("idx_pm_pm_timestamp", "timestamp"),
            Index("idx_pm_pm_user_id", "user_id"),
            Index("idx_pm_pm_page_url", "page_url"),
            {"schema": schema} if schema else {},
        )

        id = Column(Integer, primary_key=True, autoincrement=True)
        user_id = Column(String(256), nullable=True, index=True)
        session_id = Column(String(256), nullable=True, index=True)
        page_url = Column(String(2048), nullable=False)
        page_title = Column(String(512), nullable=True)
        time_on_page_ms = Column(Integer, nullable=True)
        scroll_depth_percent = Column(Integer, nullable=True)
        viewport_width = Column(Integer, nullable=True)
        viewport_height = Column(Integer, nullable=True)
        screen_width = Column(Integer, nullable=True)
        screen_height = Column(Integer, nullable=True)
        timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

        def to_dict(self) -> dict:
            """Convert model to dictionary for JSON serialization."""
            return {
                "id": self.id,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "page_url": self.page_url,
                "page_title": self.page_title,
                "time_on_page_ms": self.time_on_page_ms,
                "scroll_depth_percent": self.scroll_depth_percent,
                "viewport_width": self.viewport_width,
                "viewport_height": self.viewport_height,
                "screen_width": self.screen_width,
                "screen_height": self.screen_height,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            }

    class FormMetrics(db.Model, MetricsModelMixin):
        """Tracks form interaction data.

        Records form submissions, field interactions, validation errors,
        and completion status.
        """

        __tablename__ = "portal_metrics_form_metrics"
        __table_args__ = (
            Index("idx_pm_fm_timestamp", "timestamp"),
            Index("idx_pm_fm_user_id", "user_id"),
            Index("idx_pm_fm_form_name", "form_name"),
            {"schema": schema} if schema else {},
        )

        id = Column(Integer, primary_key=True, autoincrement=True)
        user_id = Column(String(256), nullable=True, index=True)
        session_id = Column(String(256), nullable=True, index=True)
        form_name = Column(String(256), nullable=False, index=True)
        field_name = Column(String(256), nullable=True)
        interaction_type = Column(String(64), nullable=False)  # focus, blur, submit, error, change
        completion_status = Column(Boolean, nullable=True)
        error_message = Column(String(1024), nullable=True)
        page_url = Column(String(2048), nullable=True)
        time_to_complete_ms = Column(Integer, nullable=True)
        timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

        def to_dict(self) -> dict:
            """Convert model to dictionary for JSON serialization."""
            return {
                "id": self.id,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "form_name": self.form_name,
                "field_name": self.field_name,
                "interaction_type": self.interaction_type,
                "completion_status": self.completion_status,
                "error_message": self.error_message,
                "page_url": self.page_url,
                "time_to_complete_ms": self.time_to_complete_ms,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            }

    class CustomEvent(db.Model, MetricsModelMixin):
        """Tracks custom application events.

        Allows applications to track arbitrary events with custom metadata.
        """

        __tablename__ = "portal_metrics_custom_events"
        __table_args__ = (
            Index("idx_pm_ce_timestamp", "timestamp"),
            Index("idx_pm_ce_user_id", "user_id"),
            Index("idx_pm_ce_event_name", "event_name"),
            {"schema": schema} if schema else {},
        )

        id = Column(Integer, primary_key=True, autoincrement=True)
        event_name = Column(String(256), nullable=False, index=True)
        user_id = Column(String(256), nullable=True, index=True)
        session_id = Column(String(256), nullable=True, index=True)
        metadata_json = Column(Text, nullable=True)  # JSON-encoded metadata
        page_url = Column(String(2048), nullable=True)
        timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

        def to_dict(self) -> dict:
            """Convert model to dictionary for JSON serialization."""
            import json

            metadata = None
            if self.metadata_json:
                try:
                    metadata = json.loads(self.metadata_json)
                except (json.JSONDecodeError, TypeError):
                    metadata = self.metadata_json

            return {
                "id": self.id,
                "event_name": self.event_name,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "metadata": metadata,
                "page_url": self.page_url,
                "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            }

    return {
        "UserActivity": UserActivity,
        "PageMetrics": PageMetrics,
        "FormMetrics": FormMetrics,
        "CustomEvent": CustomEvent,
    }
