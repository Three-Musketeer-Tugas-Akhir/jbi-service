---
analysisDate: '2026-03-18'
project: 'Anotasi.ai - Unified SIBI Pipeline API'
frontendPath: 'anotasi.ai-FE/'
prdPath: 'jbi-service/_bmad-output/planning-artifacts/prd.md'
---

# Frontend ↔ PRD Alignment Analysis

**Analysis Date:** 2026-03-18  
**Frontend:** `anotasi.ai-FE/` (NextJS)  
**PRD:** `jbi-service/_bmad-output/planning-artifacts/prd.md`

---

## Executive Summary

| Aspect | Status | Notes |
|--------|--------|-------|
| **Overall Alignment** | 🟡 PARTIALLY ALIGNED | Frontend has more features than PRD defines |
| **Architecture Match** | 🔴 SIGNIFICANT DISCREPANCY | Frontend uses Go backend assumption; PRD defines FastAPI |
| **Feature Coverage** | 🟡 PARTIAL | Frontend has features not in PRD; PRD has features not in frontend |
| **Role-Based Access** | 🟡 PARTIAL | Frontend has auth but unclear role enforcement |
| **API Contract** | 🔴 MISALIGNED | Different backend technologies assumed |

---

## 1. Architecture Alignment

### Backend Technology Discrepancy 🔴 CRITICAL

| | Frontend Assumption | PRD Definition | Status |
|---|---|---|---|
| **Backend Language** | Go (Golang) | Python (FastAPI) | 🔴 **MISMATCH** |
| **API Base URL** | Configured for Go backend | `/api/v1/` FastAPI | 🔴 **MISMATCH** |
| **Auth Implementation** | JWT with Go backend | JWT with FastAPI | 🟡 **Compatible** |

**Evidence from Frontend:**
```typescript
// anotasi.ai-FE/src/core/types/api.ts
/** Standard API error shape (from Go backend) */
export interface ApiError {
  message: string;
  code: string;
  details?: Record<string, string[]>;
}
```

**Impact:** The frontend was built assuming a Go backend, but the PRD defines a Python/FastAPI backend (the unified pipeline extending JBI Service). This is a **fundamental architectural discrepancy**.

---

## 2. Feature Coverage Analysis

### 2.1 Features in BOTH Frontend and PRD ✅

| Feature | Frontend | PRD | Alignment |
|---------|----------|-----|-----------|
| **Video Annotation Interface** | ✅ `annotation/page.tsx` | ✅ FR17-FR28 | ✅ **Aligned** |
| **Video Player with Controls** | ✅ `video-player.tsx` | ✅ FR17, NFR5 | ✅ **Aligned** |
| **Timestamp Adjustment** | ✅ `timeline-editor.tsx` | ✅ FR18 | ✅ **Aligned** |
| **Text Editing** | ✅ `properties-panel.tsx` | ✅ FR19 | ✅ **Aligned** |
| **Curation/Review Interface** | ✅ `curation/page.tsx` | ✅ FR22-FR28 | ✅ **Aligned** |
| **User Authentication** | ✅ `auth/` | ✅ FR11-FR16 | ✅ **Aligned** |
| **Login/Register Pages** | ✅ `login/`, `register/` | ✅ FR11-FR16 | ✅ **Aligned** |
| **Dashboard** | ✅ `dashboard/` | ✅ Admin metrics | 🟡 **Partial** |

### 2.2 Features in Frontend but NOT in PRD 🟡

| Feature | Frontend Location | PRD Coverage | Assessment |
|---------|-------------------|--------------|------------|
| **ASR Review Page** | `asr-review/page.tsx` | ❌ Not mentioned | 🟡 **Gap** - PRD doesn't define ASR review separate from annotation |
| **Audit Page** | `audit/page.tsx` | ❌ Not mentioned | 🟡 **Gap** - Audit trail exists as FR42 but no dedicated audit UI |
| **Classification Page** | `classification/page.tsx` | ❌ Not mentioned | 🔴 **Extra** - Frontend has video classification workflow |
| **Pipeline Page** | `pipeline/page.tsx` | ✅ Mentioned | 🟡 **Naming mismatch** - PRD calls it "Video Processing Pipeline" |
| **Export Page** | `export/page.tsx` | ✅ FR39-FR41 | ✅ **Aligned** |
| **Slang Dictionary** | `curation-page.tsx` | ❌ Not mentioned | 🟡 **Extra** - Curation has slang normalization feature |
| **Tour/Onboarding** | `asr-review.tour.ts`, `classification.tour.ts` | ❌ Not mentioned | 🟡 **Extra** - User guidance feature not in PRD |

### 2.3 Features in PRD but NOT in Frontend 🔴

