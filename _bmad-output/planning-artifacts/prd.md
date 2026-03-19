---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-02b-vision
  - step-02c-executive-summary
  - step-03-success
  - step-04-journeys
  - step-05-domain
  - step-06-innovation
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
inputDocuments:
  - path: jbi-service/docs/prd.md
    type: existing-prd
    loaded: true
  - path: jbi-service/README.md
    type: project-documentation
    loaded: true
  - path: asr_code.ipynb
    type: research-notebook
    loaded: false
  - path: cv_asr_annotation.ipynb
    type: research-notebook
    loaded: false
workflowType: prd
documentCounts:
  productBriefs: 0
  researchDocs: 0
  projectDocs: 2
  brainstormingDocs: 0
projectType: brownfield-unified-pipeline
frontendAligned: true
algorithmAligned: true
alignmentDate: '2026-03-18'
algorithmSource:
  - asr_code.ipynb
  - cv_asr_annotation.ipynb
  - jbi-service/VideoDetector3.ipynb
classification:
  projectType: API + Web Application (Full-stack annotation platform)
  domain: Accessibility / Sign Language Technology (SIBI)
  complexity: High
  projectContext: brownfield-evolution
  users:
    primary: LBI (Lembaga Bahasa Isyarat)
    roles: [admin, annotator, curator]
  frontend: NextJS (anotasi.ai-FE/)
  technical:
    communication: Polling (REST API)
    metadata_storage: Database (hidden from UI)
    annotation_features: [text_editing, timestamp_adjustment]
---

# Product Requirements Document - Unified SIBI Pipeline API

**Author:** Arxeno
**Date:** 2026-03-18 (Updated with Frontend & Algorithm Alignment)

---

> ## ⚠️ CRITICAL IMPLEMENTATION NOTE
> 
> **All algorithms, models, and processing flows defined in this PRD MUST follow the existing Python notebooks:**
> - `asr_code.ipynb` - ASR transcription pipeline using faster-whisper
> - `cv_asr_annotation.ipynb` - Video cropping and annotation generation
> - `jbi-service/VideoDetector3.ipynb` - CV Detection using YOLOv8 for JBI region detection
> 
> **Key Requirements:**
> 1. **ASR Model:** Use `faster-whisper` library (not OpenAI Whisper API)
> 2. **Two-Stage Cropping:** CV bbox crop → ASR timestamp crop with ±2s buffer
> 3. **JBI Time Range:** `max(0, asr_start - 2)` to `min(duration, asr_end + 2)`
> 4. **Output Format:** `segments.txt` with `[start -> end]` timestamps
> 5. **Directory Structure:** Follow notebook folder hierarchy
> 
> The backend is a **productionization** of these proven notebook workflows. Any deviation requires explicit approval.

---

## Executive Summary

**Anotasi.ai** is a unified, end-to-end sign language annotation platform that transforms how Lembaga Bahasa Isyarat (LBI) creates SIBI (Indonesian Sign Language) datasets. The platform integrates three previously disconnected ML pipelines—computer vision detection, automatic speech recognition, and annotation generation—into a single, cohesive REST API and web interface accessible to non-technical users.

**The Problem:** Current SIBI dataset creation requires running three separate Jupyter notebooks (CV Detection, ASR, CV ASR Annotation) that only AI engineers can operate. LBI annotators and curators—domain experts in sign language—cannot directly use these tools, creating a bottleneck where technical staff must mediate every dataset creation workflow.

**The Solution:** A unified pipeline where users upload news broadcast videos through a NextJS web interface, and the system automatically: (1) detects sign language interpreter regions using YOLOv8, (2) transcribes speech using Whisper, (3) generates synchronized video-transcript pairs, and (4) presents them in a video editing-like interface where annotators can correct text and adjust timestamps before curators approve the final dataset.

**Target Users:** LBI staff across three roles: **Admins** manage users and system configuration; **Annotators** review and fix synchronization between sign language video and transcripts; **Curators** approve final datasets for training use.

**Deployment Model:** FastAPI-based REST API with polling-based status tracking, PostgreSQL for metadata persistence, MinIO (S3-compatible) for video storage, and FFmpeg for video processing. Supports both CPU and GPU processing modes via Docker Compose profiles.

---

### What Makes This Special

**First End-to-End SIBI Platform in Indonesia:** While individual components (object detection, speech recognition) exist as open-source tools, no integrated solution exists specifically for Indonesian Sign Language dataset creation. The platform addresses SIBI-specific challenges including regional dialect variations in signing and Indonesian language speech patterns.

