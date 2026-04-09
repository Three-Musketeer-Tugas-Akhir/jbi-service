# Annotation Queue API Changes - `edit_id` Support

> **Date:** April 9, 2026  
> **Author:** Backend Team  
> **Target Audience:** Frontend Developers & AI Agents  
> **API Version:** v1.0.0+

---

## 🎯 Summary

The `GET /api/v1/annotations/queue` endpoint now returns **active edit information** for each queue item, enabling the frontend to:

- Show **"Continue Draft"** vs **"Start New"** indicators
- Display **work status badges** (Draft, Submitted, etc.)
- Skip redundant API calls to fetch edit details
- Implement **batch operations** from the queue view

---

## 📡 API Endpoint

```http
GET /api/v1/annotations/queue
Authorization: Bearer <jwt_token>
```

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | - | Filter by status: `ASSIGNED`, `IN_PROGRESS`, `COMPLETED` |
| `page` | integer | 1 | Page number (1-based) |
| `page_size` | integer | 20 | Items per page (1-100) |

---

## 📋 Response Schema Changes

### Before (Legacy Response)

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "segment_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "job_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "original_filename": "berita_jbi_2024.mp4",
      "video_preview_url": "https://minio/...",
      "status": "IN_PROGRESS",
      "priority": 1,
      "assigned_at": "2026-04-09T10:00:00Z",
      "transcript_text": "Pemerintah mengumumkan...",
      "asr_confidence": 0.95
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

### After (Current Response with `edit_id`)

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "segment_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "job_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "original_filename": "berita_jbi_2024.mp4",
      "video_preview_url": "https://minio/...",
      "status": "IN_PROGRESS",
      "priority": 1,
      "assigned_at": "2026-04-09T10:00:00Z",
      "transcript_text": "Pemerintah mengumumkan...",
      "asr_confidence": 0.95,
      
      "⭐ NEW FIELDS ⭐": "",
      "edit_id": "6ba7b811-9dad-11d1-80b4-00c04fd430c9",
      "edit_status": "DRAFT",
      "has_active_work": true,
      "last_edited_at": "2026-04-09T11:30:00Z"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

---

## 🆕 New Fields Explained

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `edit_id` | UUID | ✅ Yes | The **latest active edit** ID for this segment. Returns `DRAFT`, `PENDING`, or `SUBMITTED` edits only. Null if no active work or only `APPROVED`/`REJECTED` edits exist. |
| `edit_status` | string | ✅ Yes | Status of the active edit: `"DRAFT"`, `"PENDING"`, `"SUBMITTED"`, or `null`. |
| `has_active_work` | boolean | ❌ No | Convenience flag. `true` if there's an active edit (DRAFT/PENDING/SUBMITTED). Use this for quick UI decisions. |
| `last_edited_at` | datetime | ✅ Yes | ISO 8601 timestamp of when the edit was last modified. Useful for sorting by recent activity. |

### Why These Fields?

**Option B Implementation:** We return the **latest active edit** (excluding APPROVED/REJECTED) because:
- ✅ Shows work-in-progress that needs attention
- ✅ Excludes completed/archived edits
- ✅ Aligns with annotator workflow (continue working vs start fresh)

---

## 🎨 Frontend Implementation Guide

### 1. Queue Item Status Badge

```typescript
// React/TypeScript Example
interface QueueItem {
  segment_id: string;
  edit_id: string | null;
  edit_status: 'DRAFT' | 'PENDING' | 'SUBMITTED' | null;
  has_active_work: boolean;
  last_edited_at: string | null;
  // ... other fields
}

const getStatusBadge = (item: QueueItem) => {
  if (!item.has_active_work) {
    return { label: 'NEW', color: 'green', icon: '🆕' };
  }
  
  switch (item.edit_status) {
    case 'DRAFT':
      return { label: 'DRAFT', color: 'orange', icon: '✏️' };
    case 'PENDING':
      return { label: 'PENDING', color: 'yellow', icon: '⏸️' };
    case 'SUBMITTED':
      return { label: 'SUBMITTED', color: 'blue', icon: '⏳' };
    default:
      return { label: 'UNKNOWN', color: 'gray', icon: '❓' };
  }
};
```

### 2. Action Button Logic

