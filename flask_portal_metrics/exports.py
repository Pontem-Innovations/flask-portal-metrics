"""Power BI data export functionality for flask-portal-metrics.

This module provides functions and Flask blueprint for exporting
analytics data in Power BI-friendly formats with pagination,
date filtering, and aggregation support.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from flask import Blueprint, jsonify, request as flask_request
from sqlalchemy import func, and_, cast, Date, case

if TYPE_CHECKING:
    from .core import PortalMetrics

logger = logging.getLogger(__name__)


def create_export_blueprint(portal_metrics: "PortalMetrics") -> Blueprint:
    """Create Flask blueprint for Power BI export endpoints.

    Args:
        portal_metrics: Parent PortalMetrics instance

    Returns:
        Blueprint: Flask blueprint with export endpoints
    """
    bp = Blueprint("portal_metrics_export", __name__, url_prefix="/api/metrics")

    @bp.route("/powerbi", methods=["GET"])
    def powerbi_export():
        """Export data for Power BI consumption.

        Query Parameters:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            table: Table to export (user_activity, page_metrics, form_metrics,
                   custom_events, daily_summary, all)
            page: Page number (default: 1)
            per_page: Records per page (default: 1000, max: 10000)
            aggregation: Aggregation level (daily, weekly, monthly, none)

        Returns:
            JSON response with data and pagination info
        """
        try:
            # Parse query parameters
            start_date = flask_request.args.get("start_date")
            end_date = flask_request.args.get("end_date")
            table = flask_request.args.get("table", "user_activity")
            page = max(1, int(flask_request.args.get("page", 1)))
            per_page = min(10000, max(1, int(flask_request.args.get("per_page", 1000))))
            aggregation = flask_request.args.get("aggregation")

            # Parse dates
            date_range = None
            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, "%Y-%m-%d")
                    end = datetime.strptime(end_date, "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59
                    )
                    date_range = (start, end)
                except ValueError as e:
                    return (
                        jsonify(
                            {"error": f"Invalid date format: {e}", "expected_format": "YYYY-MM-DD"}
                        ),
                        400,
                    )

            # Handle different table types
            if table == "daily_summary":
                data = portal_metrics.get_daily_summary(
                    start_date=start_date,
                    end_date=end_date,
                )
                return jsonify(
                    {
                        "table": "daily_summary",
                        "data": data,
                        "total": len(data),
                        "generated_at": datetime.utcnow().isoformat(),
                    }
                )

            elif table == "all":
                # Export all tables
                result = portal_metrics.export_for_powerbi(
                    date_range=(start_date, end_date) if start_date and end_date else None,
                    tables=["user_activity", "page_metrics", "form_metrics", "custom_events"],
                    aggregation=aggregation,
                )
                return jsonify(
                    {
                        "tables": result,
                        "generated_at": datetime.utcnow().isoformat(),
                    }
                )

            else:
                # Export single table with pagination
                data, total = _export_table(
                    portal_metrics,
                    table,
                    date_range,
                    page,
                    per_page,
                    aggregation,
                )

                return jsonify(
                    {
                        "table": table,
                        "data": data,
                        "pagination": {
                            "page": page,
                            "per_page": per_page,
                            "total": total,
                            "total_pages": (total + per_page - 1) // per_page,
                            "has_next": page * per_page < total,
                            "has_prev": page > 1,
                        },
                        "date_range": (
                            {
                                "start": start_date,
                                "end": end_date,
                            }
                            if date_range
                            else None
                        ),
                        "generated_at": datetime.utcnow().isoformat(),
                    }
                )

        except Exception as e:
            logger.error(f"Error in Power BI export: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    @bp.route("/client", methods=["POST"])
    def client_metrics():
        """Receive client-side metrics from JavaScript tracker.

        Expected payload:
            {
                "type": "page_metrics" | "form_metrics" | "custom_event",
                "data": { ... }
            }
        """
        try:
            payload = flask_request.get_json()
            if not payload:
                return jsonify({"error": "No data provided"}), 400

            metric_type = payload.get("type")
            data = payload.get("data", {})

            if metric_type == "page_metrics":
                portal_metrics._record_page_metrics(data)
            elif metric_type == "form_metrics":
                portal_metrics._record_form_metrics(data)
            elif metric_type == "custom_event":
                portal_metrics.track_event(
                    name=data.get("event_name", "unknown"),
                    user_id=data.get("user_id"),
                    session_id=data.get("session_id"),
                    metadata=data.get("metadata"),
                )
            else:
                return jsonify({"error": f"Unknown metric type: {metric_type}"}), 400

            return jsonify({"status": "ok"})

        except Exception as e:
            logger.error(f"Error recording client metrics: {e}", exc_info=True)
            return jsonify({"error": "Failed to record metrics"}), 500

    @bp.route("/health", methods=["GET"])
    def health_check():
        """Health check endpoint for monitoring."""
        return jsonify(
            {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    return bp


def _export_table(
    portal_metrics: "PortalMetrics",
    table_name: str,
    date_range: Optional[Tuple[datetime, datetime]],
    page: int,
    per_page: int,
    aggregation: Optional[str],
) -> Tuple[List[Dict], int]:
    """Export a single table with pagination.

    Args:
        portal_metrics: PortalMetrics instance
        table_name: Name of table to export
        date_range: Optional date range filter
        page: Page number
        per_page: Records per page
        aggregation: Aggregation level

    Returns:
        Tuple of (data list, total count)
    """
    model_map = {
        "user_activity": portal_metrics.models.get("UserActivity"),
        "page_metrics": portal_metrics.models.get("PageMetrics"),
        "form_metrics": portal_metrics.models.get("FormMetrics"),
        "custom_events": portal_metrics.models.get("CustomEvent"),
    }

    model = model_map.get(table_name)
    if not model:
        return [], 0

    db = portal_metrics.db
    query = db.session.query(model)

    # Apply date filter
    if date_range:
        start, end = date_range
        query = query.filter(and_(model.timestamp >= start, model.timestamp <= end))

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * per_page
    records = query.order_by(model.timestamp.desc()).offset(offset).limit(per_page).all()

    # Convert to dict
    data = [record.to_dict() for record in records]

    return data, total


class PowerBIExporter:
    """Utility class for Power BI data export operations.

    Provides methods for exporting data with various aggregations
    and formats optimized for Power BI consumption.
    """

    def __init__(self, portal_metrics: "PortalMetrics"):
        """Initialize the exporter.

        Args:
            portal_metrics: Parent PortalMetrics instance
        """
        self.portal_metrics = portal_metrics
        self.db = portal_metrics.db

    def export_all(
        self,
        date_range: Optional[Tuple[str, str]] = None,
        tables: Optional[List[str]] = None,
        aggregation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Export data from multiple tables.

        Args:
            date_range: Tuple of (start_date, end_date) in YYYY-MM-DD format
            tables: List of tables to export
            aggregation: Aggregation level (daily, weekly, monthly, None)

        Returns:
            Dict with table data
        """
        tables = tables or ["user_activity", "page_metrics", "form_metrics", "custom_events"]

        # Parse date range
        parsed_range = None
        if date_range:
            try:
                start = datetime.strptime(date_range[0], "%Y-%m-%d")
                end = datetime.strptime(date_range[1], "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
                parsed_range = (start, end)
            except (ValueError, TypeError):
                pass

        result = {}
        for table in tables:
            if aggregation and aggregation != "none":
                result[table] = self._export_aggregated(table, parsed_range, aggregation)
            else:
                data, total = _export_table(
                    self.portal_metrics,
                    table,
                    parsed_range,
                    page=1,
                    per_page=10000,
                    aggregation=None,
                )
                result[table] = {
                    "data": data,
                    "total": total,
                }

        return result

    def _export_aggregated(
        self,
        table_name: str,
        date_range: Optional[Tuple[datetime, datetime]],
        aggregation: str,
    ) -> Dict[str, Any]:
        """Export aggregated data for a table.

        Args:
            table_name: Name of table
            date_range: Date range filter
            aggregation: Aggregation level

        Returns:
            Dict with aggregated data
        """
        models = self.portal_metrics.models

        if table_name == "user_activity":
            return self._aggregate_user_activity(date_range, aggregation)
        elif table_name == "page_metrics":
            return self._aggregate_page_metrics(date_range, aggregation)
        elif table_name == "form_metrics":
            return self._aggregate_form_metrics(date_range, aggregation)
        else:
            return {"data": [], "total": 0}

    def _aggregate_user_activity(
        self,
        date_range: Optional[Tuple[datetime, datetime]],
        aggregation: str,
    ) -> Dict[str, Any]:
        """Aggregate user activity data."""
        UserActivity = self.portal_metrics.models.get("UserActivity")
        if not UserActivity:
            return {"data": [], "total": 0}

        # Use database-agnostic date casting
        date_col = cast(UserActivity.timestamp, Date)

        query = self.db.session.query(
            date_col.label("date"),
            func.count(UserActivity.id).label("total_requests"),
            func.count(func.distinct(UserActivity.user_id)).label("unique_users"),
            func.count(func.distinct(UserActivity.session_id)).label("unique_sessions"),
            func.avg(UserActivity.response_time_ms).label("avg_response_time_ms"),
        ).group_by(date_col)

        if date_range:
            query = query.filter(
                and_(
                    UserActivity.timestamp >= date_range[0], UserActivity.timestamp <= date_range[1]
                )
            )

        results = query.order_by(date_col).all()

        # Convert to daily data first
        daily_data = [
            {
                "date": (
                    row.date
                    if isinstance(row.date, str)
                    else row.date.isoformat() if row.date else None
                ),
                "total_requests": row.total_requests,
                "unique_users": row.unique_users,
                "unique_sessions": row.unique_sessions,
                "avg_response_time_ms": (
                    round(row.avg_response_time_ms, 2) if row.avg_response_time_ms else None
                ),
            }
            for row in results
        ]

        # Apply weekly/monthly aggregation in Python (database-agnostic)
        if aggregation in ("weekly", "monthly"):
            data = self._aggregate_by_period(daily_data, aggregation)
        else:
            data = daily_data

        return {"data": data, "total": len(data)}

    def _aggregate_page_metrics(
        self,
        date_range: Optional[Tuple[datetime, datetime]],
        aggregation: str,
    ) -> Dict[str, Any]:
        """Aggregate page metrics data."""
        PageMetrics = self.portal_metrics.models.get("PageMetrics")
        if not PageMetrics:
            return {"data": [], "total": 0}

        # Use database-agnostic date casting
        date_col = cast(PageMetrics.timestamp, Date)

        query = self.db.session.query(
            date_col.label("date"),
            func.count(PageMetrics.id).label("total_page_views"),
            func.count(func.distinct(PageMetrics.user_id)).label("unique_users"),
            func.avg(PageMetrics.time_on_page_ms).label("avg_time_on_page_ms"),
            func.avg(PageMetrics.scroll_depth_percent).label("avg_scroll_depth"),
        ).group_by(date_col)

        if date_range:
            query = query.filter(
                and_(PageMetrics.timestamp >= date_range[0], PageMetrics.timestamp <= date_range[1])
            )

        results = query.order_by(date_col).all()

        daily_data = [
            {
                "date": (
                    row.date
                    if isinstance(row.date, str)
                    else row.date.isoformat() if row.date else None
                ),
                "total_page_views": row.total_page_views,
                "unique_users": row.unique_users,
                "avg_time_on_page_ms": (
                    round(row.avg_time_on_page_ms, 2) if row.avg_time_on_page_ms else None
                ),
                "avg_scroll_depth": (
                    round(row.avg_scroll_depth, 2) if row.avg_scroll_depth else None
                ),
            }
            for row in results
        ]

        # Apply weekly/monthly aggregation in Python (database-agnostic)
        if aggregation in ("weekly", "monthly"):
            data = self._aggregate_page_data_by_period(daily_data, aggregation)
        else:
            data = daily_data

        return {"data": data, "total": len(data)}

    def _aggregate_form_metrics(
        self,
        date_range: Optional[Tuple[datetime, datetime]],
        aggregation: str,
    ) -> Dict[str, Any]:
        """Aggregate form metrics data."""
        FormMetrics = self.portal_metrics.models.get("FormMetrics")
        if not FormMetrics:
            return {"data": [], "total": 0}

        # Use database-agnostic date casting
        date_col = cast(FormMetrics.timestamp, Date)

        query = (
            self.db.session.query(
                date_col.label("date"),
                FormMetrics.form_name,
                func.count(FormMetrics.id).label("total_interactions"),
                func.sum(func.cast(FormMetrics.completion_status, self.db.Integer)).label(
                    "successful_submissions"
                ),
            )
            .filter(FormMetrics.interaction_type == "submit")
            .group_by(date_col, FormMetrics.form_name)
        )

        if date_range:
            query = query.filter(
                and_(FormMetrics.timestamp >= date_range[0], FormMetrics.timestamp <= date_range[1])
            )

        results = query.order_by(date_col).all()

        data = [
            {
                "date": (
                    row.date
                    if isinstance(row.date, str)
                    else row.date.isoformat() if row.date else None
                ),
                "form_name": row.form_name,
                "total_submissions": row.total_interactions,
                "successful_submissions": row.successful_submissions or 0,
                "success_rate": (
                    round(100 * (row.successful_submissions or 0) / row.total_interactions, 2)
                    if row.total_interactions
                    else 0
                ),
            }
            for row in results
        ]

        # Note: Weekly/monthly aggregation for forms would require more complex logic
        # due to form_name grouping. Returning daily data grouped by form.
        return {"data": data, "total": len(data)}

    def _get_period_key(self, date_str: str, aggregation: str) -> str:
        """Get the period key for a date based on aggregation level.

        Args:
            date_str: Date string in YYYY-MM-DD format
            aggregation: 'weekly' or 'monthly'

        Returns:
            Period key string (week start date or month start date)
        """
        try:
            date_obj = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return date_str

        if aggregation == "weekly":
            # Get Monday of the week
            week_start = date_obj - timedelta(days=date_obj.weekday())
            return week_start.strftime("%Y-%m-%d")
        elif aggregation == "monthly":
            return date_obj.strftime("%Y-%m-01")
        return date_str

    def _aggregate_by_period(self, daily_data: List[Dict], aggregation: str) -> List[Dict]:
        """Aggregate daily user activity data by week or month.

        Args:
            daily_data: List of daily data dicts
            aggregation: 'weekly' or 'monthly'

        Returns:
            Aggregated data list
        """
        periods = defaultdict(
            lambda: {
                "total_requests": 0,
                "unique_users": set(),
                "unique_sessions": set(),
                "response_times": [],
            }
        )

        for row in daily_data:
            period_key = self._get_period_key(row["date"], aggregation)
            periods[period_key]["total_requests"] += row["total_requests"]
            # Note: For proper unique counting across days, we'd need raw data
            # This is an approximation using sums (may overcount)
            periods[period_key]["unique_users"].add(row.get("unique_users", 0))
            periods[period_key]["unique_sessions"].add(row.get("unique_sessions", 0))
            if row.get("avg_response_time_ms"):
                periods[period_key]["response_times"].append(row["avg_response_time_ms"])

        result = []
        for period_key in sorted(periods.keys()):
            p = periods[period_key]
            avg_response = None
            if p["response_times"]:
                avg_response = round(sum(p["response_times"]) / len(p["response_times"]), 2)

            result.append(
                {
                    "date": period_key,
                    "total_requests": p["total_requests"],
                    "unique_users": (
                        sum(p["unique_users"])
                        if isinstance(list(p["unique_users"])[0] if p["unique_users"] else 0, int)
                        else len(p["unique_users"])
                    ),
                    "unique_sessions": (
                        sum(p["unique_sessions"])
                        if isinstance(
                            list(p["unique_sessions"])[0] if p["unique_sessions"] else 0, int
                        )
                        else len(p["unique_sessions"])
                    ),
                    "avg_response_time_ms": avg_response,
                }
            )

        return result

    def _aggregate_page_data_by_period(
        self, daily_data: List[Dict], aggregation: str
    ) -> List[Dict]:
        """Aggregate daily page metrics data by week or month.

        Args:
            daily_data: List of daily data dicts
            aggregation: 'weekly' or 'monthly'

        Returns:
            Aggregated data list
        """
        periods = defaultdict(
            lambda: {
                "total_page_views": 0,
                "unique_users_sum": 0,
                "time_on_page_values": [],
                "scroll_depth_values": [],
            }
        )

        for row in daily_data:
            period_key = self._get_period_key(row["date"], aggregation)
            periods[period_key]["total_page_views"] += row["total_page_views"]
            periods[period_key]["unique_users_sum"] += row.get("unique_users", 0) or 0
            if row.get("avg_time_on_page_ms"):
                periods[period_key]["time_on_page_values"].append(row["avg_time_on_page_ms"])
            if row.get("avg_scroll_depth"):
                periods[period_key]["scroll_depth_values"].append(row["avg_scroll_depth"])

        result = []
        for period_key in sorted(periods.keys()):
            p = periods[period_key]
            avg_time = None
            if p["time_on_page_values"]:
                avg_time = round(sum(p["time_on_page_values"]) / len(p["time_on_page_values"]), 2)
            avg_scroll = None
            if p["scroll_depth_values"]:
                avg_scroll = round(sum(p["scroll_depth_values"]) / len(p["scroll_depth_values"]), 2)

            result.append(
                {
                    "date": period_key,
                    "total_page_views": p["total_page_views"],
                    "unique_users": p["unique_users_sum"],  # Approximation
                    "avg_time_on_page_ms": avg_time,
                    "avg_scroll_depth": avg_scroll,
                }
            )

        return result

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
        """
        UserActivity = self.portal_metrics.models.get("UserActivity")
        PageMetrics = self.portal_metrics.models.get("PageMetrics")

        if not UserActivity:
            return []

        # Build date range
        date_range = None
        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                date_range = (start, end)
            except ValueError:
                pass

        # Query user activity aggregates using database-agnostic date casting
        date_col = cast(UserActivity.timestamp, Date)
        ua_query = self.db.session.query(
            date_col.label("date"),
            func.count(UserActivity.id).label("total_requests"),
            func.count(func.distinct(UserActivity.user_id)).label("unique_users"),
            func.count(func.distinct(UserActivity.session_id)).label("unique_sessions"),
            func.avg(UserActivity.response_time_ms).label("avg_response_time_ms"),
            func.sum(case((UserActivity.response_code >= 400, 1), else_=0)).label("error_count"),
        ).group_by(date_col)

        if date_range:
            ua_query = ua_query.filter(
                and_(
                    UserActivity.timestamp >= date_range[0], UserActivity.timestamp <= date_range[1]
                )
            )

        ua_results = {}
        for row in ua_query.all():
            date_key = row.date.isoformat() if hasattr(row.date, "isoformat") else str(row.date)
            ua_results[date_key] = row

        # Build summary
        summary = []
        for date_str, ua in ua_results.items():
            error_count = ua.error_count or 0
            summary.append(
                {
                    "date": date_str,
                    "total_requests": ua.total_requests,
                    "unique_users": ua.unique_users,
                    "unique_sessions": ua.unique_sessions,
                    "avg_response_time_ms": (
                        round(ua.avg_response_time_ms, 2) if ua.avg_response_time_ms else None
                    ),
                    "error_count": error_count,
                    "error_rate": (
                        round(100 * error_count / ua.total_requests, 2) if ua.total_requests else 0
                    ),
                }
            )

        return sorted(summary, key=lambda x: x["date"])


# Pre-built SQL queries for Power BI direct database connections.
# NOTE: These queries use common SQL syntax. Some functions may need adaptation:
# - DATE(): Standard SQL, works in most databases
# - CAST(timestamp AS DATE): Alternative for PostgreSQL/SQL Server
# - strftime(): SQLite-specific, use EXTRACT(HOUR FROM timestamp) for PostgreSQL
# - GROUP_CONCAT(): MySQL/SQLite, use STRING_AGG() for PostgreSQL/SQL Server
POWERBI_SQL_QUERIES = {
    "daily_active_users": """
        SELECT CAST(timestamp AS DATE) as date, COUNT(DISTINCT user_id) as dau
        FROM portal_metrics_user_activity
        WHERE user_id IS NOT NULL
        GROUP BY CAST(timestamp AS DATE)
        ORDER BY date;
    """,
    "response_time_by_endpoint": """
        SELECT endpoint, 
               COUNT(*) as request_count,
               AVG(response_time_ms) as avg_response_time,
               MIN(response_time_ms) as min_response_time,
               MAX(response_time_ms) as max_response_time
        FROM portal_metrics_user_activity
        GROUP BY endpoint
        ORDER BY avg_response_time DESC;
    """,
    "page_engagement": """
        SELECT page_url, 
               AVG(time_on_page_ms) / 1000.0 as avg_seconds,
               AVG(scroll_depth_percent) as avg_scroll_depth,
               COUNT(*) as page_views
        FROM portal_metrics_page_metrics
        GROUP BY page_url
        ORDER BY page_views DESC;
    """,
    "form_completion_rates": """
        SELECT form_name,
               COUNT(*) as total_submissions,
               SUM(CASE WHEN completion_status = 1 THEN 1 ELSE 0 END) as successful,
               ROUND(100.0 * SUM(CASE WHEN completion_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
        FROM portal_metrics_form_metrics
        WHERE interaction_type = 'submit'
        GROUP BY form_name;
    """,
    "hourly_traffic_pattern": """
        -- PostgreSQL: EXTRACT(HOUR FROM timestamp)
        -- SQL Server: DATEPART(hour, timestamp)
        -- SQLite: strftime('%H', timestamp)
        SELECT EXTRACT(HOUR FROM timestamp) as hour,
               COUNT(*) as request_count
        FROM portal_metrics_user_activity
        GROUP BY EXTRACT(HOUR FROM timestamp)
        ORDER BY hour;
    """,
    "user_journey": """
        -- PostgreSQL: STRING_AGG(path, ' -> ' ORDER BY timestamp)
        -- SQL Server: STRING_AGG(path, ' -> ') WITHIN GROUP (ORDER BY timestamp)  
        -- MySQL/SQLite: GROUP_CONCAT(path, ' -> ')
        SELECT user_id,
               STRING_AGG(path, ' -> ' ORDER BY timestamp) as journey,
               COUNT(*) as page_count
        FROM portal_metrics_user_activity
        WHERE user_id IS NOT NULL
        GROUP BY user_id, CAST(timestamp AS DATE)
        ORDER BY MIN(timestamp);
    """,
}
