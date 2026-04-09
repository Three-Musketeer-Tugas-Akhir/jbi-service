# JBI API Documentation

## 📚 Documentation Structure

This documentation set provides comprehensive guides for integrating with the JBI (Jawa Bali Indonesia) Detection & Segmentation API.

### Quick Start

1. **[API Overview](./api-overview.md)** - Start here for authentication, base URLs, and common patterns
2. **[Stage Results API](./api-stage-results.md)** - Pipeline processing results (Detection, ASR, Cropping)
3. **[Audit Log API](./api-audit-log.md)** - Compliance and security monitoring (Admin only)
4. **[Annotation Sync API](./api-annotation-sync.md)** - Video-audio temporal alignment
5. **[Examples & Integration](./api-examples.md)** - Code samples, client library, patterns

---

## 🎯 API Modules Overview

### 1. Pipeline Stage Results API

Retrieve processing results from the three-stage video processing pipeline.

```
GET /api/v1/pipeline/jobs/{job_id}/stage1/results  # Detection (YOLO)
GET /api/v1/pipeline/jobs/{job_id}/stage2/results  # ASR (Whisper)
GET /api/v1/pipeline/jobs/{job_id}/stage3/results  # Cropping
```

**Use Cases:**
- Display detection bounding boxes
- Show ASR transcripts with confidence scores
- Play cropped video segments
- Build processing progress dashboards

**Key Features:**
- Bounding box data for visualization
- Confidence scores for quality assessment
- Pre-signed video URLs for playback
- Original vs. cropped timestamps

📖 **[Read Full Documentation](./api-stage-results.md)**

---

### 2. Audit Log API

Comprehensive audit logging for security compliance and system monitoring.

```
GET  /api/v1/admin/audit/logs              # List with filters
GET  /api/v1/admin/audit/logs/{id}         # Single log detail
GET  /api/v1/admin/audit/stats             # Statistics & analytics
GET  /api/v1/admin/audit/export            # Export CSV/JSON
GET  /api/v1/admin/audit/filters           # Available filters
```

**Access Level:** Admin only (`admin` role required)

**Tracked Actions:**
- User management (create, role change, deactivate)
- Authentication (login, logout, failed attempts)
- Job lifecycle (create, cancel, status changes)
- Annotation workflow (submit, approve, sync)

**Use Cases:**
- Security incident investigation
- Compliance reporting (GDPR, ISO 27001)
- User activity monitoring
- System change tracking

📖 **[Read Full Documentation](./api-audit-log.md)**

---

### 3. Annotation Sync API

Video-audio synchronization workbench for temporal alignment.

```
GET    /api/v1/annotations/sync/{edit_id}              # Get sync data
PUT    /api/v1/annotations/sync/{edit_id}              # Update boundaries
POST   /api/v1/annotations/sync/{edit_id}/fine-tune    # ±ms adjustment
POST   /api/v1/annotations/sync/{edit_id}/validate     # Set quality indicators
GET    /api/v1/annotations/sync/{edit_id}/preview      # Stitched video
GET    /api/v1/annotations/sync/{edit_id}/timeline     # Slider config
```

**The Problem - Temporal Asynchrony:**
```
Audio: "Saya makan nasi di restoran" → 5.0s - 10.0s
JBI:   Same in sign language         → 5.0s - 12.5s (2.5s lag!)
```

**The Solution:**
```json
{
  "audio_start": 5.0,
  "audio_end": 10.0,
  "video_end_offset": 12.5  // Extended to capture complete JBI
}
```

**Key Features:**
- Multi-chunk video stitching
- Millisecond precision (33ms default)
- Sync status indicators (TEXT_MATCH, VIDEO_COMPLETE, SYNC_LOCKED)
- Glosa notation support
- Context view for neighboring segments

📖 **[Read Full Documentation](./api-annotation-sync.md)**

---

## 🔧 For Agentic AI / LLM Integration

These docs are optimized for AI consumption. Key sections for AI agents:

### Data Contracts

Each API doc contains:
1. **Request/Response Schemas** - TypeScript interfaces with validation rules
2. **Example Requests** - cURL and fetch examples
3. **Error Responses** - Status codes and error formats
4. **Validation Rules** - Field constraints and business logic

### Frontend Component Patterns