**Collaborative Workflow-First Design:** Unlike generic video annotation tools, the platform encodes the specific LBI workflow: CV detection identifies JBI (Juru Bahasa Isyarat) segments → ASR generates transcripts → Annotators fix sync issues → Curators approve. Role-based permissions enforce this workflow natively.

**Technical Non-Technical Bridge:** The platform hides ML complexity (bounding boxes, confidence scores, model parameters) from end users while preserving them in the database for technical staff. LBI experts interact only with the final cropped videos and editable transcripts—not notebooks or command lines.

---

## Project Classification

| Attribute | Value |
|-----------|-------|
| **Project Type** | API + Web Application (Full-stack annotation platform) |
| **Domain** | Accessibility / Sign Language Technology (SIBI) |
| **Complexity** | High (multi-stage ML pipeline, collaborative workflows, role-based access) |
| **Project Context** | Brownfield evolution (existing JBI Detection API being extended) |
| **Primary Users** | LBI (Lembaga Bahasa Isyarat) — Admin, Annotator, Curator roles |
| **Frontend Stack** | NextJS (`anotasi.ai-FE/`) |
| **API Communication** | Polling-based REST (WebSocket for future consideration) |
| **Annotation Features** | Text editing, timestamp adjustment, slang normalization, tour/onboarding |

---

## Success Criteria

### User Success

**Annotator Success:**
- Can upload a news video and receive synchronized video-transcript pairs without understanding ML, notebooks, or model parameters
- Can edit transcript text and adjust timestamps using an intuitive video editing-like interface
- Completes annotation task (fix sync issues) on a 5-minute segment within 10 minutes

**Curator Success:**
- Reviews and approves/rejects annotated segments with clear approve/reject workflow
- Tracks annotation quality through approval rate metrics
- Manages queue of pending annotations without technical intervention

**Admin Success:**
- Onboards new Annotators and Curators through role assignment
- Monitors system health and processing queue status
- Configures processing parameters (GPU/CPU, batch sizes) without code changes

### Business Success

**Primary Metric:** End-to-end workflow reliability
- 95% of uploaded videos complete full pipeline (CV Detection → ASR → Annotation Ready) without manual technical intervention
- Pipeline completion defined as: video processed, segments cropped, transcripts generated, and annotation interface ready for Annotator review

**Secondary Metrics:**
- Time-to-annotation: Video upload to Annotator-ready state within 3x video duration (e.g., 30-min video ready in 90 minutes)
- Annotator efficiency: Annotator completes review of 1-hour video content within 2 hours
- Zero notebook dependency: 100% of LBI staff can create datasets without AI engineer involvement

### Technical Success

**Pipeline Reliability:**
- CV Detection stage: Successfully processes 99% of valid video inputs (MP4, AVI, MKV, MOV)
- ASR stage: Successfully transcribes 95% of segments with detectable audio
- End-to-end job completion rate: 95% (accounting for corrupt uploads, unreadable audio, etc.)

**API Performance:**
- Upload endpoint responds within 2 seconds for files up to 2GB
- Status polling endpoint responds within 200ms
- Video download streams at consistent bitrate without interruption

**System Stability:**
- Background task workers process jobs concurrently (max 3 concurrent as per current config)
- Failed jobs are captured with error messages, don't block queue
- PostgreSQL database maintains job state consistency across API restarts

### Measurable Outcomes

**3-Month Success (MVP Validation):**
- 50+ news videos processed end-to-end through the platform
- 3+ LBI staff (1 Admin, 1+ Annotator, 1+ Curator) actively using the system
- Zero critical bugs blocking the core upload → detect → transcribe → annotate → approve workflow

**6-Month Success (Operational):**
- 200+ videos in production dataset
- Average annotation-to-approval cycle time under 48 hours
- Curator approval rate above 80% (indicating good ASR sync quality)

---

## Product Scope

### MVP - Minimum Viable Product

**Core Pipeline (Must Work):**
- Video upload via REST API (file or URL)
- CV Detection (YOLOv8) identifying JBI regions with ≥5 second minimum duration
- ASR transcription (Whisper) of detected segments
- Segment cropping with bounding box and audio preservation
- Polling-based status tracking for job progress

**Annotation Interface (Must Work):**
- Annotator view: Video player with synchronized transcript display
- Text editing: Correct transcript text (spelling, word errors)
- Timestamp adjustment: Move transcript start/end times to match sign language
- Save and submit for curation

**Curation Interface (Must Work):**
- Curator view: Queue of pending annotations
- Approve/Reject actions with optional feedback
- Approved segments exportable for dataset use

