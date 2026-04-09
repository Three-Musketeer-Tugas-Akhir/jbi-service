# JBI API Documentation - Overview

## Introduction

This documentation covers three major API modules for the JBI (Jawa Bali Indonesia) Detection & Segmentation System:

1. **Pipeline Stage Results API** - Retrieve processing results from detection, ASR, and cropping stages
2. **Audit Log API** - Comprehensive audit logging for compliance and security monitoring (Admin only)
3. **Annotation Sync API** - Video-audio synchronization workbench for temporal alignment

## Base URL

```
Development: http://localhost:8000/api/v1
Production:  https://your-domain.com/api/v1
```

## Authentication

All APIs require JWT Bearer token authentication except the login endpoint.

### Obtaining a Token

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "your-password"
}
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900
}
```

### Using the Token

Include the token in the Authorization header:

```http
GET /api/v1/pipeline/jobs/{job_id}/stage1/results
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## Role-Based Access Control (RBAC)

| Role | Permissions |
|------|-------------|
| `admin` | Full access to all endpoints including audit logs and user management |
| `annotator` | Access to annotation endpoints, job viewing, and sync operations |
| `curator` | Review and approve annotations |

## Common Response Formats

### Success Response

```json
{
  "id": "uuid",
  "field1": "value1",
  "field2": "value2"
}
```

### Error Response

```json
{
  "detail": "Error message description"
}
```

Common HTTP Status Codes:
- `200 OK` - Success
- `201 Created` - Resource created successfully
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Missing or invalid token
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `422 Unprocessable Entity` - Validation error

## Pagination

List endpoints use the following pagination parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | 1 | Page number (1-indexed) |
| `page_size` | integer | 50 | Items per page (max 100) |

Response format:
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "page_size": 50,
  "pages": 2
}
```

## Date/Time Formats

All timestamps are in ISO 8601 format with timezone:

```
2026-04-08T16:30:00.000Z
```

## Video URL Handling

Video URLs returned by the API are pre-signed URLs from MinIO storage:

- **Expiry**: 1 hour (3600 seconds) by default
- **Format**: Direct MP4 streaming
- **CORS**: Enabled for browser playback

For persistent access, use the assets API:
```
GET /api/v1/assets/{path}
```

## Rate Limiting

- Authentication endpoints: 5 requests per 15 minutes per IP
- Other endpoints: 1000 requests per hour per user

Rate limit headers:
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1649352000
```

## SDK Generation

The API follows OpenAPI 3.0 spec. Generate client SDKs:

```bash
# OpenAPI spec available at
GET /openapi.json

# Generate TypeScript client
npx openapi-typescript http://localhost:8000/openapi.json -o jbi-api.ts
```

## Testing with cURL

```bash
# Set token variable
TOKEN="your-jwt-token"

# Stage 1 results
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/pipeline/jobs/{job_id}/stage1/results

# Audit logs (admin only)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/admin/audit/logs?page=1&page_size=20"

# Annotation sync
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/annotations/sync/{edit_id}
```

## WebSocket Support

Real-time updates for job status:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/jobs/{job_id}');

ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  console.log('Job status:', update.status);
};
```

## File Upload

For video uploads, use the TUS protocol endpoint:

```http
POST /api/v1/upload
Tus-Resumable: 1.0.0
Upload-Length: 104857600
Upload-Metadata: filename dmlkZW8ubXA0
```

## Best Practices

1. **Token Refresh**: Refresh access tokens before expiry using the refresh token
2. **Error Handling**: Always check for 401/403 and re-authenticate if needed
3. **Pagination**: Use pagination for large datasets to avoid timeouts
4. **Video Preloading**: Preload video URLs before playback to avoid expiry issues
5. **Caching**: Cache stage results; they don't change after processing completes
6. **Retry Logic**: Implement exponential backoff for 5xx errors

## Support

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Email**: support@jbi-api.local

## Changelog

### v1.0.0 (2026-04-08)
- Initial release
- Stage Results API (Stage 1/2/3)
- Audit Log API
- Annotation Sync API
