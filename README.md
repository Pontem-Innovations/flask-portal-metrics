# Flask-Portal-Metrics

[![PyPI version](https://badge.fury.io/py/flask-portal-metrics.svg)](https://badge.fury.io/py/flask-portal-metrics)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Drop-in user activity tracking for Flask applications with Power BI integration.**

Flask-Portal-Metrics provides comprehensive analytics for Flask applications with minimal setup. Track user activity, page metrics, and form interactions automatically, then export data in Power BI-ready format for actionable business insights.

## Features

- **One-Line Integration**: Add full tracking with `PortalMetrics(app, db)`
- **Automatic Request Tracking**: Middleware captures all HTTP requests without code changes
- **Client-Side Analytics**: JavaScript tracking for page time, scroll depth, and form interactions
- **Power BI Ready**: Export endpoints optimized for Power BI data ingestion
- **Privacy Compliant**: IP hashing, PII exclusion, and GDPR-friendly data retention
- **High Performance**: Async writes, sampling rates, and bulk inserts for high-traffic apps
- **Non-Blocking**: Analytics failures never break your main application

## Installation

```bash
pip install flask-portal-metrics
```

For async support with Celery:
```bash
pip install flask-portal-metrics[async]
```

## Quick Start

```python
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_portal_metrics import PortalMetrics

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
db = SQLAlchemy(app)

# Enable full tracking with one line
metrics = PortalMetrics(app, db)

@app.route('/')
def index():
    return 'Hello, World!'

if __name__ == '__main__':
    app.run()
```

That's it! All requests are now being tracked automatically.

## Configuration Options

```python
metrics = PortalMetrics(
    app, 
    db,
    # Database schema for analytics tables (default: None, uses default schema)
    schema='analytics',
    
    # Enable form interaction tracking (default: True)
    track_forms=True,
    
    # Enable performance metrics (default: True)
    track_performance=True,
    
    # Request sampling rate 0.0-1.0 (default: 1.0 = 100%)
    sample_rate=1.0,
    
    # Endpoints to exclude from tracking (default: ['static'])
    exclude_endpoints=['static', 'api.health', 'metrics'],
    
    # Hash IP addresses for privacy (default: False)
    hash_ip=False,
    
    # Form fields to never track (default: ['password', 'token', 'secret', 'credit_card'])
    sensitive_fields=['password', 'ssn', 'credit_card'],
    
    # Data retention in days (default: 90, set to 0 for no auto-cleanup)
    retention_days=90,
    
    # Enable Power BI export endpoint (default: True)
    enable_export_endpoint=True,
    
    # Export endpoint URL (default: '/api/metrics/powerbi')
    export_endpoint='/api/metrics/powerbi',
)
```

## Client-Side Tracking

Add the JavaScript tracker to your base template:

```html
<!-- In your base template, before </body> -->
<script src="{{ url_for('portal_metrics.static', filename='metrics.js') }}"></script>
<script>
    PortalMetrics.init({
        endpoint: '/api/metrics/client',
        trackPageTime: true,
        trackScrollDepth: true,
        trackForms: true,
        sampleRate: 1.0,  // Track 100% of page views
        userId: {{ current_user.id if current_user.is_authenticated else 'null' }}
    });
</script>
```

## Data Schema

Flask-Portal-Metrics creates three tables in your database:

### UserActivity
Tracks server-side request/response data:
| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| endpoint | String | Flask endpoint name |
| method | String | HTTP method (GET, POST, etc.) |
| path | String | Request path |
| response_code | Integer | HTTP response code |
| response_time_ms | Float | Response time in milliseconds |
| user_id | String | User identifier (nullable) |
| session_id | String | Session identifier |
| ip_address | String | Client IP (optionally hashed) |
| user_agent | String | Browser user agent |
| referrer | String | HTTP referrer |
| timestamp | DateTime | UTC timestamp |

### PageMetrics
Tracks client-side page engagement:
| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| user_id | String | User identifier (nullable) |
| session_id | String | Session identifier |
| page_url | String | Page URL |
| page_title | String | Page title |
| time_on_page_ms | Integer | Time spent on page in ms |
| scroll_depth_percent | Integer | Maximum scroll depth (0-100) |
| timestamp | DateTime | UTC timestamp |

### FormMetrics
Tracks form interaction data:
| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| user_id | String | User identifier (nullable) |
| session_id | String | Session identifier |
| form_name | String | Form identifier |
| field_name | String | Field name (nullable) |
| interaction_type | String | focus, blur, submit, error |
| completion_status | Boolean | Form completed successfully |
| error_message | String | Error message if any |
| timestamp | DateTime | UTC timestamp |

## Custom Event Tracking

Track custom business events:

```python
# Track a custom event
metrics.track_event(
    'document_upload',
    user_id=current_user.id,
    metadata={
        'file_type': 'pdf',
        'file_size_kb': 1024,
        'category': 'reports'
    }
)

# Track with session context
metrics.track_event(
    'purchase_completed',
    user_id=current_user.id,
    session_id=session.get('session_id'),
    metadata={
        'order_id': 'ORD-12345',
        'total': 99.99,
        'items_count': 3
    }
)
```

## Power BI Integration

### Export Endpoint

The built-in export endpoint provides data in Power BI-friendly JSON format:

```
GET /api/metrics/powerbi?start_date=2026-01-01&end_date=2026-03-10&table=user_activity
```

Query parameters:
- `start_date`: Start date (YYYY-MM-DD format)
- `end_date`: End date (YYYY-MM-DD format)
- `table`: One of `user_activity`, `page_metrics`, `form_metrics`, `daily_summary`, `all`
- `page`: Page number for pagination (default: 1)
- `per_page`: Records per page (default: 1000, max: 10000)

### Programmatic Export

```python
# Export data for Power BI
data = metrics.export_for_powerbi(
    date_range=('2026-01-01', '2026-03-10'),
    tables=['user_activity', 'page_metrics'],
    aggregation='daily'  # or 'weekly', 'monthly', None
)

# Get daily summary for dashboards
summary = metrics.get_daily_summary(
    start_date='2026-01-01',
    end_date='2026-03-10'
)
```

### Sample Power BI Queries

Connect Power BI to your endpoint and use these M queries:

```m
// User Activity Data
let
    Source = Json.Document(Web.Contents("https://yourapp.com/api/metrics/powerbi?table=user_activity&start_date=2026-01-01&end_date=2026-03-10")),
    data = Source[data],
    #"Converted to Table" = Table.FromList(data, Splitter.SplitByNothing(), null, null, ExtraValues.Error),
    #"Expanded Column1" = Table.ExpandRecordColumn(#"Converted to Table", "Column1", {"endpoint", "method", "response_time_ms", "user_id", "timestamp"})
in
    #"Expanded Column1"
```

### Pre-Built SQL Queries

```sql
-- Daily active users
SELECT DATE(timestamp) as date, COUNT(DISTINCT user_id) as dau
FROM user_activity
WHERE user_id IS NOT NULL
GROUP BY DATE(timestamp)
ORDER BY date;

-- Average response time by endpoint
SELECT endpoint, AVG(response_time_ms) as avg_response_time
FROM user_activity
GROUP BY endpoint
ORDER BY avg_response_time DESC;

-- Page engagement metrics
SELECT page_url, 
       AVG(time_on_page_ms) / 1000.0 as avg_seconds,
       AVG(scroll_depth_percent) as avg_scroll_depth,
       COUNT(*) as page_views
FROM page_metrics
GROUP BY page_url
ORDER BY page_views DESC;

-- Form completion rates
SELECT form_name,
       COUNT(*) as total_submissions,
       SUM(CASE WHEN completion_status = 1 THEN 1 ELSE 0 END) as successful,
       ROUND(100.0 * SUM(CASE WHEN completion_status = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM form_metrics
WHERE interaction_type = 'submit'
GROUP BY form_name;
```

## Performance Tuning

### High-Traffic Applications

For applications with high request volumes:

```python
metrics = PortalMetrics(
    app, db,
    sample_rate=0.1,  # Track only 10% of requests
    exclude_endpoints=['static', 'api.health', 'favicon'],
)
```

### Async Processing with Celery

Enable async database writes:

```python
from celery import Celery

celery = Celery('tasks', broker='redis://localhost:6379/0')

metrics = PortalMetrics(app, db)
metrics.enable_async(celery)
```

### Database Indexes

Add these indexes for optimal query performance:

```sql
CREATE INDEX idx_user_activity_timestamp ON user_activity(timestamp);
CREATE INDEX idx_user_activity_user_id ON user_activity(user_id);
CREATE INDEX idx_user_activity_endpoint ON user_activity(endpoint);
CREATE INDEX idx_page_metrics_timestamp ON page_metrics(timestamp);
CREATE INDEX idx_page_metrics_user_id ON page_metrics(user_id);
```

## Migration Guide

### Adding to Existing Flask App

1. Install the package:
   ```bash
   pip install flask-portal-metrics
   ```

2. Initialize after your SQLAlchemy setup:
   ```python
   from flask_portal_metrics import PortalMetrics
   
   # After db = SQLAlchemy(app)
   metrics = PortalMetrics(app, db)
   ```

3. Create the database tables:
   ```python
   with app.app_context():
       db.create_all()
   ```

4. Add client-side tracking to your base template (optional)

### Database Migration

If using Flask-Migrate/Alembic:

```bash
flask db migrate -m "Add portal metrics tables"
flask db upgrade
```

## Security & Privacy

### IP Address Hashing

```python
metrics = PortalMetrics(app, db, hash_ip=True)
```

IPs are hashed using SHA-256 with a salt derived from your `SECRET_KEY`.

### Sensitive Field Exclusion

```python
metrics = PortalMetrics(
    app, db,
    sensitive_fields=['password', 'ssn', 'credit_card', 'cvv', 'bank_account']
)
```

### Data Retention

Automatic cleanup of old data:

```python
metrics = PortalMetrics(app, db, retention_days=90)

# Manual cleanup
metrics.cleanup_old_data(days=30)
```

### GDPR Compliance

```python
# Delete all data for a specific user
metrics.delete_user_data(user_id='user123')

# Export all data for a specific user (data portability)
user_data = metrics.export_user_data(user_id='user123')
```

## API Reference

### PortalMetrics Class

#### Methods

| Method | Description |
|--------|-------------|
| `track_event(name, user_id, metadata)` | Track a custom event |
| `export_for_powerbi(date_range, tables, aggregation)` | Export data for Power BI |
| `get_daily_summary(start_date, end_date)` | Get aggregated daily stats |
| `cleanup_old_data(days)` | Remove data older than N days |
| `delete_user_data(user_id)` | Delete all data for a user |
| `export_user_data(user_id)` | Export all data for a user |
| `enable_async(celery)` | Enable async writes with Celery |

#### Properties

| Property | Description |
|----------|-------------|
| `metrics.stats` | Current session statistics |
| `metrics.config` | Current configuration |

## Troubleshooting

### Tables Not Created

Ensure you call `db.create_all()` after initializing PortalMetrics:

```python
metrics = PortalMetrics(app, db)
with app.app_context():
    db.create_all()
```

### Middleware Not Tracking

Check that the endpoint isn't in `exclude_endpoints`:

```python
metrics = PortalMetrics(app, db, exclude_endpoints=['static'])
```

### JavaScript Not Loading

Verify the static files are served correctly:

```python
# Check if blueprint is registered
print(app.blueprints.get('portal_metrics'))
```

## Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests to our GitHub repository.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- GitHub Issues: [Report a bug](https://github.com/pontem-innovations/flask-portal-metrics/issues)
- Documentation: [Full docs](https://github.com/pontem-innovations/flask-portal-metrics#readme)
