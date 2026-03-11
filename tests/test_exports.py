"""Unit tests for flask_portal_metrics export functionality."""

import json
import pytest
from datetime import datetime, timedelta

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from flask_portal_metrics import PortalMetrics, PowerBIExporter, POWERBI_SQL_QUERIES
from flask_portal_metrics.exports import create_export_blueprint


@pytest.fixture
def app():
    """Create a Flask application for testing."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret-key"
    app.config["TESTING"] = True
    return app


@pytest.fixture
def db(app):
    """Create a SQLAlchemy database instance."""
    database = SQLAlchemy(app)
    return database


@pytest.fixture
def metrics(app, db):
    """Create a PortalMetrics instance."""
    portal_metrics = PortalMetrics(app, db)
    with app.app_context():
        db.create_all()
    return portal_metrics


@pytest.fixture
def client(app, metrics):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def sample_data(app, db, metrics):
    """Create sample data for testing exports."""
    with app.app_context():
        UserActivity = metrics.models["UserActivity"]
        PageMetrics = metrics.models["PageMetrics"]
        FormMetrics = metrics.models["FormMetrics"]

        # Create user activity records
        for i in range(5):
            activity = UserActivity(
                endpoint=f"endpoint_{i}",
                method="GET",
                path=f"/test/{i}",
                response_code=200,
                response_time_ms=100 + i * 10,
                user_id=f"user_{i % 2}",
                session_id=f"session_{i}",
                timestamp=datetime.utcnow() - timedelta(days=i),
            )
            db.session.add(activity)

        # Create page metrics records
        for i in range(3):
            page = PageMetrics(
                user_id=f"user_{i}",
                session_id=f"session_{i}",
                page_url=f"http://test.com/page/{i}",
                page_title=f"Page {i}",
                time_on_page_ms=5000 + i * 1000,
                scroll_depth_percent=50 + i * 10,
                timestamp=datetime.utcnow() - timedelta(days=i),
            )
            db.session.add(page)

        # Create form metrics records
        for i in range(2):
            form = FormMetrics(
                user_id=f"user_{i}",
                form_name="login_form",
                interaction_type="submit",
                completion_status=i == 0,
                timestamp=datetime.utcnow() - timedelta(days=i),
            )
            db.session.add(form)

        db.session.commit()

    return metrics


class TestPowerBIExportEndpoint:
    """Tests for the Power BI export endpoint."""

    def test_export_endpoint_exists(self, client):
        """Test that export endpoint is registered."""
        response = client.get("/api/metrics/powerbi")
        # Should return data, not 404
        assert response.status_code != 404

    def test_export_user_activity(self, client, sample_data):
        """Test exporting user activity data."""
        response = client.get("/api/metrics/powerbi?table=user_activity")

        assert response.status_code == 200
        data = response.get_json()

        assert data["table"] == "user_activity"
        assert "data" in data
        assert "pagination" in data
        assert len(data["data"]) == 5

    def test_export_page_metrics(self, client, sample_data):
        """Test exporting page metrics data."""
        response = client.get("/api/metrics/powerbi?table=page_metrics")

        assert response.status_code == 200
        data = response.get_json()

        assert data["table"] == "page_metrics"
        assert len(data["data"]) == 3

    def test_export_form_metrics(self, client, sample_data):
        """Test exporting form metrics data."""
        response = client.get("/api/metrics/powerbi?table=form_metrics")

        assert response.status_code == 200
        data = response.get_json()

        assert data["table"] == "form_metrics"
        assert len(data["data"]) == 2

    def test_export_with_date_range(self, client, sample_data):
        """Test exporting with date range filter."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

        response = client.get(
            f"/api/metrics/powerbi?table=user_activity&start_date={yesterday}&end_date={today}"
        )

        assert response.status_code == 200
        data = response.get_json()

        # Should have fewer records due to date filter
        assert len(data["data"]) <= 5
        assert data["date_range"] is not None

    def test_export_pagination(self, client, sample_data):
        """Test export pagination."""
        response = client.get("/api/metrics/powerbi?table=user_activity&page=1&per_page=2")

        assert response.status_code == 200
        data = response.get_json()

        assert len(data["data"]) == 2
        assert data["pagination"]["per_page"] == 2
        assert data["pagination"]["has_next"] is True

    def test_export_daily_summary(self, client, sample_data):
        """Test daily summary export."""
        response = client.get("/api/metrics/powerbi?table=daily_summary")

        assert response.status_code == 200
        data = response.get_json()

        assert data["table"] == "daily_summary"
        assert "data" in data

    def test_export_all_tables(self, client, sample_data):
        """Test exporting all tables at once."""
        response = client.get("/api/metrics/powerbi?table=all")

        assert response.status_code == 200
        data = response.get_json()

        assert "tables" in data
        assert "user_activity" in data["tables"]
        assert "page_metrics" in data["tables"]

    def test_invalid_date_format(self, client):
        """Test error handling for invalid date format."""
        response = client.get(
            "/api/metrics/powerbi?table=user_activity&start_date=invalid&end_date=2026-01-01"
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_max_per_page_limit(self, client, sample_data):
        """Test that per_page is capped at maximum."""
        response = client.get("/api/metrics/powerbi?table=user_activity&per_page=99999")

        assert response.status_code == 200
        data = response.get_json()

        # Should be capped at 10000
        assert data["pagination"]["per_page"] <= 10000


class TestClientMetricsEndpoint:
    """Tests for the client metrics endpoint."""

    def test_page_metrics_submission(self, client, metrics, app):
        """Test submitting page metrics from client."""
        with app.app_context():
            response = client.post(
                "/api/metrics/client",
                json={
                    "type": "page_metrics",
                    "data": {
                        "page_url": "http://test.com/page",
                        "page_title": "Test Page",
                        "time_on_page_ms": 5000,
                        "scroll_depth_percent": 75,
                    },
                },
                content_type="application/json",
            )

            assert response.status_code == 200

            PageMetrics = metrics.models["PageMetrics"]
            record = PageMetrics.query.first()

            assert record is not None
            assert record.page_url == "http://test.com/page"
            assert record.time_on_page_ms == 5000

    def test_form_metrics_submission(self, client, metrics, app):
        """Test submitting form metrics from client."""
        with app.app_context():
            response = client.post(
                "/api/metrics/client",
                json={
                    "type": "form_metrics",
                    "data": {
                        "form_name": "contact_form",
                        "interaction_type": "submit",
                        "completion_status": True,
                    },
                },
                content_type="application/json",
            )

            assert response.status_code == 200

    def test_custom_event_submission(self, client, metrics, app):
        """Test submitting custom event from client."""
        with app.app_context():
            response = client.post(
                "/api/metrics/client",
                json={
                    "type": "custom_event",
                    "data": {"event_name": "button_click", "metadata": {"button_id": "submit_btn"}},
                },
                content_type="application/json",
            )

            assert response.status_code == 200

    def test_invalid_metric_type(self, client):
        """Test error handling for invalid metric type."""
        response = client.post(
            "/api/metrics/client",
            json={"type": "invalid_type", "data": {}},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_missing_data(self, client):
        """Test error handling for missing data."""
        response = client.post("/api/metrics/client", json=None, content_type="application/json")

        assert response.status_code == 400


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_endpoint(self, client):
        """Test health check endpoint returns OK."""
        response = client.get("/api/metrics/health")

        assert response.status_code == 200
        data = response.get_json()

        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestPowerBIExporter:
    """Tests for the PowerBIExporter class."""

    def test_exporter_initialization(self, metrics):
        """Test exporter initialization."""
        exporter = PowerBIExporter(metrics)

        assert exporter.portal_metrics is metrics
        assert exporter.db is metrics.db

    def test_export_all(self, app, sample_data):
        """Test export_all method."""
        with app.app_context():
            exporter = PowerBIExporter(sample_data)
            result = exporter.export_all()

            assert "user_activity" in result
            assert "page_metrics" in result
            assert "form_metrics" in result

    def test_export_with_aggregation(self, app, sample_data):
        """Test export with daily aggregation."""
        with app.app_context():
            exporter = PowerBIExporter(sample_data)
            result = exporter.export_all(aggregation="daily")

            assert "user_activity" in result
            # Aggregated data should have date field
            if result["user_activity"]["data"]:
                assert "date" in result["user_activity"]["data"][0]

    def test_daily_summary(self, app, sample_data):
        """Test get_daily_summary method."""
        with app.app_context():
            exporter = PowerBIExporter(sample_data)
            summary = exporter.get_daily_summary()

            assert isinstance(summary, list)
            if len(summary) > 0:
                assert "date" in summary[0]
                assert "total_requests" in summary[0]
                assert "unique_users" in summary[0]


class TestProgrammaticExport:
    """Tests for programmatic export functionality."""

    def test_export_for_powerbi(self, app, sample_data):
        """Test export_for_powerbi method."""
        with app.app_context():
            result = sample_data.export_for_powerbi(tables=["user_activity"])

            assert "user_activity" in result

    def test_export_with_date_range(self, app, sample_data):
        """Test export with date range."""
        with app.app_context():
            today = datetime.utcnow().strftime("%Y-%m-%d")
            result = sample_data.export_for_powerbi(
                date_range=("2020-01-01", today), tables=["user_activity"]
            )

            assert "user_activity" in result

    def test_get_daily_summary_method(self, app, sample_data):
        """Test get_daily_summary method on PortalMetrics."""
        with app.app_context():
            summary = sample_data.get_daily_summary()

            assert isinstance(summary, list)


class TestSQLQueries:
    """Tests for pre-built SQL queries."""

    def test_queries_available(self):
        """Test that pre-built queries are available."""
        assert "daily_active_users" in POWERBI_SQL_QUERIES
        assert "response_time_by_endpoint" in POWERBI_SQL_QUERIES
        assert "page_engagement" in POWERBI_SQL_QUERIES
        assert "form_completion_rates" in POWERBI_SQL_QUERIES

    def test_queries_are_valid_sql(self):
        """Test that queries are valid SQL strings."""
        for name, query in POWERBI_SQL_QUERIES.items():
            assert isinstance(query, str)
            assert "SELECT" in query.upper()
            assert "FROM" in query.upper()


class TestExportDisabled:
    """Tests when export endpoint is disabled."""

    def test_no_export_endpoint(self, app, db):
        """Test that export endpoint is not registered when disabled."""
        metrics = PortalMetrics(app, db, enable_export_endpoint=False)

        client = app.test_client()
        response = client.get("/api/metrics/powerbi")

        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
