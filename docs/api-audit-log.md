# Audit Log API

## Overview

The Audit Log API provides comprehensive logging for security compliance and system monitoring. All significant system actions are recorded with actor information, timestamps, and resource details.

**Access Level**: Admin only (`admin` role required)

**Purpose**:
- Security monitoring and incident investigation
- Compliance auditing (who did what, when)
- User activity tracking
- System change history

## Base Endpoint

```
/api/v1/admin/audit
```

---

## Authentication

**Required Role**: `admin`

```http
Authorization: Bearer {admin-jwt-token}
```

Attempting to access without admin role returns:
```json
{
  "detail": "Admin access required"
}
```

---

## Endpoints

### 1. List Audit Logs

```http
GET /api/v1/admin/audit/logs
```

#### Description
Retrieve audit logs with filtering, sorting, and pagination.

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | datetime | No | Filter from date (ISO 8601) |
| `end_date` | datetime | No | Filter to date (ISO 8601) |
| `actor_id` | UUID | No | Filter by user who performed action |
| `action` | string | No | Filter by action type (e.g., `user.created`) |
| `resource_type` | string | No | Filter by resource (e.g., `job`, `user`) |
| `resource_id` | UUID | No | Filter by specific resource ID |
| `ip_address` | string | No | Filter by IP address (partial match) |
| `page` | integer | No | Page number (default: 1) |
| `page_size` | integer | No | Items per page (default: 50, max: 100) |

#### Action Types

| Action | Description |
|--------|-------------|
| `user.created` | User account created |
| `user.role_changed` | User role modified |
| `user.deactivated` | User deactivated |
| `user.reactivated` | User reactivated |
| `user.login` | Successful login |
| `user.login_failed` | Failed login attempt |
| `job.created` | Job created |
| `job.cancelled` | Job cancelled |
| `annotation.submitted` | Annotation submitted |
| `asr_review.approved` | ASR review approved |
| `token.refreshed` | Access token refreshed |

#### Response Schema

```typescript
interface AuditLogListResponse {
  items: AuditLogItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

interface AuditLogItem {
  id: string;                    // Log entry UUID
  timestamp: string;             // ISO 8601 timestamp
  actor: {
    id: string;                  // User UUID
    email: string;               // User email
  } | null;                       // null for system actions
  action: string;                // Action type code
  action_label: string;          // Human-readable label
  resource: {
    type: string;                // Resource type
    id: string;                  // Resource UUID
  };
  details: Record<string, any>;  // Additional details
  ip_address: string | null;     // IP address
}
```

#### Example Request

```http
GET /api/v1/admin/audit/logs?action=user.login&page=1&page_size=20
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

#### Example Response

```json
{
  "items": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440001",
      "timestamp": "2026-04-08T14:30:00.000Z",
      "actor": {
        "id": "990e8400-e29b-41d4-a716-446655440000",
        "email": "annotator@example.com"
      },
      "action": "user.login",
      "action_label": "User Login",
      "resource": {
        "type": "auth",
        "id": "990e8400-e29b-41d4-a716-446655440000"
      },
      "details": {
        "email": "annotator@example.com",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "status_code": 200
      },
      "ip_address": "192.168.1.100"
    },
    {
      "id": "880e8400-e29b-41d4-a716-446655440002",
      "timestamp": "2026-04-08T14:25:00.000Z",
      "actor": {
        "id": "990e8400-e29b-41d4-a716-446655440001",
        "email": "admin@example.com"
      },
      "action": "user.created",
      "action_label": "User Created",
      "resource": {
        "type": "user",
        "id": "990e8400-e29b-41d4-a716-446655440002"
      },
      "details": {
        "email": "newuser@example.com",
        "roles": ["annotator"]
      },
      "ip_address": "192.168.1.101"
    }
  ],
  "total": 156,
  "page": 1,
  "page_size": 20,
  "pages": 8
}
```

---

### 2. Get Single Audit Log

```http
GET /api/v1/admin/audit/logs/{log_id}
```

#### Description
Retrieve detailed information about a specific audit log entry.

#### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `log_id` | UUID | Yes | Audit log entry ID |

#### Response Schema

```typescript
interface AuditLogDetailResponse {
  id: string;
  timestamp: string;
  actor: {
    id: string;
    email: string;
  } | null;
  action: string;
  action_label: string;
  resource: {
    type: string;
    id: string;
  };
  details: Record<string, any>;
  ip_address: string | null;
  user_agent: string | null;     // Additional detail field
}
```

#### Example Response

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440001",
  "timestamp": "2026-04-08T14:30:00.000Z",
  "actor": {
    "id": "990e8400-e29b-41d4-a716-446655440000",
    "email": "admin@example.com"
  },
  "action": "user.role_changed",
  "action_label": "User Role Changed",
  "resource": {
    "type": "user",
    "id": "990e8400-e29b-41d4-a716-446655440001"
  },
  "details": {
    "email": "user@example.com",
    "old_role": "annotator",
    "new_role": "curator"
  },
  "ip_address": "192.168.1.100",
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
```