```typescript
const getActionButton = (item: QueueItem) => {
  // No active work → Start fresh
  if (!item.has_active_work) {
    return (
      <Button variant="primary" onClick={() => startAnnotation(item.segment_id)}>
        🎬 Start Annotation
      </Button>
    );
  }
  
  // Has draft → Continue editing
  if (item.edit_status === 'DRAFT') {
    return (
      <Button 
        variant="warning" 
        onClick={() => continueEditing(item.segment_id, item.edit_id!)}
      >
        ✏️ Continue Draft
      </Button>
    );
  }
  
  // Submitted → Show review status
  if (item.edit_status === 'SUBMITTED') {
    return (
      <Button variant="info" disabled>
        ⏳ Under Review
      </Button>
    );
  }
  
  // Pending → Resume pending work
  if (item.edit_status === 'PENDING') {
    return (
      <Button variant="secondary" onClick={() => resumeWork(item.segment_id)}>
        ⏸️ Resume
      </Button>
    );
  }
};
```

### 3. Navigation to Annotation Editor

```typescript
// Direct navigation using edit_id from queue
const navigateToEditor = (item: QueueItem) => {
  if (item.edit_id) {
    // Has existing edit → go directly to sync/edit page
    router.push(`/annotation/${item.segment_id}/sync?edit_id=${item.edit_id}`);
  } else {
    // New annotation → go to annotation interface
    router.push(`/annotation/${item.segment_id}`);
  }
};
```

### 4. Sort/Filter by Work Status

```typescript
// Sort queue items by activity
const sortByLastEdited = (items: QueueItem[]) => {
  return items.sort((a, b) => {
    // Items with recent edits first
    if (a.last_edited_at && b.last_edited_at) {
      return new Date(b.last_edited_at).getTime() - new Date(a.last_edited_at).getTime();
    }
    // Items with any work before items without work
    if (a.has_active_work && !b.has_active_work) return -1;
    if (!a.has_active_work && b.has_active_work) return 1;
    return 0;
  });
};

// Filter to show only drafts
const draftsOnly = items.filter(item => item.edit_status === 'DRAFT');

// Filter to show only unsubmitted work
const needsSubmission = items.filter(item => 
  item.edit_status === 'DRAFT' || item.edit_status === 'PENDING'
);
```

### 5. Batch Operations (Advanced)

```typescript
// Submit all drafts from queue
const submitAllDrafts = async (items: QueueItem[]) => {
  const draftItems = items.filter(item => item.edit_status === 'DRAFT');
  
  for (const item of draftItems) {
    await api.post(`/annotations/${item.segment_id}/submit`, {
      confirm_no_changes: false
    });
  }
  
  // Refresh queue after batch submission
  await refreshQueue();
};
```

---

## 🔄 State Transitions Reference

```
┌─────────────────────────────────────────────────────────────────┐
│  NEW ASSIGNMENT                                                 │
│  ├─ edit_id: null                                               │
│  ├─ edit_status: null                                           │
│  └─ has_active_work: false                                      │
│     ↓ (annotator starts working)                                │
│  DRAFT CREATED                                                  │
│  ├─ edit_id: "uuid"                                             │
│  ├─ edit_status: "DRAFT"                                        │
│  └─ has_active_work: true                                       │
│     ↓ (annotator submits)                                       │
│  SUBMITTED                                                      │
│  ├─ edit_id: "uuid"                                             │
│  ├─ edit_status: "SUBMITTED"                                    │
│  └─ has_active_work: true                                       │
│     ↓ (curator reviews)                                         │
│  APPROVED / REJECTED                                            │
│  ├─ edit_id: null  ← cleared from queue                         │
│  ├─ edit_status: null                                           │
│  └─ has_active_work: false                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚠️ Important Notes

### 1. `edit_id` Can Be Null

Always check `has_active_work` or `edit_id` before using it:

```typescript
// ✅ Good
if (item.edit_id) {
  await api.get(`/annotations/sync/${item.edit_id}`);
}