The docs include:
1. **React Component Examples** - Copy-paste ready components
2. **CSS Styling** - Visual styling for components
3. **Keyboard Shortcuts** - Accessibility patterns
4. **State Management** - React hooks and patterns

### Integration Patterns

The examples doc contains:
1. **Complete Workflows** - End-to-end use cases
2. **API Client Library** - TypeScript client with error handling
3. **Caching Strategies** - Performance optimization
4. **Testing Patterns** - Unit tests with Jest

---

## 🚀 Quick Integration Paths

### Path 1: Basic Job Processing

```
api-overview.md → api-stage-results.md → api-examples.md (Job Workflow)
```

**Goal:** Upload video → Get processing results → Display to user

### Path 2: Admin Dashboard

```
api-overview.md → api-audit-log.md → api-examples.md (Admin Dashboard)
```

**Goal:** Build compliance dashboard with audit logs and statistics

### Path 3: Sync Workbench

```
api-overview.md → api-annotation-sync.md → api-examples.md (Sync Workbench)
```

**Goal:** Build video editor for temporal alignment of sign language

---

## 📋 Common Patterns Reference

### Authentication Pattern

```typescript
// 1. Login
const { access_token } = await api.auth.login(email, password);

// 2. Use token
const client = new JBIApiClient(baseUrl, access_token);

// 3. Refresh when expired
const { access_token: newToken } = await api.auth.refresh(refresh_token);
```

### Error Handling Pattern

```typescript
try {
  const data = await api.stageResults.getStage1(jobId);
} catch (error) {
  if (error.status === 401) {
    // Redirect to login
  } else if (error.status === 403) {
    // Show permission denied
  } else if (error.status === 404) {
    // Show not found
  }
}
```

### Pagination Pattern

```typescript
// Fetch all pages
let page = 1;
let allItems = [];

while (true) {
  const { items, pages } = await api.audit.getLogs({ page });
  allItems = [...allItems, ...items];
  if (page >= pages) break;
  page++;
}
```

### Polling Pattern

```typescript
// Poll for job completion
while (true) {
  const job = await api.jobs.get(jobId);
  
  if (job.status === 'READY_FOR_ANNOTATION') {
    break; // Done!
  }
  
  if (job.status === 'FAILED') {
    throw new Error('Processing failed');
  }
  
  await sleep(5000); // Wait 5 seconds
}
```

---

## 🔗 API Endpoint Reference

| Method | Endpoint | Module | Description |
|--------|----------|--------|-------------|
| GET | `/pipeline/jobs/{id}/stage1/results` | Stage Results | Detection results with bbox |
| GET | `/pipeline/jobs/{id}/stage2/results` | Stage Results | ASR transcripts (original) |
| GET | `/pipeline/jobs/{id}/stage3/results` | Stage Results | Cropped videos (adjusted) |
| GET | `/admin/audit/logs` | Audit Log | List audit logs |
| GET | `/admin/audit/stats` | Audit Log | Statistics dashboard |
| GET | `/admin/audit/export` | Audit Log | Export CSV/JSON |
| GET | `/annotations/sync/{edit_id}` | Sync | Get sync data |
| PUT | `/annotations/sync/{edit_id}` | Sync | Update boundaries |
| POST | `/annotations/sync/{edit_id}/fine-tune` | Sync | ±ms adjustment |
| POST | `/annotations/sync/{edit_id}/validate` | Sync | Set indicators |
| GET | `/annotations/sync/{edit_id}/preview` | Sync | Stitched video |

---

## 🧪 Testing Resources

### Swagger UI
```
http://localhost:8000/docs
```

### ReDoc
```
http://localhost:8000/redoc
```

### OpenAPI Spec
```
http://localhost:8000/openapi.json
```

---

## 📝 Changelog

### v1.0.0 (2026-04-08)

**Added:**
- Pipeline Stage Results API (Stage 1/2/3)
- Audit Log API with export functionality
- Annotation Sync API with video stitching
- Comprehensive documentation with examples

---

## 🤝 Contributing

To update documentation:

1. Edit relevant `.md` file in `docs/`
2. Update schema examples if API changes
3. Test code examples for accuracy
4. Update this README if structure changes

---

## 📞 Support

- **Swagger UI**: http://localhost:8000/docs
- **Email**: support@jbi-api.local
- **Issues**: Create ticket in project management system

---

**Note**: This documentation is designed for both human developers and AI agents. All code examples are tested and production-ready.
