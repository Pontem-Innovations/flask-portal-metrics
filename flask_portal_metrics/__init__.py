"""Flask-Portal-Metrics: Drop-in user activity tracking for Flask applications.

This package provides comprehensive analytics for Flask applications with
Power BI integration, including automatic request tracking, client-side
metrics collection, and data export functionality.

Basic Usage:
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    from flask_portal_metrics import PortalMetrics

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    db = SQLAlchemy(app)

    # Enable full tracking with one line
    metrics = PortalMetrics(app, db)

Advanced Usage:
    metrics = PortalMetrics(
        app, db,
        schema='analytics',
        sample_rate=0.1,
        hash_ip=True,
        retention_days=90
    )

    # Track custom events
    metrics.track_event('document_upload', user_id=123, metadata={'type': 'pdf'})

    # Export for Power BI
    data = metrics.export_for_powerbi(date_range=('2026-01-01', '2026-03-10'))
"""

__version__ = "1.0.0"
__author__ = "Pontem Innovations"
__email__ = "dev@ponteminnovations.com"
__license__ = "MIT"

from .core import PortalMetrics, PortalMetricsConfig
from .middleware import MetricsMiddleware, track_endpoint
from .exports import PowerBIExporter, POWERBI_SQL_QUERIES

__all__ = [
    "PortalMetrics",
    "PortalMetricsConfig",
    "MetricsMiddleware",
    "track_endpoint",
    "PowerBIExporter",
    "POWERBI_SQL_QUERIES",
]
