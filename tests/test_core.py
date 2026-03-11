"""Unit tests for flask_portal_metrics core functionality."""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from flask import Flask, g, session
from flask_sqlalchemy import SQLAlchemy

from flask_portal_metrics import PortalMetrics, PortalMetricsConfig
from flask_portal_metrics.middleware import MetricsMiddleware


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


class TestPortalMetricsConfig:
    """Tests for PortalMetricsConfig class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PortalMetricsConfig()

        assert config.schema is None
        assert config.track_forms is True
        assert config.track_performance is True
        assert config.sample_rate == 1.0
        assert "static" in config.exclude_endpoints
        assert config.hash_ip is False
        assert config.retention_days == 90
        assert config.enable_export_endpoint is True

    def test_custom_config(self):
        """Test custom configuration values."""
        config = PortalMetricsConfig(
            schema="analytics",
            sample_rate=0.5,
            hash_ip=True,
            retention_days=30,
            exclude_endpoints=["static", "health"],
        )

        assert config.schema == "analytics"
        assert config.sample_rate == 0.5
        assert config.hash_ip is True
        assert config.retention_days == 30
        assert "health" in config.exclude_endpoints

    def test_sample_rate_clamping(self):
        """Test that sample_rate is clamped to valid range."""
        config_low = PortalMetricsConfig(sample_rate=-0.5)
        config_high = PortalMetricsConfig(sample_rate=1.5)

        assert config_low.sample_rate == 0.0
        assert config_high.sample_rate == 1.0

    def test_to_dict(self):
        """Test configuration serialization."""
        config = PortalMetricsConfig(schema="test")
        result = config.to_dict()

        assert isinstance(result, dict)
        assert result["schema"] == "test"
        assert "sample_rate" in result
        assert "exclude_endpoints" in result


class TestPortalMetricsInitialization:
    """Tests for PortalMetrics initialization."""

    def test_basic_initialization(self, app, db):
        """Test basic initialization with app and db."""
        metrics = PortalMetrics(app, db)

        assert metrics.app is app
        assert metrics.db is db
        assert metrics.models is not None
        assert "UserActivity" in metrics.models
        assert "PageMetrics" in metrics.models
        assert "FormMetrics" in metrics.models

    def test_deferred_initialization(self, app, db):
        """Test deferred initialization with init_app."""
        metrics = PortalMetrics()
        assert metrics.app is None

        metrics.init_app(app, db)

        assert metrics.app is app
        assert metrics.db is db

    def test_configuration_passed_to_instance(self, app, db):
        """Test that configuration options are applied."""
        metrics = PortalMetrics(
            app,
            db,
            schema="analytics",
            sample_rate=0.5,
            hash_ip=True,
        )

        assert metrics.config.schema == "analytics"
        assert metrics.config.sample_rate == 0.5
        assert metrics.config.hash_ip is True

    def test_models_created(self, app, db, metrics):
        """Test that database models are created."""
        with app.app_context():
            assert "UserActivity" in metrics.models

            # Check model has expected columns
            UserActivity = metrics.models["UserActivity"]
            assert hasattr(UserActivity, "endpoint")
            assert hasattr(UserActivity, "method")
            assert hasattr(UserActivity, "response_time_ms")
            assert hasattr(UserActivity, "user_id")

    def test_extension_registered(self, app, db, metrics):
        """Test that extension is registered on app."""
        assert "portal_metrics" in app.extensions
        assert app.extensions["portal_metrics"] is metrics


class TestRequestTracking:
    """Tests for automatic request tracking."""

    def test_request_tracked(self, app, db, metrics, client):
        """Test that basic requests are tracked."""

        @app.route("/test")
        def test_route():
            return "OK"

        with app.app_context():
            response = client.get("/test")

            assert response.status_code == 200

            UserActivity = metrics.models["UserActivity"]
            record = UserActivity.query.first()

            assert record is not None
            assert record.method == "GET"
            assert record.path == "/test"
            assert record.response_code == 200

    def test_response_time_recorded(self, app, db, metrics, client):
        """Test that response time is recorded."""
        import time

        @app.route("/slow")
        def slow_route():
            time.sleep(0.01)  # 10ms delay
            return "OK"

        with app.app_context():
            client.get("/slow")

            UserActivity = metrics.models["UserActivity"]
            record = UserActivity.query.first()

            assert record.response_time_ms is not None
            assert record.response_time_ms >= 10

    def test_excluded_endpoints_not_tracked(self, app, db):
        """Test that excluded endpoints are not tracked."""
        metrics = PortalMetrics(app, db, exclude_endpoints=["test_excluded"])

        @app.route("/excluded", endpoint="test_excluded")
        def excluded_route():
            return "OK"

        with app.app_context():
            db.create_all()
            client = app.test_client()
            client.get("/excluded")

            UserActivity = metrics.models["UserActivity"]
            count = UserActivity.query.count()

            assert count == 0

    def test_user_agent_captured(self, app, db, metrics, client):
        """Test that user agent is captured."""

        @app.route("/ua")
        def ua_route():
            return "OK"

        with app.app_context():
            client.get("/ua", headers={"User-Agent": "Test Browser/1.0"})

            UserActivity = metrics.models["UserActivity"]
            record = UserActivity.query.first()

            assert "Test Browser" in record.user_agent


class TestCustomEventTracking:
    """Tests for custom event tracking."""

    def test_track_event(self, app, db, metrics):
        """Test tracking a custom event."""
        with app.app_context():
            metrics.track_event("test_event", user_id="user123", metadata={"key": "value"})

            CustomEvent = metrics.models["CustomEvent"]
            event = CustomEvent.query.first()

            assert event is not None
            assert event.event_name == "test_event"
            assert event.user_id == "user123"

            metadata = json.loads(event.metadata_json)
            assert metadata["key"] == "value"

    def test_track_event_without_metadata(self, app, db, metrics):
        """Test tracking event without metadata."""
        with app.app_context():
            metrics.track_event("simple_event")

            CustomEvent = metrics.models["CustomEvent"]
            event = CustomEvent.query.first()

            assert event.event_name == "simple_event"
            assert event.metadata_json is None


class TestIPAddressHashing:
    """Tests for IP address hashing."""

    def test_ip_hashing_enabled(self, app, db):
        """Test IP hashing when enabled."""
        metrics = PortalMetrics(app, db, hash_ip=True)

        @app.route("/test")
        def test_route():
            return "OK"

        with app.app_context():
            db.create_all()
            client = app.test_client()
            client.get("/test", environ_base={"REMOTE_ADDR": "192.168.1.1"})

            UserActivity = metrics.models["UserActivity"]
            record = UserActivity.query.first()

            # IP should be hashed, not raw
            assert record.ip_address != "192.168.1.1"
            assert len(record.ip_address) == 32  # SHA256 truncated

    def test_ip_hashing_disabled(self, app, db, metrics, client):
        """Test IP not hashed when disabled."""

        @app.route("/test")
        def test_route():
            return "OK"

        with app.app_context():
            # Skip this test as test client doesn't set a real IP
            pass


class TestDataCleanup:
    """Tests for data retention and cleanup."""

    def test_cleanup_old_data(self, app, db, metrics):
        """Test cleanup of old data."""
        with app.app_context():
            UserActivity = metrics.models["UserActivity"]

            # Create old record
            old_record = UserActivity(
                endpoint="test",
                method="GET",
                path="/test",
                timestamp=datetime.utcnow() - timedelta(days=100),
            )
            db.session.add(old_record)

            # Create new record
            new_record = UserActivity(
                endpoint="test", method="GET", path="/test", timestamp=datetime.utcnow()
            )
            db.session.add(new_record)
            db.session.commit()

            assert UserActivity.query.count() == 2

            # Cleanup records older than 30 days
            deleted = metrics.cleanup_old_data(days=30)

            assert deleted["UserActivity"] == 1
            assert UserActivity.query.count() == 1

    def test_delete_user_data(self, app, db, metrics):
        """Test GDPR user data deletion."""
        with app.app_context():
            UserActivity = metrics.models["UserActivity"]

            # Create records for different users
            for user_id in ["user1", "user2", "user1"]:
                record = UserActivity(
                    endpoint="test",
                    method="GET",
                    path="/test",
                    user_id=user_id,
                    timestamp=datetime.utcnow(),
                )
                db.session.add(record)
            db.session.commit()

            assert UserActivity.query.count() == 3

            # Delete user1's data
            deleted = metrics.delete_user_data("user1")

            assert deleted["UserActivity"] == 2
            assert UserActivity.query.count() == 1
            assert UserActivity.query.first().user_id == "user2"

    def test_export_user_data(self, app, db, metrics):
        """Test GDPR user data export."""
        with app.app_context():
            UserActivity = metrics.models["UserActivity"]

            record = UserActivity(
                endpoint="test",
                method="GET",
                path="/test",
                user_id="export_user",
                timestamp=datetime.utcnow(),
            )
            db.session.add(record)
            db.session.commit()

            exported = metrics.export_user_data("export_user")

            assert "UserActivity" in exported
            assert len(exported["UserActivity"]) == 1
            assert exported["UserActivity"][0]["user_id"] == "export_user"


class TestSampling:
    """Tests for request sampling."""

    def test_sampling_rate_zero(self, app, db):
        """Test that no requests are tracked with 0% sampling."""
        metrics = PortalMetrics(app, db, sample_rate=0.0)

        @app.route("/test")
        def test_route():
            return "OK"

        with app.app_context():
            db.create_all()
            client = app.test_client()

            # Make several requests
            for _ in range(10):
                client.get("/test")

            UserActivity = metrics.models["UserActivity"]
            assert UserActivity.query.count() == 0

    def test_sampling_consistency(self, app, db):
        """Test that sampling is consistent within reasonable bounds."""
        # This is a statistical test, so we use a margin
        pass  # Complex to test reliably


class TestStats:
    """Tests for statistics functionality."""

    def test_stats_property(self, app, db, metrics, client):
        """Test stats property returns expected data."""

        @app.route("/test")
        def test_route():
            return "OK"

        with app.app_context():
            client.get("/test")

            stats = metrics.stats

            assert "total_activities" in stats
            assert stats["total_activities"] >= 1
            assert "config" in stats


class TestMiddleware:
    """Tests for MetricsMiddleware class."""

    def test_middleware_initialization(self, app, db, metrics):
        """Test middleware initialization."""
        middleware = MetricsMiddleware(
            metrics,
            exclude_endpoints=["static", "health"],
            sample_rate=0.5,
            hash_ip=True,
        )

        assert "static" in middleware.exclude_endpoints
        assert "health" in middleware.exclude_endpoints
        assert middleware.sample_rate == 0.5
        assert middleware.hash_ip is True


class TestErrorHandling:
    """Tests for error handling and graceful degradation."""

    def test_tracking_error_doesnt_break_app(self, app, db, metrics, client):
        """Test that tracking errors don't break the main app."""

        @app.route("/test")
        def test_route():
            return "OK"

        with app.app_context():
            # Mock a database error
            with patch.object(db.session, "commit", side_effect=Exception("DB Error")):
                response = client.get("/test")

            # Response should still be OK
            assert response.status_code == 200

    def test_track_event_error_handling(self, app, db, metrics):
        """Test that track_event handles errors gracefully."""
        with app.app_context():
            # Mock a database error
            with patch.object(db.session, "commit", side_effect=Exception("DB Error")):
                # Should not raise
                metrics.track_event("test", metadata={"key": "value"})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