---

### 3. Get Audit Statistics

```http
GET /api/v1/admin/audit/stats
```

#### Description
Get audit log statistics and analytics for a time period.

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | datetime | No | Period start (ISO 8601) |
| `end_date` | datetime | No | Period end (ISO 8601) |
| `days` | integer | No | Look back N days (alternative to date range) |

#### Response Schema

```typescript
interface AuditStatsSummary {
  total_logs: number;            // Total log entries in period
  unique_users: number;          // Unique actors
  period_start: string | null;   // ISO 8601
  period_end: string | null;     // ISO 8601
  top_actions: ActionCount[];    // Most frequent actions
  daily_activity: DailyActivity[];
}

interface ActionCount {
  action: string;
  label: string;
  count: number;
}

interface DailyActivity {
  date: string;                  // YYYY-MM-DD
  count: number;
}
```

#### Example Request

```http
GET /api/v1/admin/audit/stats?days=30
```

#### Example Response

```json
{
  "total_logs": 1250,
  "unique_users": 15,
  "period_start": "2026-03-09T00:00:00.000Z",
  "period_end": "2026-04-08T23:59:59.000Z",
  "top_actions": [
    { "action": "user.login", "label": "User Login", "count": 450 },
    { "action": "annotation.submitted", "label": "Annotation Submitted", "count": 280 },
    { "action": "job.created", "label": "Job Created", "count": 120 }
  ],
  "daily_activity": [
    { "date": "2026-04-01", "count": 45 },
    { "date": "2026-04-02", "count": 52 },
    { "date": "2026-04-03", "count": 38 }
  ]
}
```

---

### 4. Get User Activity

```http
GET /api/v1/admin/audit/users/{user_id}/activity
```

#### Description
Get activity summary for a specific user.

#### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | UUID | Yes | User ID |

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period_days` | integer | No | Period in days (default: 30, max: 365) |

#### Response Schema

```typescript
interface UserActivitySummary {
  user_id: string;
  email: string;
  total_actions: number;
  last_active: string | null;    // ISO 8601
  actions_by_type: ActionCount[];
  period_days: number;
}
```

#### Example Response

```json
{
  "user_id": "990e8400-e29b-41d4-a716-446655440000",
  "email": "annotator@example.com",
  "total_actions": 45,
  "last_active": "2026-04-08T16:30:00.000Z",
  "actions_by_type": [
    { "action": "annotation.submitted", "label": "Annotation Submitted", "count": 25 },
    { "action": "annotation.updated", "label": "Annotation Updated", "count": 15 },
    { "action": "user.login", "label": "User Login", "count": 5 }
  ],
  "period_days": 30
}
```

---

### 5. Get Resource Activity

```http
GET /api/v1/admin/audit/resources/{resource_type}/{resource_id}
```

#### Description
Get activity history for a specific resource (job, annotation, etc.).

#### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `resource_type` | string | Yes | Resource type (`job`, `annotation`, etc.) |
| `resource_id` | UUID | Yes | Resource UUID |

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | No | Number of actions to return (default: 50, max: 100) |

#### Response Schema

```typescript
interface ResourceActivitySummary {
  resource_type: string;
  resource_id: string;
  total_actions: number;
  created_at: string | null;
  last_modified: string | null;
  action_history: AuditLogItem[];
}
```

#### Example Request

```http
GET /api/v1/admin/audit/resources/job/550e8400-e29b-41d4-a716-446655440000
```

#### Example Response

```json
{
  "resource_type": "job",
  "resource_id": "550e8400-e29b-41d4-a716-446655440000",
  "total_actions": 5,
  "created_at": "2026-04-08T10:00:00.000Z",
  "last_modified": "2026-04-08T14:30:00.000Z",
  "action_history": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440001",
      "timestamp": "2026-04-08T14:30:00.000Z",
      "actor": { "id": "...", "email": "admin@example.com" },
      "action": "job.cancelled",
      "action_label": "Job Cancelled",
      "resource": { "type": "job", "id": "550e8400-..." },
      "details": { "previous_status": "CROPPING" },
      "ip_address": "192.168.1.100"
    }
  ]
}
```

---

### 6. Export Audit Logs

```http
GET /api/v1/admin/audit/export
```

#### Description
Export audit logs to CSV or JSON format.

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `format` | string | Yes | Export format: `json` or `csv` |
| `start_date` | datetime | No | Export from date |
| `end_date` | datetime | No | Export to date |
| `days` | integer | No | Export last N days |
| `action` | string | No | Filter by action type |
| `actor_id` | UUID | No | Filter by actor |
| `resource_type` | string | No | Filter by resource type |

#### Response

Returns file download with appropriate Content-Type:
- `application/json` for JSON format
- `text/csv` for CSV format

#### Example Request

```http
GET /api/v1/admin/audit/export?format=csv&days=7
```

#### CSV Format

```csv
timestamp,actor_id,actor_email,action,action_label,resource_type,resource_id,ip_address,details
2026-04-08T14:30:00.000Z,990e8400-e29b-41d4-a716-446655440000,admin@example.com,user.created,User Created,user,990e8400-e29b-41d4-a716-446655440001,192.168.1.100,"{""email"":""newuser@example.com""}"
```

---

### 7. Get Available Filters

```http
GET /api/v1/admin/audit/filters
```

#### Description
Get available filter values for building filter UI.

#### Response Schema

```typescript
interface AvailableFilters {
  actions: Array<{
    action: string;
    label: string;
  }>;
  resource_types: string[];
}
```

#### Example Response

```json
{
  "actions": [
    { "action": "user.created", "label": "User Created" },
    { "action": "user.login", "label": "User Login" },
    { "action": "job.created", "label": "Job Created" },
    { "action": "annotation.submitted", "label": "Annotation Submitted" }
  ],
  "resource_types": ["auth", "user", "job", "annotation", "asr_review"]
}
```

---

## Frontend Integration Guide

### Audit Log Dashboard

```typescript
// React component for audit log dashboard
import { useState, useEffect } from 'react';

interface Filters {
  start_date?: string;
  end_date?: string;
  action?: string;
  actor_id?: string;
}