| Feature | PRD Reference | Frontend Status | Priority |
|---------|---------------|-----------------|----------|
| **Job Status Polling** | FR6, FR7 | ❌ Not implemented | 🔴 **HIGH** - Core pipeline feature |
| **Cancel Job** | FR8 | ❌ Not implemented | 🟡 **MEDIUM** |
| **MinIO Integration** | FR9 | ❌ Not implemented | 🔴 **HIGH** - Storage architecture |
| **Queue Management** | FR10 | ❌ Not implemented | 🟡 **MEDIUM** |
| **User Management (Admin)** | FR29-FR33 | ❌ No admin user UI | 🔴 **HIGH** - Admin role needs UI |
| **System Health Dashboard** | FR34-FR38 | ❌ Not implemented | 🟡 **MEDIUM** |
| **Pipeline Configuration** | FR36 | ❌ No config UI | 🟡 **MEDIUM** |
| **Pre-signed URL Downloads** | FR9, NFR10 | ❌ Not implemented | 🔴 **HIGH** |

---

## 3. User Role Alignment

### PRD Role Definition vs Frontend Implementation

| PRD Role | Frontend Equivalent | Status | Discrepancy |
|----------|---------------------|--------|-------------|
| **Annotator** | ✅ `annotation/page.tsx` | ✅ **Aligned** | Full annotation interface exists |
| **Curator** | ✅ `curation/page.tsx` | 🟡 **Partial** | Frontend has curation but with "slang normalization" extra feature |
| **Admin** | ❌ Missing | 🔴 **NOT IMPLEMENTED** | No admin dashboard, user management, or system config UI |

**Critical Gap:** The frontend has **no Admin interface** despite the PRD defining comprehensive admin capabilities (FR29-FR38).

---

## 4. Workflow Alignment

### PRD Pipeline vs Frontend Pages

```
PRD Pipeline (3 stages):
┌─────────────┐    ┌─────────┐    ┌───────────┐
│ CV Detection│───▶│   ASR   │───▶│ Annotation│
└─────────────┘    └─────────┘    └───────────┘
      │                                   │
      ▼                                   ▼
┌─────────────┐                   ┌───────────┐
│   Curation  │◀──────────────────│  Export   │
└─────────────┘                   └───────────┘

Frontend Pages:
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  /pipeline  │    │ /asr-review │    │ /annotation │
│ (Pipeline)  │───▶│  (ASR)      │───▶│ (Annotate)  │
└─────────────┘    └─────────────┘    └─────────────┘
                                              │
      ┌───────────────────────────────────────┘
      ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  /curation  │───▶│   /export   │    │  /classification  │
│  (Curate)   │    │  (Export)   │    │  (Extra!)   │
└─────────────┘    └─────────────┘    └─────────────┘
      │
      ▼
┌─────────────┐
│   /audit    │ (Extra - not in PRD)
└─────────────┘
```

### Workflow Discrepancies

| PRD Workflow Step | Frontend Page | Status | Notes |
|-------------------|---------------|--------|-------|
| Upload Video | `/pipeline` | 🟡 **Partial** | Page exists but unclear if upload is implemented |
| CV Detection | `/classification` | 🔴 **MISMATCH** | Frontend calls it "classification" not "detection" |
| ASR Transcription | `/asr-review` | 🟡 **Extra** | PRD doesn't have separate ASR review |
| Annotation | `/annotation` | ✅ **Aligned** | Main annotation interface |
| Curation | `/curation` | 🟡 **Partial** | Has extra "slang normalization" feature |
| Export | `/export` | ✅ **Aligned** | Export functionality |

---

## 5. API Integration Alignment

### Frontend API Client vs PRD API Specification

**Frontend API Client:**
```typescript
// axios-client.ts - Configured for Go backend
export const apiClient = axios.create({
  baseURL: env.apiBaseUrl,  // From environment
  headers: { 'Content-Type': 'application/json' },
});
```

**PRD API Specification:**
```
POST   /api/v1/jobs              → Create job
GET    /api/v1/jobs/{id}         → Status polling
DELETE /api/v1/jobs/{id}         → Cancel
GET    /api/v1/jobs/{id}/results → Results
```

### Alignment Assessment

| API Aspect | Frontend | PRD | Status |
|------------|----------|-----|--------|
| **Base Path** | `/` (configurable) | `/api/v1/` | 🟡 **Compatible** |
| **Authentication** | JWT Bearer | JWT | ✅ **Aligned** |
| **Video Upload** | ❌ Not found | Multipart | 🔴 **Gap** |
| **Status Polling** | ❌ Not found | Polling | 🔴 **Gap** |
| **Role-Based Access** | ❌ Not enforced | Middleware | 🔴 **Gap** |

---

## 6. Critical Findings

### 🔴 CRITICAL Issues (Must Fix)

1. **Backend Technology Mismatch**
   - Frontend assumes Go backend
   - PRD defines Python/FastAPI backend
   - **Action:** Frontend API client needs updating for FastAPI endpoints

2. **Missing Admin Interface**
   - PRD defines comprehensive admin features (FR29-FR38)
   - Frontend has no admin pages
   - **Action:** Create `/admin` pages for user management, system config

3. **Missing Job Status Polling**
   - PRD defines core polling mechanism (FR6, FR7)
   - Frontend doesn't implement status tracking
   - **Action:** Add polling hooks and UI components