**User Management (Must Work):**
- Role-based access: Admin, Annotator, Curator
- Basic user onboarding and role assignment

### Growth Features (Post-MVP)

- Batch video upload (multiple files in one operation)
- Real-time collaboration (multiple annotators on same video)
- Advanced export formats (JSON, XML, custom formats)
- Quality metrics dashboard (annotator productivity, curator approval rates)
- ASR model fine-tuning interface for domain-specific vocabulary
- WebSocket real-time updates replacing polling
- Video preview before full processing (thumbnail generation)

### Vision (Future)

- Live stream processing (real-time news broadcast annotation)
- Multi-language support (regional Indonesian dialects, international sign languages)
- AI-assisted annotation suggestions (predictive text, auto-sync recommendations)
- Community dataset sharing between LBI institutions
- Mobile annotation app for tablet-based review
- Integration with SIBI learning platforms for educational use

---

## User Journeys

### Journey 1: The Annotator (Rina) - Success Path

**Persona:** Rina, 28, linguistics graduate, SIBI fluent, 2 years at LBI

**Current Pain:** Receives video segments and Excel files via shared drive. Must navigate Jupyter notebooks she doesn't understand to check timestamps, then manually document discrepancies in Word docs. Back-and-forth with engineers takes 3-4 days per batch.

**The Journey:**

1. **Monday Morning:** Rina logs into the Anotasi.ai web interface. Dashboard shows "3 videos pending annotation" with priority indicators.

2. **Selects First Video:** Clicks video title. Interface loads with video player on left, transcript panel on right. Status shows "CV Detection: Complete, ASR: Complete, Ready for Annotation."

3. **Identifies Sync Issue:** Sees transcript `[00:15:23] "Presiden mengadakan rapat..."` but the sign for "rapat" actually starts at 00:15:25. She clicks the timestamp—draggable handles appear.

4. **Adjusts Timing:** Drags start time handle to 00:15:25. Video preview updates instantly showing new sync point.

5. **Corrects Transcript Text:** Notices "rapat" should be "pertemuan" based on signing. Clicks text field, edits directly, hits Enter to save.

6. **Submits for Review:** Clicks "Submit for Curation." Video status changes to "Pending Review" and disappears from her queue. She begins next annotation.

7. **End of Day:** Dashboard shows "0 pending, 3 completed." She receives notification that Curator approved 2 of her annotations.

**Emotional Arc:** Frustration (waiting on engineers) → Empowerment (direct control) → Satisfaction (queue clearing) → Pride (quality approval).

**Critical Success Factors:** Intuitive video player, precise timestamp controls, immediate visual feedback, clear queue management.

---

### Journey 2: The Curator (Pak Budi) - Quality Assurance Path

**Persona:** Pak Budi, 45, senior LBI staff, 15 years experience, final dataset gatekeeper

**Current Pain:** Receives fragmented feedback via WhatsApp/email. "Video 3 has sync issues"—but where? Must open notebook outputs, compare with Annotator notes, manually compile decisions. No visibility into what Annotators changed.

**The Journey:**

1. **Tuesday Afternoon:** Pak Budi logs in, navigates to "Curation Queue." Sees 5 segments from Rina marked "Ready for Review."

2. **Reviews Segment #2:** Opens segment. Side-by-side view shows video player + transcript. Changes Rina made are highlighted: timestamp adjusted from 00:15:23→00:15:25, text changed "rapat"→"pertemuan."

3. **Plays Verification:** Clicks play. Watches sign language, reads transcript. Signs match perfectly. No issues detected.

4. **Approves:** Clicks green "Approve" button. Status changes to "Approved." Segment moves to "Exportable Dataset" bucket.

5. **Reviews Segment #3:** Plays clip. Notices ASR missed entire sentence at 00:22:15-00:22:45. Signs present, no transcript.

6. **Rejects with Feedback:** Clicks red "Reject" button. Modal opens. Types: "Missing transcript at 00:22:15 - 00:22:45. Please add." Clicks "Send to Annotator."

7. **End of Week:** Opens "Approved Segments" view. Sees 50 approved segments. Clicks "Export Dataset," selects JSON format. Downloads complete dataset for model training.

**Emotional Arc:** Confusion (scattered feedback) → Clarity (centralized review) → Confidence (highlighted changes) → Authority (quality gatekeeping) → Accomplishment (dataset export).

**Critical Success Factors:** Change highlighting, side-by-side comparison, clear approve/reject actions, structured feedback mechanism, export functionality.

---

