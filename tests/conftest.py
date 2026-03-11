"""Pytest configuration and shared fixtures for flask-portal-metrics tests."""

import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy


@pytest.fixture(scope="session")
def app_factory():
    """Factory for creating Flask applications."""

    def _create_app(config=None):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test-secret-key-for-testing"
        app.config["TESTING"] = True

        if config:
            app.config.update(config)

        return app

    return _create_app


@pytest.fixture
def app(app_factory):
    """Create a Flask application for testing."""
    return app_factory()


@pytest.fixture
def db(app):
    """Create a SQLAlchemy database instance."""
    database = SQLAlchemy(app)

    with app.app_context():
        database.create_all()
        yield database
        database.drop_all()


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create a test CLI runner."""
    return app.test_cli_runner()