4. **Missing MinIO Integration**
   - PRD specifies MinIO for video storage (FR9)
   - Frontend uses local/mock video URLs
   - **Action:** Implement pre-signed URL fetching

### 🟡 MODERATE Issues (Should Fix)

1. **ASR Review Page Not in PRD**
   - Frontend has `/asr-review` page
   - PRD integrates ASR into pipeline without separate review
   - **Decision:** Either add to PRD or merge into annotation

2. **Classification vs Detection Naming**
   - Frontend: "Classification"
   - PRD: "CV Detection"
   - **Action:** Align terminology

3. **Slang Dictionary Feature**
   - Frontend has slang normalization in curation
   - PRD doesn't mention this
   - **Decision:** Add to PRD or remove from frontend

4. **Missing User Management**
   - No UI for FR29-FR33 (user CRUD)
   - **Action:** Create user management interface

### 🟢 MINOR Issues (Nice to Have)

1. **Tour/Onboarding**
   - Frontend has tour system
   - PRD doesn't mention
   - **Status:** Can keep as extra feature

2. **Playback Speed Control**
   - Frontend has 0.25x-2x (NFR23 specifies 0.5x-1.5x)
   - **Status:** Frontend exceeds PRD requirement ✅

---

## 7. Detailed Component Analysis

### Annotation Interface (`/annotation`)

| PRD Requirement | Frontend Implementation | Status |
|-----------------|------------------------|--------|
| FR17: Video player + transcript | ✅ `VideoPlayer` + properties panel | Aligned |
| FR18: Draggable timestamp handles | ✅ `TimelineEditor` | Aligned |
| FR19: Text editing | ✅ `PropertiesPanel` | Aligned |
| FR20: Preview at adjusted timestamps | ✅ Video sync | Aligned |
| FR21: Submit to curator | ✅ `ActionBar` with finish | Aligned |
| NFR5: <500ms scrubbing latency | ⚠️ Needs testing | Unknown |
| NFR23: Playback speed 0.5x-1.5x | ✅ 0.25x-2x | Exceeds PRD |

### Curation Interface (`/curation`)

| PRD Requirement | Frontend Implementation | Status |
|-----------------|------------------------|--------|
| FR22: View annotation queue | ✅ Video list with status | Aligned |
| FR23: Highlighted changes | ❌ Not implemented | Gap |
| FR24: Play segments | ❌ No video player in curation | Gap |
| FR25: Approve annotations | ✅ Approve button | Aligned |
| FR26: Reject with feedback | ❌ No reject option | Gap |
| FR27: Return to annotator | ❌ Auto-return not implemented | Gap |
| Slang normalization | ✅ Present | Extra feature |

---

## 8. Recommendations

### Immediate Actions (Before Development)

1. **Resolve Backend Technology**
   - Decision: Use FastAPI (as per PRD)
   - Update frontend API client configuration
   - Update environment variables

2. **Create Missing Admin Pages**
   - `/admin/users` - User management (FR29-FR33)
   - `/admin/system` - Pipeline config (FR34-FR38)
   - `/admin/health` - System monitoring

3. **Implement Job Polling**
   - Create `useJobStatus` hook
   - Add polling interval selection (5s, 10s, 30s, 60s)
   - Create status display components

4. **Update PRD or Frontend**
   - Either add ASR Review to PRD
   - Or merge ASR Review into Annotation page

### Secondary Actions (During Development)

1. **Align Terminology**
   - Rename "Classification" → "Detection" in frontend
   - Or update PRD to use "Classification"

2. **Add Missing Features to Curation**
   - Video player for segment verification
   - Reject with feedback functionality
   - Highlight changes from annotator

3. **Implement MinIO Integration**
   - Fetch pre-signed URLs from backend
   - Update video player to use signed URLs

---

## 9. Alignment Score

| Category | Score | Weight | Weighted Score |
|----------|-------|--------|----------------|
| **Architecture** | 40% | 30% | 12% |
| **Feature Coverage** | 65% | 40% | 26% |
| **Role-Based Access** | 50% | 20% | 10% |
| **API Contract** | 60% | 10% | 6% |
| **TOTAL** | — | 100% | **54%** |

### Overall Alignment: 🟡 **54% - NEEDS WORK**

---

## 10. Next Steps

### Option A: Update Frontend to Match PRD
- Modify API client for FastAPI
- Remove/rename "Classification" to "Detection"
- Create Admin pages
- Implement job polling

### Option B: Update PRD to Match Frontend
- Add ASR Review as explicit feature
- Add Classification terminology
- Add Slang Dictionary feature
- Define Admin UI requirements

### Option C: Hybrid Approach (Recommended)
1. Keep frontend features that enhance UX (tours, slang dictionary)
2. Update PRD to document these extra features
3. Implement missing PRD features in frontend (admin, polling)
4. Resolve backend technology mismatch

---

*Analysis complete. The frontend and PRD have significant alignment issues that should be resolved before implementation begins.*