### Journey 3: The ASR Reviewer (Dewi) - Pre-Annotation Validation

**Persona:** Dewi, 32, linguistics specialist, 4 years at LBI, focuses on transcript quality

**Current Pain:** ASR sometimes produces transcripts with errors that waste annotators' time. Annotators have to fix ASR errors AND sync issues, slowing down the entire workflow.

**The Journey:**

1. **Monday Morning:** Dewi logs in, navigates to "ASR Review Queue." Sees 8 videos with freshly generated ASR transcripts ready for pre-validation.

2. **Reviews Video #1:** Opens ASR review interface. Sees video player with ASR transcript displayed alongside. Confidence scores shown for each segment (92%, 87%, 95%...).

3. **Identifies Low-Confidence Segment:** Segment at 00:45:30 has 45% confidence. Plays video—speech is unclear due to background noise. She edits the transcript manually, correcting "presiden" to "perwakilan presiden."

4. **Flags Problematic Segment:** Segment at 01:20:00 has completely wrong ASR output. Clicks "Flag for Reprocessing" with note: "Heavy overlapping speech, needs manual transcription."

5. **Approves Clean Transcripts:** Reviews remaining segments—all high confidence and accurate. Clicks "Approve All" to send video to annotation queue.

6. **End of Day:** Dashboard shows "12 videos reviewed, 10 approved, 2 flagged for reprocessing." Annotators receive only validated transcripts, reducing their error-fixing workload.

**Emotional Arc:** Overwhelm (too many errors to fix) → Focus (pre-validation catches errors early) → Efficiency (annotators work faster with clean transcripts) → Quality (higher overall dataset accuracy).

**Critical Success Factors:** Confidence score visibility, easy edit interface, flag/reprocess workflow, batch approval for efficiency.

---

### Journey 4: The Admin (Sari) - Operations Path

**Persona:** Sari, LBI IT coordinator, technical but not ML engineer

**Current Pain:** When CV Detection fails or ASR produces garbage, no visibility. Engineers say "works on my machine" but LBI staff can't use it. Manages user access via database queries.

**The Journey:**

1. **System Alert:** Dashboard notification: "Job failed: Video #123 - ASR stage." Sari clicks notification.

2. **Investigates Failure:** Sees error detail: "Audio codec not supported: pcm_s24le." Checks job logs. Identifies issue: source video has uncommon audio format. Decides to add transcoding pre-processing to pipeline config.

3. **Onboards New User:** New Annotator joins. Navigates to "User Management." Clicks "Add User." Enters email, assigns role "Annotator," sets video access to "News Broadcasts only." User receives invitation email.

4. **Monitors System:** Dashboard shows queue metrics: 12 videos processing, GPU utilization 75%, average processing time 2.3x video length. Notices ASR stage slower than usual (5x normal time).

5. **Takes Action:** Investigates ASR worker. Sees worker stuck on large file. Restarts ASR worker service. Processing times return to normal.

6. **Adjusts Configuration:** LBI receives new video type with shorter sign clips. Navigates to "Pipeline Config." Changes `min_segment_duration` from 5s to 3s. Saves. New videos processed with updated threshold.

7. **Audit Investigation:** LBI director asks about a specific video that was exported last month. Sari navigates to "Audit Log," searches by video ID. Sees complete history: uploaded by Annotator A, ASR reviewed by Dewi, annotated by Rina, curated by Pak Budi, exported on [date]. Full traceability achieved.

8. **Monthly Report:** Exports system metrics: 200 videos processed, 94% success rate, average annotator throughput 4 videos/day, curator approval rate 82%.

**Emotional Arc:** Blindness (no visibility) → Awareness (alerts + logs) → Control (user management + config) → Proactivity (issue resolution) → Confidence (data-driven decisions).

**Critical Success Factors:** Real-time alerts, detailed error logs, user role management, system metrics dashboard, configuration UI, job queue visibility, comprehensive audit trail.

---

### Journey Requirements Summary

| Journey | Key Capabilities Revealed |
|---------|---------------------------|
| **Annotator** | Video player with sync controls, timestamp adjustment (drag handles), transcript text editing, queue dashboard, submit for review workflow |
| **Curator** | Side-by-side review view, change highlighting, approve/reject actions, rejection feedback modal, batch export functionality, slang dictionary, auto-normalization |
| **ASR Reviewer** | ASR confidence scores, transcript pre-validation, edit ASR output, flag for reprocessing, batch approval |
| **Admin** | System health dashboard, job queue monitoring, error log viewer, user management (CRUD + roles), pipeline configuration UI, metrics reporting, audit trail |