// ❌ Bad - will cause 404 if edit_id is null
await api.get(`/annotations/sync/${item.edit_id}`);
```

### 2. Status Can Change

The queue data is cached. If the annotator is actively working:
- The `edit_status` might change (DRAFT → SUBMITTED)
- A new `edit_id` might be created
- Always handle 404 errors gracefully and refresh the queue

### 3. Permission-Based Visibility

The queue only returns segments **assigned to the current user** (or all segments for admin). The `edit_id` returned is always for that user's edits.

---

## 🐛 Common Issues & Solutions

### Issue: `edit_id` exists but API returns 404

**Cause:** Edit was deleted or status changed to APPROVED/REJECTED  
**Solution:** Refresh the queue and handle gracefully

```typescript
try {
  await api.get(`/annotations/sync/${edit_id}`);
} catch (error) {
  if (error.status === 404) {
    // Edit no longer exists, refresh queue
    await refreshQueue();
    showToast('Work status changed. Refreshing...');
  }
}
```

### Issue: `last_edited_at` sorting seems wrong

**Cause:** Timezone handling  
**Solution:** Ensure proper ISO 8601 parsing

```typescript
const date = new Date(item.last_edited_at); // Auto-parses ISO 8601
// Or use date-fns
import { parseISO } from 'date-fns';
const date = parseISO(item.last_edited_at);
```

---

## 🔗 Related Endpoints

| Endpoint | Description | Uses `edit_id`? |
|----------|-------------|-----------------|
| `GET /annotations/queue` | Get annotator's queue | Returns `edit_id` |
| `GET /annotations/segments/{id}` | Get segment details | Returns `edit_history` with all `edit_id`s |
| `POST /annotations/{segment_id}/draft` | Save draft | Returns `edit_id` |
| `POST /annotations/{segment_id}/submit` | Submit for review | Returns `edit_id` |
| `GET /annotations/sync/{edit_id}` | Get sync data | Requires `edit_id` |
| `PUT /annotations/sync/{edit_id}` | Update sync | Requires `edit_id` |
| `POST /annotations/sync/{edit_id}/fine-tune` | Fine-tune | Requires `edit_id` |

---

## 📱 Example: Complete Queue Item Component

```tsx
// QueueItem.tsx
import React from 'react';
import { formatDistanceToNow } from 'date-fns';

interface QueueItemProps {
  item: QueueItem;
  onClick: () => void;
}

export const QueueItemCard: React.FC<QueueItemProps> = ({ item, onClick }) => {
  const getStatusConfig = () => {
    if (!item.has_active_work) {
      return { 
        badge: '🆕 NEW', 
        color: 'bg-green-100 text-green-800',
        action: 'Start Annotation'
      };
    }
    switch (item.edit_status) {
      case 'DRAFT':
        return { 
          badge: '✏️ DRAFT', 
          color: 'bg-orange-100 text-orange-800',
          action: 'Continue Editing'
        };
      case 'SUBMITTED':
        return { 
          badge: '⏳ SUBMITTED', 
          color: 'bg-blue-100 text-blue-800',
          action: 'View Status'
        };
      default:
        return { 
          badge: '❓ UNKNOWN', 
          color: 'bg-gray-100 text-gray-800',
          action: 'Open'
        };
    }
  };

  const config = getStatusConfig();

  return (
    <div 
      className="border rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer"
      onClick={onClick}
    >
      {/* Header */}
      <div className="flex justify-between items-start mb-2">
        <h3 className="font-semibold text-lg truncate">
          {item.original_filename}
        </h3>
        <span className={`px-2 py-1 rounded text-sm ${config.color}`}>
          {config.badge}
        </span>
      </div>

      {/* Metadata */}
      <div className="text-sm text-gray-600 space-y-1">
        <p>Priority: {item.priority}</p>
        <p>Assigned: {formatDistanceToNow(new Date(item.assigned_at))} ago</p>
        {item.last_edited_at && (
          <p>Last edited: {formatDistanceToNow(new Date(item.last_edited_at))} ago</p>
        )}
      </div>

      {/* Preview */}
      {item.video_preview_url && (
        <video 
          src={item.video_preview_url} 
          className="w-full h-32 object-cover rounded mt-3"
          muted
        />
      )}

      {/* Action Button */}
      <button className="mt-3 w-full bg-blue-500 text-white py-2 rounded hover:bg-blue-600">
        {config.action}
      </button>
    </div>
  );
};
```

---

## 📝 Changelog

| Date | Change | Commit |
|------|--------|--------|
| 2026-04-09 | Added `edit_id`, `edit_status`, `has_active_work`, `last_edited_at` to queue response | `a7c02dd` |

---

## 💬 Questions?

Contact: Backend Team (`jbi-service` repo)  
API Docs: http://152.118.31.36:8000/docs
