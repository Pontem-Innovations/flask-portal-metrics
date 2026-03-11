"""Setup configuration for flask-portal-metrics package."""

from setuptools import setup, find_packages
import os

# Read the README file for long description
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="flask-portal-metrics",
    version="1.0.1",
    description="Drop-in user activity tracking for Flask applications with Power BI integration",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Pontem Innovations",
    author_email="dev@ponteminnovations.com",
    url="https://github.com/pontem-innovations/flask-portal-metrics",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    python_requires=">=3.7",
    install_requires=[
        "Flask>=2.0.0",
        "Flask-SQLAlchemy>=3.0.0",
        "SQLAlchemy>=1.4.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-flask>=1.2.0",
            "coverage>=6.0",
        ],
        "async": [
            "celery>=5.0.0",
        ],
    },
    keywords=[
        "flask",
        "analytics",
        "metrics",
        "powerbi",
        "tracking",
        "user-activity",
        "middleware",
        "sqlalchemy",
    ],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Framework :: Flask",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Monitoring",
    ],
    project_urls={
        "Bug Reports": "https://github.com/pontem-innovations/flask-portal-metrics/issues",
        "Source": "https://github.com/pontem-innovations/flask-portal-metrics",
        "Documentation": "https://github.com/pontem-innovations/flask-portal-metrics#readme",
    },
    package_data={
        "flask_portal_metrics": ["static/*.js"],
    },
)