**Cross-Cutting Requirements:**
- Role-based access control (Annotator sees queue, Curator sees review, Admin sees everything)
- Real-time status updates (job progress, approval notifications)
- Error handling with user-friendly messages
- Audit trail (who changed what, when)

---

## API & Web Application Specific Requirements

### Project-Type Overview

This is a **Full-Stack Annotation Platform** consisting of:
- **Backend**: FastAPI-based REST API with multi-stage ML pipeline (CV Detection → ASR → Annotation)
- **Frontend**: NextJS web application for Annotators, Curators, and Admins
- **Storage**: MinIO (S3-compatible) for video files, PostgreSQL for metadata
- **Processing**: Async background tasks with polling-based status updates

### Technical Architecture Considerations

#### API Design Pattern
- **Unified Pipeline Endpoint**: Single `/api/v1/jobs` entry point orchestrates all 3 stages (CV Detection → ASR → Annotation)
- **Status Polling**: Clients poll `GET /api/v1/jobs/{id}` for progress updates
- **Stage-Agnostic Frontend**: Frontend doesn't manage stage transitions; backend handles pipeline flow

**Endpoint Structure:**
```
POST   /api/v1/jobs              → Create job (multipart upload)
GET    /api/v1/jobs/{id}         → Get job status + progress
DELETE /api/v1/jobs/{id}         → Cancel job
GET    /api/v1/jobs/{id}/results → Get final results (when completed)
GET    /api/v1/jobs/{id}/segments/{n}/download → Download cropped video (pre-signed URL)
```

#### Authentication & Authorization
- **Method**: JWT tokens (stateless, scalable)
- **Role Enforcement**: Middleware-based with route decorators
- **Permission Model**:
  - Annotator: Read own queue, write own annotations
  - Curator: Read all pending annotations, write approvals/rejections
  - Admin: Full user CRUD, system metrics, configuration

#### Data Formats
- **Upload**: Multipart/form-data (video files + metadata)
- **API Requests/Responses**: JSON throughout
- **Video Download**: Pre-signed URLs to MinIO (S3-compatible storage)

#### Real-Time Updates
- **Mechanism**: Polling (not WebSocket)
- **Configurable Intervals**: Frontend allows selection of 5s, 10s, 30s, 60s
- **Smart Polling**: Faster when processing (5s), slower when queued/completed (30s)
- **Backend Caching**: Job status cached for 2 seconds to reduce database load

#### API Versioning
- **Strategy**: URL-based (`/api/v1/`)
- **MVP**: Single version only
- **Future**: Parallel version support when needed (`/api/v1/`, `/api/v2/`)

#### Resource Protection & Rate Limits
- **Upload**: No file size limit (video sizes vary widely)
- **Concurrent Processing**: Max 3 jobs simultaneously
- **Queue Depth**: Max 20-50 pending jobs (configurable)
- **Polling Rate Limiting**: Exponential backoff + response caching to prevent abuse

#### Storage Architecture
- **Video Files**: MinIO (S3-compatible object storage)
- **Metadata**: PostgreSQL (job status, annotations, user data)
- **Pre-signed URLs**: Time-limited download URLs for video segments

### Implementation Considerations

#### Background Task Processing
- **Queue**: In-memory with PostgreSQL persistence (current JBI Service approach)
- **Scalability Path**: Can migrate to Redis + Celery for higher throughput
- **Failure Handling**: Failed jobs captured with error messages, don't block queue

#### Frontend-Backend Contract
- **NextJS Integration**: API routes proxy to FastAPI backend
- **CORS**: Configured for frontend domain
- **Error Handling**: Consistent JSON error responses with meaningful messages

#### Deployment Profile
- **Docker Compose**: CPU and GPU profiles supported
- **Environment**: Development (auto-reload) vs Production (structured logging)
- **Health Checks**: `/api/v1/health` returns model status, GPU availability, disk space

---

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Experience MVP - Deliver complete end-to-end workflow that solves the core user problem (LBI staff creating SIBI datasets without engineering support), even if initially with manual stage handoffs.

**Resource Requirements:**
- Backend: 1-2 engineers (FastAPI, PostgreSQL, MinIO integration)
- Frontend: 1 engineer (NextJS, video player, annotation UI)
- ML/DevOps: 1 engineer (Arxeno - pipeline integration, model deployment)
- Timeline: 8-12 weeks for MVP

### MVP Feature Set (Phase 1)