function AuditLogDashboard({ token }: { token: string }) {
  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [filters, setFilters] = useState<Filters>({});
  const [pagination, setPagination] = useState({ page: 1, page_size: 50 });
  const [loading, setLoading] = useState(false);

  const fetchLogs = async () => {
    setLoading(true);
    
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.append(key, value);
    });
    params.append('page', String(pagination.page));
    params.append('page_size', String(pagination.page_size));
    
    const response = await fetch(
      `/api/v1/admin/audit/logs?${params}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    
    const data = await response.json();
    setLogs(data.items);
    setLoading(false);
  };

  useEffect(() => {
    fetchLogs();
  }, [filters, pagination]);

  return (
    <div className="audit-log-dashboard">
      <FilterBar filters={filters} onChange={setFilters} />
      <AuditLogTable logs={logs} loading={loading} />
      <Pagination 
        current={pagination.page} 
        onChange={(page) => setPagination(p => ({ ...p, page }))}
      />
    </div>
  );
}
```

### Activity Timeline Chart

```typescript
// Using Chart.js or Recharts
import { LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts';

function ActivityChart({ stats }: { stats: AuditStatsSummary }) {
  return (
    <LineChart width={600} height={300} data={stats.daily_activity}>
      <XAxis dataKey="date" />
      <YAxis />
      <Tooltip />
      <Line type="monotone" dataKey="count" stroke="#8884d8" />
    </LineChart>
  );
}
```

### Export Button

```typescript
function ExportButton({ filters, token }: { filters: Filters; token: string }) {
  const handleExport = async (format: 'json' | 'csv') => {
    const params = new URLSearchParams();
    params.append('format', format);
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.append(key, value);
    });
    
    const response = await fetch(
      `/api/v1/admin/audit/export?${params}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit_logs_${new Date().toISOString().split('T')[0]}.${format}`;
    a.click();
  };

  return (
    <div className="export-buttons">
      <button onClick={() => handleExport('csv')}>Export CSV</button>
      <button onClick={() => handleExport('json')}>Export JSON</button>
    </div>
  );
}
```

---

## Common Use Cases

### 1. Security Monitoring

```javascript
// Monitor failed login attempts
async function checkFailedLogins(token) {
  const response = await fetch(
    '/api/v1/admin/audit/logs?action=user.login_failed&page_size=100',
    { headers: { Authorization: `Bearer ${token}` } }
  );
  
  const data = await response.json();
  
  // Group by IP
  const byIp = data.items.reduce((acc, log) => {
    const ip = log.ip_address;
    acc[ip] = (acc[ip] || 0) + 1;
    return acc;
  }, {});
  
  // Alert on suspicious activity
  Object.entries(byIp).forEach(([ip, count]) => {
    if (count > 5) {
      alert(`Suspicious activity from IP ${ip}: ${count} failed logins`);
    }
  });
}
```

### 2. User Activity Report

```javascript
// Generate monthly activity report
async function generateUserReport(userId, token) {
  const response = await fetch(
    `/api/v1/admin/audit/users/${userId}/activity?period_days=30`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  
  const data = await response.json();
  
  return {
    summary: `${data.email} performed ${data.total_actions} actions`,
    breakdown: data.actions_by_type.map(a => 
      `${a.label}: ${a.count}`
    ).join('\n'),
    lastActive: data.last_active
  };
}
```

### 3. Resource Audit Trail

```javascript
// Show complete history of a job
async function getJobHistory(jobId, token) {
  const response = await fetch(
    `/api/v1/admin/audit/resources/job/${jobId}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  
  const data = await response.json();
  
  return data.action_history.map(log => ({
    time: new Date(log.timestamp).toLocaleString(),
    user: log.actor?.email || 'System',
    action: log.action_label,
    details: log.details
  }));
}
```

---

## Data Retention

Audit logs are retained for **1 year** by default. After this period:
- Logs are archived to cold storage
- Can be retrieved via admin request
- Compliance exports should be done before archival

---

## Compliance Notes

1. **Immutability**: Audit logs cannot be modified or deleted
2. **Tamper-proof**: Each log entry has cryptographic integrity
3. **Export**: Regular exports recommended for external compliance systems
4. **PII**: IP addresses are logged for security; handle according to privacy policy