**Core User Journeys Supported:**
- Annotator: Upload → Wait for processing → Review & fix sync → Submit
- Curator: Review queue → Approve/Reject with feedback → Export dataset
- Admin: User management → System monitoring → Configuration

**Must-Have Capabilities:**

| Stage | Implementation | Status |
|-------|---------------|--------|
| **Stage 1: CV Detection** | Leverage existing JBI Service | ✅ Foundation exists |
| **Stage 2: ASR** | Integrate faster-whisper, manual trigger initially | 🔄 Build |
| **Stage 3: Annotation** | Video player + timestamp editor + transcript editor | 🔄 Build |
| **Integration** | Manual job status tracking → Automated pipeline | 🔄 Phase 1.5 |

**Phase 1.5 (Integration Automation):**
- Connect CV Detection output → ASR input automatically
- Connect ASR output → Annotation interface
- Replace manual status checks with automated pipeline state machine

### Post-MVP Features

**Phase 2 (Growth - Months 3-6):**
- Real-time collaboration (multiple annotators on same video)
- Batch upload (multiple videos)
- Quality metrics dashboard
- Advanced export formats (JSON, XML, custom)
- ASR fine-tuning interface for domain vocabulary
- WebSocket updates (replace polling)

**Phase 3 (Expansion - Months 6-12):**
- Live stream processing
- Multi-dialect SIBI support
- AI-assisted annotation (predictive sync suggestions)
- Community dataset sharing between institutions
- Mobile annotation app

### Risk Mitigation Strategy

**Technical Risks:**
- **Chaining 3 ML models** → Mitigation: Build stage-by-stage with manual handoff first, automate connections once each stage is stable
- **Video processing at scale** → Mitigation: Queue-based processing with 3 concurrent job limit, configurable queue depth
- **ASR accuracy for Indonesian** → Mitigation: Start with **faster-whisper** library (optimized local inference), plan fine-tuning for news-specific vocabulary in Phase 2

**Market Risks:**
- **LBI adoption resistance** → Mitigation: Beta launch with 2-3 power users, incorporate feedback before wider rollout
- **Workflow mismatch** → Mitigation: User testing at each stage build, validate Annotator/Curator workflow before full automation

**Resource Risks:**
- **ML pipeline complexity** → Mitigation: Leverage existing JBI Service foundation, don't rebuild CV Detection
- **Frontend video player complexity** → Mitigation: Use proven libraries (Video.js, React Player), focus on sync controls

---

## Functional Requirements

### 1. Video Processing Pipeline

> **⚠️ CRITICAL NOTE:** The pipeline algorithm, model selection, and processing logic **MUST** follow the existing Python notebooks (`asr_code.ipynb`, `cv_asr_annotation.ipynb`, `jbi-service/VideoDetector3.ipynb`). The backend implementation is a productionization of these proven notebook workflows.

#### Pipeline Overview (3-Stage Process)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: CV Detection & Initial Crop                                   │
│  ├── Input: Full news video                                             │
│  ├── Model: YOLOv8 (from existing JBI Service)                          │
│  ├── Action: Detect JBI regions → Crop by bounding box                  │
│  └── Output: result_{timestamp}.mp4 clips                              │
│                                                                         │
│  STAGE 2: ASR Transcription                                             │
│  ├── Input: Cropped clips from Stage 1                                  │
│  ├── Model: faster-whisper                                              │
│  ├── Config: Model size configurable (tiny/base/small/medium/large-v3) │
│  └── Output: segments.txt with [start -> end] timestamps               │
│                                                                         │
│  STAGE 3: Timestamp-Based Cropping (JBI Buffer)                         │
│  ├── Input: Clips + ASR timestamps                                      │
│  ├── Logic: Apply ±2 second buffer for sign language context            │
│  │           jbi_start = max(0, asr_start - 2)                          │
│  │           jbi_end = min(duration, asr_end + 2)                       │
│  └── Output: Final clips for annotation interface                       │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Functional Requirements

- **FR1:** Users can upload video files (MP4, AVI, MKV, MOV) via multipart upload or URL
- **FR2:** Users receive a job ID immediately upon successful upload for status tracking
- **FR3:** System automatically detects JBI (sign language interpreter) regions in uploaded videos using YOLOv8
- **FR4:** System performs Stage 1 cropping: crops video segments based on detected bounding boxes (initial crop)
- **FR5:** System automatically transcribes audio from Stage 1 cropped clips using faster-whisper ASR
- **FR5a:** ASR supports configurable model sizes: tiny, base, small, medium, large-v3
- **FR5b:** ASR supports configurable compute types: int8, float16, int8_float16
- **FR5c:** ASR outputs segments.txt format: `[start -> end] transcript text`
- **FR6:** System performs Stage 2 cropping: re-crops clips based on ASR timestamps with ±2 second JBI buffer
- **FR6a:** JBI Time Range calculation: `start = max(0, asr_start - 2)`, `end = min(duration, asr_end + 2)`
- **FR6b:** Final cropped clips are stored for annotation interface
- **FR7:** Users can poll for job status at configurable intervals (5s, 10s, 30s, 60s)
- **FR8:** System reports processing progress per stage (Detection, ASR Stage 1, ASR Stage 2 Cropping)
- **FR9:** Users can cancel queued or processing jobs
- **FR10:** System stores cropped video segments in MinIO with pre-signed URL access
- **FR12:** System maintains processing queue with max concurrent job limits

### 2. User Authentication & Authorization

- **FR13:** Users can authenticate with JWT tokens
- **FR14:** System supports three user roles: Admin, Annotator, Curator
- **FR15:** Annotators can access their assigned annotation queue only
- **FR16:** Curators can access all pending annotations for review
- **FR17:** Admins can access all system functions including user management
- **FR18:** System enforces role-based access control on all endpoints via middleware

### 3. Annotation & Review Workflow

- **FR19:** Annotators can view synchronized video player with transcript panel
- **FR20:** Annotators can adjust transcript timestamps via draggable handles
- **FR21:** Annotators can edit transcript text for spelling and word corrections
- **FR22:** Annotators can preview video at adjusted timestamps before saving
- **FR23:** Annotators can submit annotations to Curator queue
- **FR24:** Curators can view annotation queue with pending items
- **FR25:** Curators can view highlighted changes made by Annotators
- **FR26:** Curators can play video segments to verify synchronization
- **FR27:** Curators can approve annotations, moving them to exportable dataset
- **FR28:** Curators can reject annotations with structured feedback to Annotators
- **FR29:** Rejected annotations return to Annotator queue for revision
- **FR30:** System tracks annotation status (Pending, Approved, Rejected) per segment

### 4. User Management

- **FR31:** Admins can create new user accounts with role assignment
- **FR32:** Admins can modify user roles and permissions
- **FR33:** Admins can deactivate user accounts
- **FR34:** Admins can view list of all users with their roles
- **FR35:** Users receive invitation emails when accounts are created

### 5. System Administration

- **FR36:** Admins can view system health dashboard (job queue depth, processing metrics)
- **FR37:** Admins can view failed job logs with error details
- **FR38:** Admins can configure pipeline parameters (min segment duration, etc.)
- **FR39:** Admins can view per-user activity metrics (videos processed, annotations completed)
- **FR40:** System provides health check endpoint reporting model status, GPU availability, disk space

### 6. Data Export & Integration

- **FR41:** Curators can export approved segments as structured dataset
- **FR42:** System supports JSON format for dataset export
- **FR43:** Export includes video paths, transcripts, timestamps, and metadata
- **FR44:** System maintains audit trail of who approved each segment and when

### 7. ASR Review (Pre-Annotation Validation)

- **FR45:** Reviewers can view ASR-generated transcripts before they enter annotation workflow
- **FR46:** Reviewers can edit ASR transcripts for spelling and word accuracy
- **FR47:** Reviewers can approve ASR output to proceed to annotation stage
- **FR48:** Reviewers can flag ASR segments for re-processing with specific issues
- **FR49:** System maintains ASR confidence scores for each transcript segment

### 8. Slang Dictionary & Normalization

- **FR50:** Curators can view slang-to-standard dictionary during curation
- **FR51:** System automatically suggests standard Indonesian equivalents for slang terms
- **FR52:** Curators can apply auto-normalization to convert slang to standard language
- **FR53:** Curators can manually override normalized text when auto-normalization is incorrect
- **FR54:** System learns from curator corrections to improve future normalizations

### 9. Audit Trail & History

- **FR55:** Admins can view complete audit log of all user actions
- **FR56:** Audit log includes timestamp, user, action type, and affected resources
- **FR57:** System tracks video state transitions (uploaded → processing → annotated → curated → exported)
- **FR58:** Admins can filter audit logs by date range, user, or action type
- **FR59:** Audit logs are immutable and retained for compliance

### 10. User Onboarding & Guidance

- **FR60:** System provides interactive tour for first-time users
- **FR61:** Tours cover annotation workflow, curation process, and admin functions
- **FR62:** Users can replay tours or access help documentation at any time
- **FR63:** Contextual tooltips provide guidance for complex interface elements

---

## Non-Functional Requirements

### Performance

- **NFR1:** Video upload endpoint responds within 2 seconds for files up to 2GB
- **NFR2:** Status polling endpoint responds within 200ms under normal load
- **NFR3:** Job status is cached for 2 seconds to reduce database load during polling
- **NFR4:** Video segments download via pre-signed URLs at minimum 5 Mbps sustained throughput
- **NFR5:** Annotation interface video player supports scrubbing with <500ms latency
- **NFR6:** CV Detection stage processes video at minimum 1 second of video per 2 seconds of wall time (0.5x real-time)

### Security

- **NFR7:** All API communications use HTTPS/TLS 1.3 encryption in transit
- **NFR8:** JWT tokens expire after 24 hours with refresh token support
- **NFR9:** Passwords are hashed using bcrypt with salt rounds ≥12
- **NFR10:** Pre-signed URLs for video download expire after 1 hour
- **NFR11:** Failed authentication attempts are rate-limited (5 attempts per 15 minutes per IP)
- **NFR12:** Video files in MinIO are encrypted at rest using AES-256

### Scalability

- **NFR13:** System supports maximum 3 concurrent video processing jobs
- **NFR14:** Job queue depth supports maximum 50 pending jobs before rejecting new uploads
- **NFR15:** System maintains performance with up to 100 concurrent authenticated users
- **NFR16:** PostgreSQL connection pool supports 20 concurrent connections minimum
- **NFR17:** System handles video files up to 10GB without memory exhaustion

### Accessibility

- **NFR18:** Web interface meets WCAG 2.1 Level AA compliance
- **NFR19:** Video player supports keyboard navigation (play, pause, seek, timestamp adjustment)
- **NFR20:** All interactive elements have minimum 44x44px touch targets
- **NFR21:** Color contrast ratios meet 4.5:1 minimum for text
- **NFR22:** Interface supports screen reader announcements for status changes
- **NFR23:** Users can adjust video playback speed (0.5x, 0.75x, 1x, 1.25x, 1.5x) for annotation accuracy

### Reliability & Availability

- **NFR24:** System achieves 95% end-to-end job completion rate (accounting for corrupt inputs)
- **NFR25:** Failed jobs provide actionable error messages to users
- **NFR26:** Database maintains ACID consistency for all job state transitions
- **NFR27:** System gracefully degrades when GPU unavailable (falls back to CPU processing)
- **NFR28:** Background task workers automatically restart on failure without manual intervention

---

## Changelog

### 2026-03-18 - Frontend & Algorithm Alignment Update

**Purpose:** Aligned PRD with existing frontend implementation (`anotasi.ai-FE/`) and Python notebooks

**Changes Made:**

1. **Backend Clarification**
   - Confirmed FastAPI (Python) as backend technology
   - Removed ambiguity about Go backend

2. **Critical Algorithm Alignment (FIXED)**
   - **Added CRITICAL NOTE:** All models/algorithms must follow existing Python notebooks
   - **Two-Stage Cropping:** Documented Stage 1 (CV bbox) + Stage 2 (ASR timestamp ±2s buffer)
   - **JBI Time Range:** Explicitly defined calculation `max(0, start-2)` to `min(duration, end+2)`
   - **ASR Configuration:** Added faster-whisper details (model sizes, compute types, output format)
   - **Pipeline Flow:** Updated from 2 stages to correct 3-stage process matching notebooks

3. **New Functional Requirements Added:**
   - **ASR Details (FR5a-FR5c):** Model sizes, compute types, output format
   - **Stage 2 Cropping (FR6, FR6a, FR6b):** Timestamp-based cropping with JBI buffer
   - **ASR Review (FR45-FR49):** Pre-annotation validation workflow
   - **Slang Dictionary & Normalization (FR50-FR54):** Indonesian slang conversion
   - **Audit Trail & History (FR55-FR59):** Comprehensive audit logging
   - **User Onboarding & Guidance (FR60-FR63):** Interactive tours and help system

4. **Updated User Journeys:**
   - Added **ASR Reviewer (Dewi)** journey
   - Updated **Admin (Sari)** journey to include audit investigation
   - Updated journey requirements summary

5. **Updated Project Classification:**
   - Added "slang normalization" and "tour/onboarding" to annotation features

**Total FRs:** 42 → 63 (+21 new requirements)

**Alignment Status:** 
- ✅ PRD now comprehensively covers all frontend features
- ✅ PRD now correctly reflects notebook algorithms (3-stage pipeline)

---

*End of Product Requirements Document
