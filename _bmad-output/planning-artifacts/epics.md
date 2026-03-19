---
stepsCompleted: [1, 2, 3]
inputDocuments:
  - path: jbi-service/_bmad-output/planning-artifacts/prd.md
    type: prd
    loaded: true
  - path: jbi-service/_bmad-output/planning-artifacts/architecture.md
    type: architecture
    loaded: true
workflowType: epics
project_name: 'Unified SIBI Pipeline API'
date: '2026-03-18'
---

# Unified SIBI Pipeline API - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for the Unified SIBI Pipeline API, decomposing the requirements from the PRD and Architecture into implementable stories.

## Requirements Inventory

### Functional Requirements

**Total: 63 FRs**

#### 1. Video Processing Pipeline (FR1-FR12)
- **FR1:** Users can upload video files (MP4, AVI, MKV, MOV) via multipart upload or URL
- **FR2:** Users receive a job ID immediately upon successful upload for status tracking
- **FR3:** System automatically detects JBI regions in uploaded videos using YOLOv8
- **FR4:** System performs Stage 1 cropping: crops video segments based on detected bounding boxes
- **FR5:** System automatically transcribes audio from Stage 1 cropped clips using faster-whisper ASR
- **FR5a:** ASR supports configurable model sizes: tiny, base, small, medium, large-v3
- **FR5b:** ASR supports configurable compute types: int8, float16, int8_float16
- **FR5c:** ASR outputs segments.txt format: `[start -> end] transcript text`
- **FR6:** System performs Stage 2 cropping: re-crops clips based on ASR timestamps with ±2 second JBI buffer
- **FR6a:** JBI Time Range calculation: `start = max(0, asr_start - 2)`, `end = min(duration, asr_end + 2)`
- **FR6b:** Final cropped clips are stored for annotation interface
- **FR7:** Users can poll for job status at configurable intervals (5s, 10s, 30s, 60s)
- **FR8:** System reports processing progress per stage
- **FR9:** Users can cancel queued or processing jobs
- **FR10:** System stores cropped video segments in MinIO with pre-signed URL access
- **FR12:** System maintains processing queue with max concurrent job limits

#### 2. User Authentication & Authorization (FR13-FR18)
- **FR13:** Users can authenticate with JWT tokens
- **FR14:** System supports three user roles: Admin, Annotator, Curator
- **FR15:** Annotators can access their assigned annotation queue only
- **FR16:** Curators can access all pending annotations for review
- **FR17:** Admins can access all system functions including user management
- **FR18:** System enforces role-based access control on all endpoints via middleware

#### 3. Annotation & Review Workflow (FR19-FR30)
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

#### 4. User Management (FR31-FR35)
- **FR31:** Admins can create new user accounts with role assignment
- **FR32:** Admins can modify user roles and permissions
- **FR33:** Admins can deactivate user accounts
- **FR34:** Admins can view list of all users with their roles
- **FR35:** Users receive invitation emails when accounts are created

#### 5. System Administration (FR36-FR40)
- **FR36:** Admins can view system health dashboard
- **FR37:** Admins can view failed job logs with error details
- **FR38:** Admins can configure pipeline parameters
- **FR39:** Admins can view per-user activity metrics
- **FR40:** System provides health check endpoint

#### 6. Data Export & Integration (FR41-FR44)
- **FR41:** Curators can export approved segments as structured dataset
- **FR42:** System supports JSON format for dataset export
- **FR43:** Export includes video paths, transcripts, timestamps, and metadata
- **FR44:** System maintains audit trail of who approved each segment and when

#### 7. ASR Review (FR45-FR49)
- **FR45:** Reviewers can view ASR-generated transcripts before annotation workflow
- **FR46:** Reviewers can edit ASR transcripts for spelling and word accuracy
- **FR47:** Reviewers can approve ASR output to proceed to annotation stage
- **FR48:** Reviewers can flag ASR segments for re-processing with specific issues
- **FR49:** System maintains ASR confidence scores for each transcript segment

#### 8. Slang Dictionary & Normalization (FR50-FR54)
- **FR50:** Curators can view slang-to-standard dictionary during curation
- **FR51:** System automatically suggests standard Indonesian equivalents for slang terms
- **FR52:** Curators can apply auto-normalization to convert slang to standard language
- **FR53:** Curators can manually override normalized text when auto-normalization is incorrect
- **FR54:** System learns from curator corrections to improve future normalizations

#### 9. Audit Trail & History (FR55-FR59)
- **FR55:** Admins can view complete audit log of all user actions
- **FR56:** Audit log includes timestamp, user, action type, and affected resources
- **FR57:** System tracks video state transitions
- **FR58:** Admins can filter audit logs by date range, user, or action type
- **FR59:** Audit logs are immutable and retained for compliance

#### 10. User Onboarding & Guidance (FR60-FR63)
- **FR60:** System provides interactive tour for first-time users
- **FR61:** Tours cover annotation workflow, curation process, and admin functions
- **FR62:** Users can replay tours or access help documentation at any time
- **FR63:** Contextual tooltips provide guidance for complex interface elements

### Non-Functional Requirements

**Total: 28 NFRs**

#### Performance (NFR1-NFR6)
- **NFR1:** Video upload endpoint responds within 2 seconds for files up to 2GB
- **NFR2:** Status polling endpoint responds within 200ms under normal load
- **NFR3:** Job status is cached for 2 seconds to reduce database load during polling
- **NFR4:** Video segments download via pre-signed URLs at minimum 5 Mbps sustained throughput
- **NFR5:** Annotation interface video player supports scrubbing with <500ms latency
- **NFR6:** CV Detection stage processes video at minimum 0.5x real-time

#### Security (NFR7-NFR12)
- **NFR7:** All API communications use HTTPS/TLS 1.3 encryption in transit
- **NFR8:** JWT tokens expire after 24 hours with refresh token support
- **NFR9:** Passwords are hashed using bcrypt with salt rounds ≥12
- **NFR10:** Pre-signed URLs for video download expire after 1 hour
- **NFR11:** Failed authentication attempts are rate-limited (5 attempts per 15 minutes per IP)
- **NFR12:** Video files in MinIO are encrypted at rest using AES-256

#### Scalability (NFR13-NFR17)
- **NFR13:** System supports maximum 3 concurrent video processing jobs
- **NFR14:** Job queue depth supports maximum 50 pending jobs
- **NFR15:** System maintains performance with up to 100 concurrent authenticated users
- **NFR16:** PostgreSQL connection pool supports 20 concurrent connections minimum
- **NFR17:** System handles video files up to 10GB without memory exhaustion

#### Accessibility (NFR18-NFR23)
- **NFR18:** Web interface meets WCAG 2.1 Level AA compliance
- **NFR19:** Video player supports keyboard navigation
- **NFR20:** All interactive elements have minimum 44x44px touch targets
- **NFR21:** Color contrast ratios meet 4.5:1 minimum for text
- **NFR22:** Interface supports screen reader announcements for status changes
- **NFR23:** Users can adjust video playback speed (0.5x, 0.75x, 1x, 1.25x, 1.5x)

#### Reliability & Availability (NFR24-NFR28)
- **NFR24:** System achieves 95% end-to-end job completion rate
- **NFR25:** Failed jobs provide actionable error messages to users
- **NFR26:** Database maintains ACID consistency for all job state transitions
- **NFR27:** System gracefully degrades when GPU unavailable (falls back to CPU)
- **NFR28:** Background task workers automatically restart on failure

### Additional Requirements

**From Architecture Document:**

#### Technical Stack
- FastAPI 0.135+ with Python 3.9+
- SQLAlchemy 2.0 with async PostgreSQL
- Pydantic v2 for data validation
- PyJWT for custom JWT implementation
- MinIO for S3-compatible object storage

#### Infrastructure
- Docker Compose for local development
- PostgreSQL 15+ for database
- MinIO for video storage
- Alembic for database migrations

#### Architecture Patterns
- Domain-prefixed database schema (`auth_*`, `pipeline_*`, `annotation_*`, `audit_*`, `config_*`)
- 4-layer architecture: API → Service → Worker → Pipeline
- Custom JWT with role-based access control
- PostgreSQL-backed queue (upgrade path to Redis)
- Pre-signed URLs for video access (1-hour expiry)

#### Critical Implementation Notes
- MUST follow existing Python notebooks exactly (VideoDetector3.ipynb, asr_code.ipynb, cv_asr_annotation.ipynb)
- Two-stage cropping: Stage 1 (YOLOv8 bbox) → Stage 2 (ASR timestamp ±2s buffer)
- ASR Review is optional and parallel to annotation workflow
- String-based state machine in CONSTANT_CASE format

### UX Design Requirements

**Status:** No formal UX document exists. UX requirements are implied from:
- Existing frontend codebase (`anotasi.ai-FE/`)
- PRD user journeys (4 personas: Rina, Pak Budi, Dewi, Sari)
- NFR18-NFR23 accessibility requirements

### FR Coverage Map

| FR # | Requirement | Epic |
|------|-------------|------|
| FR1 | Video upload | Epic 2 |
| FR2 | Job ID tracking | Epic 2 |
| FR3 | YOLOv8 detection | Epic 2 |
| FR4 | Stage 1 cropping | Epic 2 |
| FR5 | faster-whisper ASR | Epic 2 |
| FR5a | Configurable model sizes | Epic 2 |
| FR5b | Configurable compute types | Epic 2 |
| FR5c | segments.txt format | Epic 2 |
| FR6 | Stage 2 cropping | Epic 2 |
| FR6a | JBI buffer calculation | Epic 2 |
| FR6b | Final clips storage | Epic 2 |
| FR7 | Poll for status | Epic 2 |
| FR8 | Progress per stage | Epic 2 |
| FR9 | Cancel jobs | Epic 2 |
| FR10 | MinIO pre-signed URLs | Epic 2 |
| FR12 | Concurrent job limits | Epic 2 |
| FR13 | JWT tokens | Epic 1 |
| FR14 | 3 user roles | Epic 1 |
| FR15 | Annotator queue access | Epic 1 |
| FR16 | Curator review access | Epic 1 |
| FR17 | Admin full access | Epic 1 |
| FR18 | RBAC middleware | Epic 1 |
| FR19 | Video player + transcript | Epic 3 |
| FR20 | Timestamp adjustment | Epic 3 |
| FR21 | Transcript editing | Epic 3 |
| FR22 | Preview before save | Epic 3 |
| FR23 | Submit for review | Epic 3 |
| FR24 | Curator view queue | Epic 4 |
| FR25 | Highlighted changes | Epic 4 |
| FR26 | Play segments | Epic 4 |
| FR27 | Approve annotations | Epic 4 |
| FR28 | Reject with feedback | Epic 4 |
| FR29 | Return to annotator | Epic 4 |
| FR30 | Track segment status | Epic 4 |
| FR31 | Create users | Epic 1 |
| FR32 | Modify roles | Epic 1 |
| FR33 | Deactivate accounts | Epic 1 |
| FR34 | List users | Epic 1 |
| FR35 | Invitation emails | Epic 1 |
| FR36 | Health dashboard | Epic 2 |
| FR37 | Failed job logs | Epic 2 |
| FR38 | Pipeline config | Epic 2 |
| FR39 | Per-user metrics | Epic 5 |
| FR40 | Health check endpoint | Epic 2 |
| FR41 | Export approved segments | Epic 4 |
| FR42 | JSON format export | Epic 4 |
| FR43 | Include metadata in export | Epic 4 |
| FR44 | Audit trail | Epic 5 |
| FR45 | View ASR transcripts | Epic 3 |
| FR46 | Edit ASR transcripts | Epic 3 |
| FR47 | Approve ASR output | Epic 3 |
| FR48 | Flag for reprocessing | Epic 3 |
| FR49 | ASR confidence scores | Epic 3 |
| FR50 | Slang dictionary view | Epic 4 |
| FR51 | Auto-suggest standard | Epic 4 |
| FR52 | Apply normalization | Epic 4 |
| FR53 | Manual override | Epic 4 |
| FR54 | Learn from corrections | Epic 4 |
| FR55 | View audit logs | Epic 5 |
| FR56 | Audit log details | Epic 5 |
| FR57 | State transition tracking | Epic 5 |
| FR58 | Filter audit logs | Epic 5 |
| FR59 | Immutable audit logs | Epic 5 |
| FR60 | Interactive tours | Epic 6 |
| FR61 | Tours cover workflows | Epic 6 |
| FR62 | Replay tours | Epic 6 |
| FR63 | Contextual tooltips | Epic 6 |

## Epic List

### Epic 1: Foundation & Authentication
**Goal:** Users can register, login, and admins can manage user accounts securely with role-based access control.

**User Outcomes:**
- Users can authenticate with JWT tokens
- System enforces 3-role permissions (Admin, Annotator, Curator)
- Admins can create, modify, and deactivate user accounts
- Users receive invitation emails for account activation

**FRs covered:** FR13-FR18, FR31-FR35 (11 FRs)

**NFRs addressed:** NFR7-NFR12 (Security)

---

### Epic 2: Video Processing Pipeline
**Goal:** Users can upload videos and the system automatically processes them through CV Detection → ASR → Cropping with status tracking.

**User Outcomes:**
- Users can upload videos via multipart or URL
- System detects JBI regions using YOLOv8
- ASR transcription with configurable models (tiny to large-v3)
- Automatic timestamp-based cropping with ±2s JBI buffer
- Real-time status polling and job cancellation
- Health monitoring and system configuration

**FRs covered:** FR1-FR12, FR36-FR40 (17 FRs)

**NFRs addressed:** NFR1-NFR6 (Performance), NFR13-NFR17 (Scalability), NFR24-NFR28 (Reliability)

---

### Epic 3: Annotation Workflow
**Goal:** Annotators can review and correct synchronized video-transcript pairs with optional pre-annotation ASR validation.

**User Outcomes:**
- Annotators view synchronized video player with transcripts
- Adjust timestamps with draggable handles
- Edit transcript text for accuracy
- Preview changes before saving
- Submit completed annotations for curation
- Optional ASR Review workflow for transcript pre-validation

**FRs covered:** FR19-FR23, FR45-FR49 (14 FRs)

**NFRs addressed:** NFR5 (Video player performance)

---

### Epic 4: Curation & Export
**Goal:** Curators can review, approve/reject annotations, normalize Indonesian slang, and export datasets for training.

**User Outcomes:**
- Curators view annotation queue with highlighted changes
- Approve or reject annotations with structured feedback
- View and manage slang-to-standard dictionary
- Apply auto-normalization with manual override capability
- Export approved segments as JSON datasets with full metadata

**FRs covered:** FR24-FR30, FR41-FR44, FR50-FR54 (21 FRs)

**NFRs addressed:** NFR4 (Download performance)

---

### Epic 5: Audit & Compliance
**Goal:** Admins can view complete, immutable audit trails of all system actions for compliance and accountability.

**User Outcomes:**
- View complete audit log of all user actions
- Filter logs by date, user, or action type
- Track video state transitions through pipeline
- Immutable logs retained for compliance
- Per-user activity metrics and reporting

**FRs covered:** FR39, FR44, FR55-FR59 (7 FRs)

**NFRs addressed:** NFR7-NFR12 (Security), NFR26 (ACID consistency)

---

### Epic 6: User Onboarding
**Goal:** First-time users receive guided tours and contextual help to effectively use the platform.

**User Outcomes:**
- Interactive tours for annotation, curation, and admin workflows
- Ability to replay tours or access help anytime
- Contextual tooltips for complex interface elements
- Accessible interface meeting WCAG 2.1 Level AA

**FRs covered:** FR60-FR63 (4 FRs)

**NFRs addressed:** NFR18-NFR23 (Accessibility)

---

## Epic Dependencies

```
Epic 1 (Auth) ──┬──► Epic 2 (Pipeline) ──┬──► Epic 3 (Annotation)
                │                        │
                │                        └──► Epic 4 (Curation)
                │
                └──► Epic 5 (Audit) ───► Depends on all epics
                
Epic 6 (Onboarding) ──► Depends on all epics (tours all features)
```

**Implementation Order:** Epic 1 → Epic 2 → Epic 3 → Epic 4 → Epic 5 → Epic 6



---

## Epic 1: Foundation & Authentication

### Epic Goal
Users can register, login, and admins can manage user accounts securely with role-based access control.

### FRs Covered
FR13-FR18, FR31-FR35 (11 FRs)

### Stories

#### Story 1.1: Database Schema Setup - Auth Domain

As a developer,
I want to create the authentication database schema,
So that user data and roles can be stored and managed.

**Acceptance Criteria:**

**Given** the database migration system is initialized
**When** I run the auth domain migration
**Then** the following tables are created:
  - `auth_users` (id, email, password_hash, role, is_active, created_at, updated_at)
  - `auth_roles` (id, name, permissions)
  - `auth_user_roles` (user_id, role_id) - junction table
**And** appropriate indexes are created on email and role fields
**And** the schema follows domain-prefixed naming convention

**Technical Notes:**
- Use Alembic for migration
- Password hash field must support bcrypt (min 60 chars)
- Role enum: 'admin', 'annotator', 'curator'

---

#### Story 1.2: JWT Authentication Service

As a developer,
I want to implement JWT token generation and validation,
So that users can be securely authenticated.

**Acceptance Criteria:**

**Given** the JWT configuration is set (secret key, algorithm HS256)
**When** I call `create_access_token(user_id, role)`
**Then** a JWT token is returned with:
  - sub: user_uuid
  - role: user_role
  - iat: current timestamp
  - exp: current + 24 hours
  - type: "access"

**Given** a valid JWT token
**When** I call `verify_token(token)`
**Then** the token is validated and decoded payload is returned
**And** expired tokens raise appropriate error
**And** invalid tokens raise authentication error

**Technical Notes:**
- Use PyJWT 2.8+
- Configurable expiry via settings
- Support for RS256 (future multi-service)

---

#### Story 1.3: User Login API Endpoint

As a user,
I want to login with my email and password,
So that I can access the system.

**Acceptance Criteria:**

**Given** I have a registered account with email "user@lbi.ac.id" and password "secret123"
**When** I POST to `/api/v1/auth/login` with valid credentials
**Then** I receive a 200 response with:
  - access_token (JWT)
  - refresh_token (JWT)
  - token_type: "bearer"
  - expires_in: 86400

**Given** I provide invalid credentials
**When** I POST to `/api/v1/auth/login`
**Then** I receive a 401 response with error message "Invalid credentials"
**And** failed attempt is counted for rate limiting

**Given** I have 5 failed login attempts in 15 minutes
**When** I attempt to login again
**Then** I receive a 429 response with error message "Too many attempts, try again later"

**Technical Notes:**
- Use bcrypt for password verification (12+ rounds)
- Implement rate limiting middleware
- Return generic error for invalid credentials (don't reveal which field is wrong)

---

#### Story 1.4: JWT Refresh Token Flow

As a user,
I want to refresh my access token using a refresh token,
So that I don't need to re-login frequently.

**Acceptance Criteria:**

**Given** I have a valid refresh token (7-day expiry)
**When** I POST to `/api/v1/auth/refresh` with the refresh token
**Then** I receive a new access_token and refresh_token pair
**And** the new access token has 24-hour expiry
**And** the new refresh token has 7-day expiry

**Given** I have an expired refresh token
**When** I attempt to refresh
**Then** I receive a 401 response with error "Refresh token expired, please login again"

**Given** I have a revoked/blacklisted refresh token
**When** I attempt to refresh
**Then** I receive a 401 response with error "Invalid refresh token"

**Technical Notes:**
- Store refresh token jti in database for revocation capability
- Rotate refresh tokens (new token issued on each refresh)

---

#### Story 1.5: Role-Based Access Control Middleware

As a system,
I want to enforce role-based permissions on API endpoints,
So that users can only access resources appropriate to their role.

**Acceptance Criteria:**

**Given** an endpoint decorated with `@require_role("admin")`
**When** an admin user makes a request with valid JWT
**Then** the request is allowed to proceed

**Given** an endpoint decorated with `@require_role("admin")`
**When** an annotator user makes a request
**Then** the request is rejected with 403 "Insufficient permissions"

**Given** an endpoint decorated with `@require_role("annotator", "curator")`
**When** either an annotator or curator makes a request
**Then** the request is allowed to proceed

**Given** a request without a valid JWT token
**When** accessing a protected endpoint
**Then** the request is rejected with 401 "Authentication required"

**Given** the current user dependency is used
**When** accessing any protected endpoint
**Then** the handler receives the authenticated user object
**And** the user object contains id, email, and role

**Technical Notes:**
- Create FastAPI dependency `get_current_user()`
- Create role checking dependency `require_role(...)`
- Support permission-based decorators for future granularity

---

#### Story 1.6: Admin - Create User Accounts

As an admin,
I want to create new user accounts with role assignment,
So that new team members can access the system.

**Acceptance Criteria:**

**Given** I am authenticated as an admin
**When** I POST to `/api/v1/admin/users` with:
  - email: "newuser@lbi.ac.id"
  - role: "annotator"
  - temporary_password: "TempPass123!"
**Then** a new user is created in the database
**And** the password is hashed with bcrypt
**And** I receive a 201 response with user details (excluding password)
**And** an invitation email is queued for sending

**Given** I attempt to create a user with an existing email
**When** I POST to `/api/v1/admin/users`
**Then** I receive a 409 response with error "User with this email already exists"

**Given** I attempt to create a user without admin role
**When** I POST to `/api/v1/admin/users`
**Then** I receive a 403 response with error "Admin access required"

**Given** I create a user with role "curator"
**When** the user is created
**Then** the user can immediately login with the temporary password
**And** the user is assigned to the curator role

**Technical Notes:**
- Validate email format
- Validate role is one of allowed values
- Generate secure temporary password if not provided
- Email service integration (can be stubbed for MVP)

---

#### Story 1.7: Admin - Modify User Roles

As an admin,
I want to modify user roles,
So that I can update permissions as team responsibilities change.

**Acceptance Criteria:**

**Given** I am authenticated as an admin
**And** a user exists with id "uuid-123" and role "annotator"
**When** I PUT to `/api/v1/admin/users/uuid-123/role` with:
  - role: "curator"
**Then** the user's role is updated to "curator"
**And** I receive a 200 response with updated user details
**And** an audit log entry is created for the role change

**Given** I attempt to modify my own role
**When** I PUT to my own user role endpoint
**Then** I receive a 400 response with error "Cannot modify your own role"

**Given** I attempt to change a user's role to an invalid value
**When** I PUT to the role endpoint with role "superadmin"
**Then** I receive a 400 response with error "Invalid role specified"

**Given** the user is currently logged in
**When** their role is changed
**Then** their current session remains valid until token expiry
**And** on next token refresh, the new role takes effect

---

#### Story 1.8: Admin - Deactivate User Accounts

As an admin,
I want to deactivate user accounts,
So that former employees can no longer access the system.

**Acceptance Criteria:**

**Given** I am authenticated as an admin
**And** a user exists with id "uuid-123" and is_active: true
**When** I DELETE to `/api/v1/admin/users/uuid-123`
**Then** the user's is_active flag is set to false (soft delete)
**And** I receive a 200 response confirming deactivation
**And** an audit log entry is created

**Given** I attempt to deactivate my own account
**When** I DELETE to my own user endpoint
**Then** I receive a 400 response with error "Cannot deactivate your own account"

**Given** a deactivated user attempts to login
**When** they POST to `/api/v1/auth/login`
**Then** they receive a 401 response with error "Account is deactivated"

**Given** I am an admin
**When** I list users
**Then** I can see both active and inactive users
**And** there is a filter to show only active/inactive

**Technical Notes:**
- Use soft delete (is_active flag) not hard delete
- Preserve audit history for deactivated users
- Consider revoking all refresh tokens on deactivation

---

#### Story 1.9: Admin - List and View Users

As an admin,
I want to view a list of all users and their details,
So that I can manage the team effectively.

**Acceptance Criteria:**

**Given** I am authenticated as an admin
**When** I GET `/api/v1/admin/users`
**Then** I receive a 200 response with paginated user list:
  - id, email, role, is_active, created_at, last_login
**And** the list supports pagination (page, page_size params)

**Given** I GET `/api/v1/admin/users` with query param `role=annotator`
**When** the request is made
**Then** I receive only users with role "annotator"

**Given** I GET `/api/v1/admin/users` with query param `is_active=false`
**When** the request is made
**Then** I receive only deactivated users

**Given** I GET `/api/v1/admin/users/{user_id}`
**When** the user exists
**Then** I receive detailed user information including:
  - All fields from list view
  - created_at, updated_at timestamps
  - activity summary (videos annotated, reviews completed)

**Given** I am not an admin
**When** I attempt to access user list endpoint
**Then** I receive a 403 response

**Technical Notes:**
- Support filtering by role, is_active, created_date
- Support sorting by created_at, last_login
- Default page size: 20, max: 100
- Do not return password_hash in any response

---

### Epic 1 Summary
- **Total Stories:** 9
- **FRs Covered:** 11/11 (100%)
- **Key Deliverables:**
  - Complete auth database schema
  - JWT authentication system
  - Role-based access control
  - User management CRUD for admins

---

## Epic 2: Video Processing Pipeline

### Epic Goal
Users can upload videos and the system automatically processes them through CV Detection → ASR → Cropping with status tracking.

### FRs Covered
FR1-FR12, FR36-FR40 (17 FRs)

### Stories

#### Story 2.1: Database Schema - Pipeline Domain

As a developer,
I want to create the pipeline database schema,
So that video processing jobs and segments can be stored and tracked.

**Acceptance Criteria:**

**Given** the database migration system is initialized
**When** I run the pipeline domain migration
**Then** the following tables are created:
  - `pipeline_jobs` (id, video_path, original_filename, status, current_stage, error_message, created_by, created_at, updated_at, completed_at)
  - `pipeline_segments` (id, job_id, segment_index, bbox_data, asr_text, asr_confidence, asr_start, asr_end, jbi_start, jbi_end, status, cropped_video_path)
  - `pipeline_job_logs` (id, job_id, stage, message, created_at)
  - `queue_jobs` (id, queue_name, payload, status, priority, attempts, max_attempts, error_message, created_at, scheduled_at, processed_at)
  - `config_pipeline_params` (key, value, description, updated_at)

**And** appropriate foreign keys and indexes are created
**And** status fields use CONSTANT_CASE string values

**Technical Notes:**
- Job status: UPLOADED, QUEUED, DETECTING, TRANSCRIBING, CROPPING, READY_FOR_ANNOTATION, FAILED, CANCELLED
- Queue status: pending, processing, completed, failed
- bbox_data stored as JSONB

---

#### Story 2.2: MinIO Storage Integration

As a developer,
I want to integrate MinIO for video storage,
So that video files can be uploaded and retrieved securely.

**Acceptance Criteria:**

**Given** MinIO is configured (endpoint, access_key, secret_key, bucket_name)
**When** I call `minio_service.upload_file(file_data, object_name)`
**Then** the file is uploaded to the configured bucket
**And** the object_name follows pattern: `jobs/{job_id}/{filename}`

**Given** a file exists in MinIO
**When** I call `minio_service.generate_presigned_url(object_name, expiry=3600)`
**Then** a pre-signed URL is returned valid for 1 hour
**And** the URL allows direct download without API authentication

**Given** a job is complete and segments are stored
**When** I call `minio_service.get_segment_url(job_id, segment_index)`
**Then** a pre-signed URL for the specific segment is returned

**Given** MinIO is unavailable
**When** attempting upload or download
**Then** appropriate error is raised with retry information

**Technical Notes:**
- Use minio-py client
- Configure bucket lifecycle policies for cleanup
- Support multipart upload for large files
- Store content-type metadata

---

#### Story 2.3: Video Upload API

As a user,
I want to upload video files for processing,
So that they can be analyzed by the pipeline.

**Acceptance Criteria:**

**Given** I am authenticated with valid JWT
**When** I POST to `/api/v1/jobs` with multipart/form-data video file (MP4, AVI, MKV, MOV)
**Then** I receive immediate response (within 2 seconds) with:
  - job_id: UUID
  - status: "UPLOADED"
  - message: "Video uploaded successfully, processing will begin shortly"

**Given** I upload a video file
**When** the upload is successful
**Then** the file is stored in MinIO
**And** a pipeline_jobs record is created with status "UPLOADED"
**And** a queue job is created for the detection stage

**Given** I upload a file larger than 10GB
**When** I attempt upload
**Then** I receive a 413 response with error "File too large, maximum size is 10GB"

**Given** I upload a file with unsupported format (e.g., .wmv)
**When** I attempt upload
**Then** I receive a 400 response with error "Unsupported file format"

**Given** I upload via URL (instead of file)
**When** I POST to `/api/v1/jobs` with JSON body `{ "video_url": "https://..." }`
**Then** the system downloads the video from URL
**And** proceeds with normal processing flow

**Technical Notes:**
- Use streaming upload for large files
- Validate file type by extension and MIME type
- Generate unique job_id using UUID
- URL download should timeout after reasonable period

---

#### Story 2.4: PostgreSQL Queue Implementation

As a developer,
I want to implement a job queue using PostgreSQL,
So that video processing stages can be executed asynchronously.

**Acceptance Criteria:**

**Given** the queue table exists
**When** I call `queue.enqueue("detection", {"job_id": "uuid"})`
**Then** a new queue job is created with status "pending"
**And** the job is scheduled for immediate processing

**Given** pending jobs exist in the queue
**When** a worker calls `queue.dequeue("detection")`
**Then** the oldest pending job is returned
**And** its status is updated to "processing"
**And** the job is locked to prevent other workers from picking it up

**Given** a job fails during processing
**When** the worker reports failure
**Then** the job status is set to "failed"
**And** attempts counter is incremented
**And** if attempts < max_attempts, job is rescheduled with exponential backoff

**Given** a job completes successfully
**When** the worker reports completion
**Then** the job status is set to "completed"
**And** processed_at timestamp is recorded

**Given** I want to check queue status
**When** I query queue metrics
**Then** I can see pending count, processing count, failed count per queue

**Technical Notes:**
- Use SELECT FOR UPDATE SKIP LOCKED for atomic dequeue
- Implement exponential backoff: 5s, 15s, 45s
- Support queue priorities (high, normal, low)
- Clean up completed jobs after retention period

---

#### Story 2.5: Detection Worker - YOLOv8 Integration

As a system,
I want to detect JBI regions in videos using YOLOv8,
So that sign language interpreter segments can be identified.

**Acceptance Criteria:**

**Given** a job is queued for detection stage
**When** the DetectionWorker picks up the job
**Then** the worker downloads the video from MinIO
**And** runs YOLOv8 detection (from VideoDetector3.ipynb)
**And** identifies all JBI regions with confidence scores

**Given** YOLOv8 detects JBI regions
**When** detection is complete
**Then** Stage 1 cropping is performed (bbox crop)
**And** cropped segments are uploaded to MinIO
**And** segment records are created in pipeline_segments table
**And** job status is updated to "TRANSCRIBING"
**And** next stage is queued for ASR processing

**Given** no JBI regions are detected
**When** detection is complete
**Then** job status is updated to "FAILED"
**And** error_message: "No JBI regions detected in video"
**And** user is notified via API

**Given** YOLOv8 model is not available
**When** attempting detection
**Then** error is caught and job is retried (max 3 attempts)
**And** after max retries, status is FAILED with error details

**Technical Notes:**
- Follow VideoDetector3.ipynb implementation exactly
- Load model once and reuse (singleton pattern)
- Support GPU if available, fallback to CPU
- Minimum segment duration: 5 seconds (configurable)

---

#### Story 2.6: ASR Worker - faster-whisper Integration

As a system,
I want to transcribe audio from cropped segments using faster-whisper,
So that synchronized transcripts can be generated.

**Acceptance Criteria:**

**Given** segments are ready for ASR processing
**When** the ASRWorker picks up the job
**Then** the worker downloads each cropped segment from MinIO
**And** runs faster-whisper transcription (from asr_code.ipynb)
**And** generates segments.txt format: `[start -> end] transcript text`

**Given** ASR configuration specifies model size
**When** transcription runs
**Then** the specified model is used (tiny/base/small/medium/large-v3)
**And** compute type is applied (int8/float16/int8_float16)

**Given** ASR transcription completes
**When** results are processed
**Then** each segment's asr_text, asr_start, asr_end are saved
**And** confidence scores are stored (FR49)
**And** job status is updated to "CROPPING"
**And** next stage is queued for timestamp-based cropping

**Given** ASR produces low confidence segments (< 0.5)
**When** results are saved
**Then** segments are flagged for potential ASR Review
**And** confidence scores are available for annotator review

**Given** audio codec is unsupported
**When** transcription fails
**Then** error is classified as permanent (no retry)
**And** job status is FAILED with "Audio codec not supported"

**Technical Notes:**
- Follow asr_code.ipynb implementation exactly
- Use faster-whisper, not OpenAI Whisper API
- Extract audio using FFmpeg before ASR
- Support Indonesian language (auto-detect or specify)

---

#### Story 2.7: Cropping Worker - JBI Buffer

As a system,
I want to re-crop segments based on ASR timestamps with JBI buffer,
So that final clips include full sign language context.

**Acceptance Criteria:**

**Given** ASR transcription is complete for all segments
**When** the CroppingWorker picks up the job
**Then** for each segment, calculate JBI time range:
  - jbi_start = max(0, asr_start - 2)
  - jbi_end = min(video_duration, asr_end + 2)

**Given** JBI time ranges are calculated
**When** re-cropping is performed
**Then** FFmpeg extracts the exact time range from original cropped clip
**And** final cropped clips are uploaded to MinIO
**And** jbi_start and jbi_end are saved to pipeline_segments

**Given** all segments are processed
**When** cropping is complete
**Then** job status is updated to "READY_FOR_ANNOTATION"
**And** annotation queue entry is created for annotators

**Given** a segment's calculated duration is < 3 seconds
**When** cropping is performed
**Then** adjacent segments may be merged (configurable)
**And** warning is logged for very short segments

**Given** FFmpeg fails to crop a segment
**When** error occurs
**Then** the specific segment is marked as failed
**And** other segments continue processing
**And** job partially completes with error details

**Technical Notes:**
- Follow cv_asr_annotation.ipynb Stage 2 exactly
- Use FFmpeg with precise seeking (-ss before -i for accuracy)
- Preserve original video quality
- Store final clip paths in pipeline_segments.cropped_video_path

---

#### Story 2.8: Job Status API & Polling

As a user,
I want to check the status of my video processing job,
So that I know when it's ready for annotation.

**Acceptance Criteria:**

**Given** I have a valid job_id
**When** I GET `/api/v1/jobs/{job_id}`
**Then** I receive job details within 200ms:
  - id, status, current_stage, created_at, updated_at
  - progress percentage (optional)
  - error_message (if failed)

**Given** I request job status
**When** the job is in "DETECTING" stage
**Then** I see current_stage: "DETECTING"
**And** status: "PROCESSING"

**Given** I poll for status repeatedly
**When** multiple requests are made
**Then** responses are cached for 2 seconds (NFR3)
**And** rate limiting prevents abuse

**Given** I want to see all my jobs
**When** I GET `/api/v1/jobs` with my auth token
**Then** I receive a list of jobs I created
**And** results are paginated

**Given** I am an admin
**When** I GET `/api/v1/jobs`
**Then** I see all jobs from all users
**And** I can filter by status, user, date range

**Technical Notes:**
- Implement caching layer (Redis or in-memory)
- Cache key: job_status:{job_id}
- TTL: 2 seconds
- Use FastAPI dependency for caching

---

#### Story 2.9: Job Cancellation

As a user,
I want to cancel a video processing job,
So that I can stop processing if I made a mistake.

**Acceptance Criteria:**

**Given** I have a job in "QUEUED" status
**When** I DELETE `/api/v1/jobs/{job_id}`
**Then** the job status is updated to "CANCELLED"
**And** associated queue jobs are marked cancelled
**And** I receive 200 confirmation

**Given** I have a job in "DETECTING" or "TRANSCRIBING" status
**When** I request cancellation
**Then** cancellation signal is sent to worker
**And** job stops at next checkpoint
**And** status is updated to "CANCELLED"

**Given** I have a job in "COMPLETED" or "FAILED" status
**When** I attempt cancellation
**Then** I receive 400 response with error "Cannot cancel completed job"

**Given** I attempt to cancel another user's job
**When** I am not an admin
**Then** I receive 403 response with error "Not authorized"

**Given** a job is cancelled
**When** workers check job status
**Then** they detect cancellation and stop processing
**And** partial results may be preserved

**Technical Notes:**
- Implement cancellation token pattern
- Workers check cancellation flag periodically
- Allow force-cancel for stuck jobs (admin only)

---

#### Story 2.10: Health Check & System Monitoring

As an admin,
I want to monitor system health and configure pipeline parameters,
So that I can ensure smooth operation.

**Acceptance Criteria:**

**Given** I access the system
**When** I GET `/api/v1/health`
**Then** I receive health status:
  - api: "healthy"
  - database: "connected" | "disconnected"
  - minio: "connected" | "disconnected"
  - yolo_model: "loaded" | "not_loaded"
  - gpu_available: true | false
  - disk_space: "OK" | "low" | "critical"

**Given** I am an admin
**When** I GET `/api/v1/admin/system/config`
**Then** I see current pipeline parameters:
  - min_segment_duration
  - max_concurrent_jobs
  - queue_max_depth
  - asr_model_default

**Given** I am an admin
**When** I PUT `/api/v1/admin/system/config` with new parameters
**Then** parameters are updated in config_pipeline_params table
**And** new values take effect for future jobs
**And** current jobs continue with previous values

**Given** I am an admin
**When** I GET `/api/v1/admin/system/metrics`
**Then** I see system metrics:
  - jobs_completed_today
  - jobs_failed_today
  - average_processing_time
  - queue_depth_by_stage
  - gpu_utilization

**Given** jobs have failed
**When** I GET `/api/v1/admin/jobs/failed`
**Then** I see list of failed jobs with:
  - job_id, error_message, failed_at, stage
  - retry count
  - option to retry manually

**Technical Notes:**
- Health checks should be lightweight
- Cache health status for 30 seconds
- Metrics aggregated from pipeline_jobs table
- Config changes require audit log entry

---

### Epic 2 Summary
- **Total Stories:** 10
- **FRs Covered:** 17/17 (100%)
- **Key Deliverables:**
  - Complete pipeline database schema
  - MinIO storage integration
  - 3-stage ML processing workers
  - Job status API with caching
  - System monitoring and configuration

---

## Epic 3: Annotation Workflow

### Epic Goal
Annotators can review and correct synchronized video-transcript pairs with optional pre-annotation ASR validation.

### FRs Covered
FR19-FR23, FR45-FR49 (14 FRs)

### Stories

#### Story 3.1: Database Schema - Annotation Domain

As a developer,
I want to create the annotation database schema,
So that annotation edits and reviews can be stored and tracked.

**Acceptance Criteria:**

**Given** the database migration system is initialized
**When** I run the annotation domain migration
**Then** the following tables are created:
  - `annotation_edits` (id, segment_id, editor_id, old_text, new_text, old_start, old_end, new_start, new_end, edited_at)
  - `annotation_reviews` (id, edit_id, curator_id, status, feedback, reviewed_at)
  - `annotation_comments` (id, edit_id, user_id, comment, created_at)
  - `asr_reviews` (id, segment_id, reviewer_id, original_text, corrected_text, status, confidence_score, reviewed_at)
  - `annotation_queue` (id, segment_id, annotator_id, status, priority, assigned_at, due_date)

**And** foreign keys link to pipeline_segments and auth_users
**And** appropriate indexes support queue queries

**Technical Notes:**
- Edit status: pending, submitted, approved, rejected
- ASR review status: pending, approved, corrected, flagged
- Queue status: assigned, in_progress, completed
- Soft delete for edits (keep history)

---

#### Story 3.2: Annotation Queue API

As an annotator,
I want to see my assigned annotation queue,
So that I know which videos need my attention.

**Acceptance Criteria:**

**Given** I am authenticated as an annotator
**And** segments are assigned to me in annotation_queue
**When** I GET `/api/v1/annotations/queue`
**Then** I receive a list of segments assigned to me:
  - segment_id, video_preview_url, status, priority, assigned_at
  - job metadata (original video name, duration)
  - current transcript text

**Given** I have segments in my queue
**When** I GET `/api/v1/annotations/queue` with filter `status=assigned`
**Then** I see only segments not yet started

**Given** I click on a segment to annotate
**When** I GET `/api/v1/segments/{segment_id}`
**Then** I receive complete segment details:
  - video_url (pre-signed, 1hr expiry)
  - asr_text, asr_start, asr_end
  - jbi_start, jbi_end (final timestamps)
  - previous edits history (if any)
  - ASR confidence score

**Given** no segments are assigned to me
**When** I view my queue
**Then** I see empty state message: "No annotations assigned. Check back later!"

**Given** I am a curator
**When** I attempt to access annotator queue
**Then** I receive 403 response (different endpoint for curators)

**Technical Notes:**
- Queue assignment logic: round-robin or workload-based
- Pre-signed URLs refresh on each request
- Include pagination for large queues

---

#### Story 3.3: Submit Annotation Edit

As an annotator,
I want to edit transcript text and timestamps,
So that I can correct synchronization errors.

**Acceptance Criteria:**

**Given** I am viewing a segment
**When** I POST `/api/v1/annotations/{segment_id}/edits` with:
  - new_text: "corrected transcript"
  - new_start: 12.5 (seconds)
  - new_end: 18.3 (seconds)
**Then** an annotation_edits record is created
**And** old values are preserved for change tracking
**And** I receive 201 response with edit_id

**Given** I edit the transcript text
**When** changes are saved
**Then** the system records:
  - old_text (from ASR or previous edit)
  - new_text (my correction)
  - editor_id (my user id)
  - edited_at timestamp

**Given** I adjust timestamps using draggable handles
**When** I save the annotation
**Then** new_start and new_end are saved
**And** old_start and old_end are preserved
**And** changes are validated (start < end, within video bounds)

**Given** I submit an edit with invalid timestamps
**When** validation fails
**Then** I receive 400 response with error:
  - "Start time must be less than end time"
  - or "Timestamps must be within video duration"

**Given** I have made multiple edits to the same segment
**When** I view the segment
**Then** I see the most recent edit applied
**And** edit history is available for reference

**Technical Notes:**
- Validate timestamps against jbi_start/jbi_end bounds
- Store timestamps as float (seconds with decimals)
- Support undo/redo within a session
- Auto-save drafts (optional enhancement)

---

#### Story 3.4: Preview and Save Annotations

As an annotator,
I want to preview my changes before final submission,
So that I can verify the synchronization is correct.

**Acceptance Criteria:**

**Given** I have made edits to a segment
**When** I click "Preview" in the interface
**Then** the video player shows the segment with new timestamps
**And** the transcript panel shows the corrected text
**And** I can play the video to verify sync

**Given** I am satisfied with my changes
**When** I click "Save Draft"
**Then** edits are saved but not submitted for review
**And** segment status remains "in_progress"
**And** I can return to edit later

**Given** I have a saved draft
**When** I return to the segment
**Then** my draft changes are loaded
**And** I can continue editing or discard

**Given** I want to reset my changes
**When** I click "Reset to Original"
**Then** all my edits for this segment are discarded
**And** segment reverts to ASR-original state

**Given** I preview and verify my changes
**When** I click "Submit for Review"
**Then** see Story 3.5 behavior

**Technical Notes:**
- Draft edits stored with status="draft"
- Preview uses same pre-signed URL mechanism
- Reset creates new edit record reverting to original

---

#### Story 3.5: Submit for Review

As an annotator,
I want to submit my completed annotations for curator review,
So that they can be approved for the dataset.

**Acceptance Criteria:**

**Given** I have completed editing a segment
**When** I POST `/api/v1/annotations/{segment_id}/submit`
**Then** segment status changes to "pending_review"
**And** annotation_edits status changes to "submitted"
**And** segment is added to curator review queue
**And** I receive confirmation: "Annotation submitted for review"

**Given** I have multiple segments for the same job
**When** I submit all segments
**Then** each is individually submitted for review
**And** I can track each segment's review status

**Given** I try to submit without any edits
**When** I click submit
**Then** I receive warning: "No changes made. Submit anyway?"
**And** I can confirm or cancel

**Given** I have submitted an annotation
**When** the curator rejects it
**Then** segment returns to my queue with status "needs_revision"
**And** I see curator feedback
**And** I can make further edits and resubmit

**Given** I have submitted an annotation
**When** the curator approves it
**Then** segment status changes to "approved"
**And** it moves to exportable dataset
**And** I see approval notification

**Technical Notes:**
- Submission is irreversible (but can be rejected)
- Track submission timestamp
- Notify curator (in-app notification, future: email)

---

#### Story 3.6: ASR Review Queue (Optional)

As an annotator (ASR Reviewer role),
I want to review ASR-generated transcripts before annotation,
So that I can catch errors early and save annotation time.

**Acceptance Criteria:**

**Given** ASR Review is enabled for the job (configurable)
**When** ASR stage completes
**Then** segments appear in ASR Review queue before Annotation queue

**Given** I am assigned ASR Review role
**When** I GET `/api/v1/asr-review/queue`
**Then** I see segments pending ASR validation:
  - segment_id, video_url, asr_text, confidence_score
  - low confidence segments flagged

**Given** I open a segment for ASR review
**When** I view the interface
**Then** I see:
  - Video player with the segment
  - ASR transcript displayed
  - Confidence score visible
  - Edit interface for corrections

**Given** I am reviewing a low-confidence segment
**When** confidence < 0.5
**Then** the segment is visually flagged (warning icon)
**And** I am prompted to pay extra attention

**Given** ASR Review is disabled for the job
**When** ASR completes
**Then** segments go directly to Annotation queue
**And** ASR Review queue is skipped

**Technical Notes:**
- ASR Review is optional per-job configuration
- Parallel to annotation (doesn't block)
- Can be done by same annotators or dedicated reviewers
- Configurable via `config_pipeline_params.asr_review_enabled`

---

#### Story 3.7: ASR Approval and Flagging

As an ASR reviewer,
I want to approve, correct, or flag ASR segments,
So that only quality transcripts enter the annotation workflow.

**Acceptance Criteria:**

**Given** I have reviewed an ASR segment
**When** I POST `/api/v1/asr-review/{segment_id}/approve`
**Then** asr_reviews record is created with status "approved"
**And** segment moves to Annotation queue
**And** ASR text is used as-is

**Given** I find errors in ASR transcript
**When** I POST `/api/v1/asr-review/{segment_id}/correct` with:
  - corrected_text: "fixed transcript"
**Then** asr_reviews record is created with status "corrected"
**And** corrected_text is used for annotation
**And** original ASR is preserved for reference

**Given** I encounter a problematic segment
**When** I POST `/api/v1/asr-review/{segment_id}/flag` with:
  - issue_type: "background_noise" | "overlapping_speech" | "unclear_audio"
  - notes: "description of issue"
**Then** asr_reviews record is created with status "flagged"
**And** segment is marked for manual transcription
**And** job admin is notified

**Given** I flag a segment
**When** it is reprocessed or manually transcribed
**Then** it returns to ASR Review queue
**And** I can review the corrected version

**Given** multiple ASR reviewers exist
**When** a segment is reviewed
**Then** only one review is accepted
**And** others see "Already reviewed" status

**Technical Notes:**
- Track reviewer_id for accountability
- Flag reasons are enumerable (not free text)
- Flagged segments can be routed to specialized transcribers

---

#### Story 3.8: ASR Confidence Scores

As a system,
I want to store and display ASR confidence scores,
So that reviewers can prioritize low-confidence segments.

**Acceptance Criteria:**

**Given** ASR transcription completes
**When** results are processed
**Then** confidence scores are extracted from faster-whisper
**And** stored in pipeline_segments.asr_confidence (0.0 - 1.0)

**Given** a segment has low confidence (< 0.5)
**When** displayed in ASR Review queue
**Then** it is sorted higher (priority review)
**And** visually highlighted (red/orange indicator)

**Given** a segment has high confidence (> 0.9)
**When** displayed
**Then** it may be auto-approved (configurable)
**Or** shown with green indicator for quick review

**Given** I am an annotator
**When** I view a segment in annotation queue
**Then** I see the ASR confidence score
**And** I understand the transcript may need more attention if low

**Given** I am an admin
**When** I view system metrics
**Then** I see average ASR confidence across all jobs
**And** I can identify jobs with unusually low confidence

**Technical Notes:**
- Confidence score comes from faster-whisper segment-level output
- Store as float (0.0 to 1.0)
- Configurable thresholds for auto-approval

---

### Epic 3 Summary
- **Total Stories:** 8
- **FRs Covered:** 14/14 (100%)
- **Key Deliverables:**
  - Complete annotation database schema
  - Annotator queue and assignment system
  - Edit tracking with change history
  - Optional ASR Review workflow
  - Confidence-based prioritization

---

## Epic 4: Curation & Export

### Epic Goal
Curators can review, approve/reject annotations, normalize Indonesian slang, and export datasets for training.

### FRs Covered
FR24-FR30, FR41-FR44, FR50-FR54 (21 FRs)

### Stories

#### Story 4.1: Curator Review Queue API

As a curator,
I want to see all pending annotations for review,
So that I can efficiently manage the review queue.

**Acceptance Criteria:**

**Given** I am authenticated as a curator
**When** I GET `/api/v1/curator/queue`
**Then** I receive a list of annotations pending review:
  - annotation_id, segment_id, annotator_name, submitted_at
  - video_preview_url, current_transcript, changes_summary
  - job_info (source video, duration)

**Given** annotations are in the queue
**When** I view an annotation detail
**Then** I see side-by-side comparison:
  - Left: Original ASR text and timestamps
  - Right: Annotator's corrected text and timestamps
  - Highlighted differences (changed words, adjusted times)

**Given** I am reviewing an annotation
**When** I play the video
**Then** it plays with the annotator's corrected timestamps
**And** the transcript highlights as video plays

**Given** I want to filter the queue
**When** I apply filters (date range, annotator, job)
**Then** filtered results are returned
**And** pagination is supported

**Given** I am an annotator
**When** I attempt to access curator queue
**Then** I receive 403 response

**Technical Notes:**
- Queue sorted by submitted_at (oldest first)
- Highlight changes using diff algorithm
- Pre-signed URLs for video playback
- Support batch operations (future enhancement)

---

#### Story 4.2: Approve and Reject Annotations

As a curator,
I want to approve or reject annotations with feedback,
So that quality control is maintained.

**Acceptance Criteria:**

**Given** I am reviewing an annotation
**When** I POST `/api/v1/curator/reviews/{annotation_id}/approve`
**Then** annotation_reviews record is created with status "approved"
**And** segment status changes to "approved"
**And** segment moves to exportable dataset
**And** annotator receives notification

**Given** I find issues with an annotation
**When** I POST `/api/v1/curator/reviews/{annotation_id}/reject` with:
  - feedback: "Timestamp at 00:15 is incorrect, sign starts at 00:17"
**Then** annotation_reviews record is created with status "rejected"
**And** segment status changes to "needs_revision"
**And** segment returns to annotator's queue
**And** annotator sees feedback

**Given** I reject an annotation
**When** the annotator views it
**Then** they see my feedback prominently
**And** they can make corrections and resubmit

**Given** I want to provide additional guidance
**When** I add a comment to the review
**Then** comment is stored in annotation_comments table
**And** visible to annotator

**Given** I approve a rejected annotation (after revision)
**When** I review the resubmission
**Then** I can approve it
**And** it moves to exportable dataset

**Given** I want to see my review history
**When** I GET `/api/v1/curator/reviews`
**Then** I see all my approvals and rejections
**And** statistics on my review activity

**Technical Notes:**
- Track curator_id for accountability
- Feedback is required for rejections
- Support rejection categories (future)
- Notify annotator via in-app notification

---

#### Story 4.3: Slang Dictionary Management

As a curator,
I want to view and manage the slang-to-standard dictionary,
So that I can normalize Indonesian slang during curation.

**Acceptance Criteria:**

**Given** I am in the curation interface
**When** I open the slang dictionary panel
**Then** I see a searchable list of slang mappings:
  - slang: "enggak", standard: "tidak"
  - slang: "udah", standard: "sudah"
  - (and 15+ other entries)

**Given** I am reviewing a transcript
**When** slang words are detected
**Then** they are highlighted in the interface
**And** standard equivalents are suggested

**Given** I find slang not in dictionary
**When** I add a new entry
**Then** POST `/api/v1/config/slang-dictionary` creates:
  - slang: "gamau"
  - standard: "tidak mau"
  - added_by: my_user_id
  - created_at: current timestamp

**Given** I find an incorrect mapping
**When** I update the entry
**Then** PUT `/api/v1/config/slang-dictionary/{id}` updates:
  - standard: "new correction"
  - updated_at: current timestamp

**Given** I am an admin
**When** I manage the dictionary
**Then** I can also delete entries
**And** view usage statistics per entry

**Given** I am an annotator
**When** I attempt to modify dictionary
**Then** I receive 403 response (curator/admin only)

**Technical Notes:**
- Dictionary stored in config_slang_dictionary table
- Slang matching is case-insensitive
- Support multi-word slang phrases
- Track who added each entry

---

#### Story 4.4: Auto-Normalization Engine

As a curator,
I want to automatically normalize slang to standard Indonesian,
So that I can save time during curation.

**Acceptance Criteria:**

**Given** I am reviewing an annotation with slang
**When** I click "Auto-Normalize"
**Then** the system scans transcript for slang words
**And** replaces them with standard equivalents from dictionary
**And** shows me a diff of changes

**Given** auto-normalization runs
**When** slang "enggak" is found
**Then** it is replaced with "tidak"
**And** original is preserved for reference

**Given** I review the normalized text
**When** I see an incorrect normalization
**Then** I can manually override it
**And** my correction is saved

**Given** I approve the normalized text
**When** I submit the review
**Then** the normalized version is used
**And** normalization decisions are logged

**Given** a slang word has multiple possible standards
**When** auto-normalization runs
**Then** I am prompted to choose
**Or** the most common choice is used (configurable)

**Given** no slang is detected
**When** I run auto-normalization
**Then** I see message: "No slang detected"
**And** transcript is unchanged

**Technical Notes:**
- Text replacement preserves punctuation
- Word-boundary matching (don't match partial words)
- Case preservation ("Enggak" → "Tidak")
- Store normalization history

---

#### Story 4.5: Learning from Corrections

As a system,
I want to learn from curator corrections to improve future normalizations,
So that the slang dictionary becomes more accurate over time.

**Acceptance Criteria:**

**Given** a curator overrides an auto-normalization
**When** the correction is saved
**Then** the system logs:
  - original_slang: "enggak"
  - auto_normalized: "tidak"
  - curator_correction: "tidak"
  - was_override: false (if same) or true (if different)

**Given** curators consistently override a specific mapping
**When** override_count > threshold (e.g., 5)
**Then** admin is notified: "Mapping 'enggak' → 'tidak' frequently overridden"

**Given** I am an admin
**When** I view normalization analytics
**Then** I see:
  - Most common slang terms
  - Override rates per mapping
  - Suggested dictionary updates

**Given** the system has learned patterns
**When** new slang is added
**Then** similar patterns are suggested for consistency

**Technical Notes:**
- MVP: Basic logging only
- Post-MVP: ML-based learning
- Track confidence scores for mappings
- Allow admin to approve learned updates

---

#### Story 4.6: Dataset Export

As a curator,
I want to export approved segments as structured datasets,
So that they can be used for training SIBI models.

**Acceptance Criteria:**

**Given** segments are approved
**When** I POST `/api/v1/export` with:
  - job_ids: ["uuid1", "uuid2"] (optional, all if empty)
  - format: "json"
  - include_metadata: true
**Then** a dataset export is generated

**Given** I export to JSON format
**When** download is ready
**Then** the file contains array of segment objects:
```json
{
  "segment_id": "uuid",
  "video_path": "minio://jobs/...",
  "transcript": "corrected text",
  "start_time": 12.5,
  "end_time": 18.3,
  "metadata": {
    "original_video": "news_2024.mp4",
    "annotator": "Rina",
    "curator": "Pak Budi",
    "approved_at": "2026-03-18T10:00:00Z"
  }
}
```

**Given** I request export
**When** processing completes
**Then** I receive download URL (pre-signed, 24hr expiry)
**And** export is logged in audit trail

**Given** I want to filter export
**When** I specify date range, annotator, or curator
**Then** only matching segments are included

**Given** I am not a curator
**When** I attempt to export
**Then** I receive 403 response

**Given** no approved segments match criteria
**When** I request export
**Then** I receive 404 response: "No approved segments found"

**Technical Notes:**
- Support formats: JSON (MVP), XML, CSV (future)
- Export runs asynchronously for large datasets
- Include checksum for file integrity
- Archive old exports (configurable retention)

---

### Epic 4 Summary
- **Total Stories:** 6
- **FRs Covered:** 21/21 (100%)
- **Key Deliverables:**
  - Curator review queue with change highlighting
  - Approve/reject workflow with feedback
  - Slang dictionary management
  - Auto-normalization engine
  - Dataset export (JSON)

---

## Epic 5: Audit & Compliance

### Epic Goal
Admins can view complete, immutable audit trails of all system actions for compliance and accountability.

### FRs Covered
FR39, FR44, FR55-FR59 (7 FRs)

### Stories

#### Story 5.1: Database Schema - Audit Domain

As a developer,
I want to create the audit database schema,
So that all system actions can be logged and tracked immutably.

**Acceptance Criteria:**

**Given** the database migration system is initialized
**When** I run the audit domain migration
**Then** the following tables are created:
  - `audit_logs` (id, timestamp, user_id, action, resource_type, resource_id, details, ip_address, user_agent)
  - `audit_state_transitions` (id, job_id, from_state, to_state, triggered_by, timestamp, reason)

**And** appropriate indexes are created:
  - Index on timestamp for time-range queries
  - Index on user_id for user activity queries
  - Index on resource_type and resource_id for resource tracking

**And** table constraints ensure:
  - No UPDATE operations allowed (immutable)
  - No DELETE operations allowed (retention compliance)

**Technical Notes:**
- Use append-only pattern
- Consider partitioning by timestamp for large datasets
- Archive old logs to cold storage (future)
- GDPR compliance for IP retention (configurable)

---

#### Story 5.2: Audit Logging Middleware

As a system,
I want to automatically log all user actions,
So that a complete audit trail is maintained.

**Acceptance Criteria:**

**Given** a user performs an action
**When** any API endpoint is called
**Then** an audit log entry is created with:
  - timestamp: current UTC time
  - user_id: authenticated user (or "anonymous")
  - action: HTTP method + endpoint path
  - resource_type: entity type (job, annotation, user)
  - resource_id: affected entity ID
  - details: request payload (sanitized)
  - ip_address: client IP
  - user_agent: browser/client info

**Given** a user creates a job
**When** POST `/api/v1/jobs` succeeds
**Then** audit log entry:
  - action: "POST /api/v1/jobs"
  - resource_type: "job"
  - resource_id: new job UUID
  - details: {"filename": "video.mp4"}

**Given** a curator approves an annotation
**When** POST `/api/v1/curator/reviews/{id}/approve` succeeds
**Then** audit log entry:
  - action: "APPROVE_ANNOTATION"
  - resource_type: "annotation"
  - resource_id: annotation UUID
  - details: {"curator_id": "...", "annotator_id": "..."}

**Given** sensitive data is in request payload
**When** logging occurs
**Then** passwords and tokens are redacted
**And** PII is masked according to policy

**Given** an action fails
**When** error response is returned
**Then** audit log still captures the attempt
**And** includes error_code in details

**Technical Notes:**
- Use FastAPI middleware for automatic logging
- Log asynchronously to avoid blocking requests
- Batch insert for high-volume scenarios
- Exclude health check endpoints from logging

---

#### Story 5.3: State Transition Tracking

As a system,
I want to track all job state transitions,
So that the complete lifecycle of each video is auditable.

**Acceptance Criteria:**

**Given** a job changes state
**When** transition occurs (e.g., UPLOADED → QUEUED)
**Then** an audit_state_transitions record is created:
  - job_id: job UUID
  - from_state: "UPLOADED"
  - to_state: "QUEUED"
  - triggered_by: "system" | user_id
  - timestamp: transition time
  - reason: "Job queued for processing" (optional)

**Given** I view a job's history
**When** I GET `/api/v1/jobs/{id}/history`
**Then** I see complete state transition timeline:
```
UPLOADED → QUEUED (system, 10:00:00)
QUEUED → DETECTING (system, 10:00:05)
DETECTING → TRANSCRIBING (system, 10:05:30)
TRANSCRIBING → CROPPING (system, 10:15:45)
CROPPING → READY_FOR_ANNOTATION (system, 10:20:10)
```

**Given** a curator approves a segment
**When** status changes to "approved"
**Then** transition is logged with triggered_by: curator_user_id

**Given** a user cancels a job
**When** status changes to "CANCELLED"
**Then** transition is logged with:
  - triggered_by: user_id who cancelled
  - reason: "User requested cancellation"

**Given** a job fails
**When** status changes to "FAILED"
**Then** transition is logged with:
  - from_state: previous processing state
  - to_state: "FAILED"
  - reason: error message

**Technical Notes:**
- Integrate with job state machine
- Log before state change (atomic transaction)
- Support querying by date range
- Export transition history with job export

---

#### Story 5.4: Audit Log Query API

As an admin,
I want to query and filter audit logs,
So that I can investigate issues and ensure compliance.

**Acceptance Criteria:**

**Given** I am authenticated as an admin
**When** I GET `/api/v1/admin/audit-logs`
**Then** I receive paginated audit log entries:
  - timestamp, user_id, action, resource_type, resource_id, details

**Given** I want to filter by date range
**When** I add query params `from=2026-03-01&to=2026-03-18`
**Then** only logs within that range are returned

**Given** I want to filter by user
**When** I add query param `user_id=uuid-123`
**Then** only that user's actions are shown

**Given** I want to filter by action type
**When** I add query param `action=APPROVE_ANNOTATION`
**Then** only approval actions are shown

**Given** I want to filter by resource
**When** I add query param `resource_type=job&resource_id=uuid-456`
**Then** only actions on that specific job are shown

**Given** I combine multiple filters
**When** I query with `user_id=X&from=Y&action=Z`
**Then** all filters are applied (AND logic)

**Given** audit logs are extensive
**When** I query without filters
**Then** results are paginated (default: 50 per page)
**And** I can specify `page` and `page_size` params

**Given** I want to export audit logs
**When** I request export (future feature)
**Then** logs are exported in CSV/JSON format

**Given** I am not an admin
**When** I attempt to access audit logs
**Then** I receive 403 response

**Technical Notes:**
- Support sorting by timestamp (desc default)
- Maximum page size: 1000 (prevent abuse)
- Query optimization for date range (use index)
- Response time < 500ms for typical queries

---

#### Story 5.5: Per-User Activity Metrics

As an admin,
I want to view per-user activity metrics,
So that I can monitor team productivity and workload.

**Acceptance Criteria:**

**Given** I am authenticated as an admin
**When** I GET `/api/v1/admin/users/{id}/metrics`
**Then** I see activity summary for the user:
  - total_annotations_completed
  - total_reviews_conducted (if curator)
  - average_time_per_annotation
  - approval_rate (for curators)
  - last_active_timestamp

**Given** I view metrics
**When** I specify `period=7d` query param
**Then** metrics are calculated for last 7 days only

**Given** I want to compare users
**When** I GET `/api/v1/admin/metrics/leaderboard`
**Then** I see ranked list of annotators by productivity

**Given** I want to see system-wide metrics
**When** I GET `/api/v1/admin/metrics/dashboard`
**Then** I see:
  - Total videos processed (today/this week/this month)
  - Total annotations completed
  - Average processing time per video
  - Pipeline stage breakdown (detection, ASR, cropping times)
  - Error rates by stage

**Given** metrics are queried
**When** database is large
**Then** results are cached for 5 minutes
**And** cache is keyed by user + period

**Given** I am a user
**When** I access my own metrics endpoint
**Then** I see only my own metrics
**And** I cannot access other users' metrics

**Technical Notes:**
- Aggregate from audit_logs and pipeline_jobs tables
- Cache expensive queries
- Support custom date ranges
- Export metrics as reports (future)

---

### Epic 5 Summary
- **Total Stories:** 5
- **FRs Covered:** 7/7 (100%)
- **Key Deliverables:**
  - Immutable audit log schema
  - Automatic action logging middleware
  - Job state transition tracking
  - Audit log query API with filtering
  - Per-user and system-wide metrics

---

## Epic 6: User Onboarding

### Epic Goal
First-time users receive guided tours and contextual help to effectively use the platform.

### FRs/NFRs Covered
FR60-FR63, NFR18-NFR23 (10 total)

### Stories

#### Story 6.1: Interactive Tour System

As a first-time user,
I want to take a guided tour of the platform,
So that I can learn how to use the annotation and curation workflows.

**Acceptance Criteria:**

**Given** I log in for the first time
**When** the dashboard loads
**Then** I see a welcome modal: "Welcome to Anotasi.ai! Take a tour to get started?"
**And** I can accept, decline, or postpone

**Given** I accept the tour
**When** the tour starts
**Then** I see a step-by-step guided walkthrough:
  - Step 1: "This is your dashboard showing assigned work"
  - Step 2: "Click here to start annotating"
  - Step 3: "This is the video player with sync controls"
  - Step 4: "Edit transcripts here"
  - Step 5: "Submit when done"

**Given** I am taking the tour
**When** I click "Next"
**Then** the tour highlights the next UI element
**And** shows explanatory tooltip

**Given** I am taking the tour
**When** I click "Skip"
**Then** the tour ends
**And** my preference is saved (don't show again)

**Given** different user roles
**When** they take the tour
**Then** they see role-specific content:
  - Annotators: Annotation workflow tour
  - Curators: Review and approval tour
  - Admins: User management and monitoring tour

**Given** I declined or skipped the initial tour
**When** I navigate to help
**Then** I can restart the tour from: `/help/restart-tour`

**Given** I complete the tour
**When** I finish the final step
**Then** I see: "Tour complete! You're ready to start."
**And** tour completion is recorded

**Technical Notes:**
- Use React Joyride or Shepherd.js
- Store tour state in user profile
- Support keyboard navigation (arrow keys, Escape)
- Mobile-responsive tour steps

---

#### Story 6.2: Help Documentation

As a user,
I want to access help documentation at any time,
So that I can reference instructions when needed.

**Acceptance Criteria:**

**Given** I am logged in
**When** I click the "Help" button
**Then** a help panel or modal opens with:
  - Search bar for finding topics
  - Categories: Getting Started, Annotation, Curation, Admin
  - Quick links to common questions

**Given** I search for a topic
**When** I type "keyboard shortcuts"
**Then** relevant help articles are displayed
**And** I can click to view full article

**Given** I am on the annotation page
**When** I open help
**Then** annotation-specific help is shown first
**And** I see: "How to adjust timestamps", "Keyboard shortcuts"

**Given** I am on the curation page
**When** I open help
**Then** curation-specific help is shown first
**And** I see: "How to approve/reject", "Using slang dictionary"

**Given** I want detailed documentation
**When** I click "Full Documentation"
**Then** I am taken to docs site (or in-app docs)
**With** comprehensive guides and screenshots

**Given** I can't find what I need
**When** I click "Contact Support"
**Then** a support form or email opens
**With** context (current page, user info) pre-filled

**Given** I found help useful
**When** I close the help panel
**Then** my last viewed topic is remembered

**Technical Notes:**
- Help content stored in markdown files
- Search using simple text matching (MVP) or Algolia (future)
- Context-aware help based on current route
- Offline help documentation available

---

#### Story 6.3: Contextual Tooltips

As a user,
I want contextual tooltips on complex interface elements,
So that I understand what each control does.

**Acceptance Criteria:**

**Given** I hover over a complex control
**When** delay of 500ms passes
**Then** a tooltip appears explaining the control:
  - "Drag to adjust start time"
  - "Click to play video at this timestamp"
  - "Approve: Mark annotation as complete"

**Given** I see a tooltip
**When** I move mouse away
**Then** tooltip disappears after 200ms

**Given** I am on mobile/touch device
**When** I long-press a control
**Then** tooltip appears (touch-friendly alternative)

**Given** complex forms or workflows
**When** page loads
**Then** info icons (ⓘ) appear next to complex fields
**And** clicking shows detailed explanation

**Given** I am in annotation interface
**When** I hover over timestamp handles
**Then** tooltip shows: "Drag to adjust segment boundaries"

**Given** I am in curation interface
**When** I hover over slang dictionary button
**Then** tooltip shows: "View and manage Indonesian slang mappings"

**Given** I want to disable tooltips
**When** I toggle "Show tooltips" in settings
**Then** tooltips are disabled/enabled per preference

**Technical Notes:**
- Use React Tooltip or Tippy.js
- Support ARIA labels for accessibility
- Position tooltips intelligently (avoid viewport overflow)
- Allow HTML content in tooltips for rich formatting

---

#### Story 6.4: Accessibility Compliance

As a user with disabilities,
I want the interface to meet WCAG 2.1 Level AA standards,
So that I can use the platform effectively.

**Acceptance Criteria:**

**Given** I use a screen reader
**When** I navigate the interface
**Then** all interactive elements have ARIA labels
**And** status changes are announced ("Job processing complete")

**Given** I use keyboard navigation
**When** I press Tab
**Then** focus moves to next interactive element
**And** focus is visually indicated (outline or highlight)

**Given** I am on the annotation page
**When** I use keyboard shortcuts
**Then** I can:
  - Space: Play/Pause video
  - Left/Right arrows: Seek -5s/+5s
  - Shift + Left/Right: Adjust start/end timestamp
  - Escape: Close modals

**Given** I view text content
**Then** contrast ratio is at least 4.5:1 (WCAG AA)
**And** text can be resized to 200% without breaking layout

**Given** I use touch device
**When** I interact with buttons
**Then** touch targets are at least 44x44px
**And** adequate spacing between touch targets

**Given** I have color vision deficiency
**When** I view status indicators
**Then** information is conveyed by more than just color
**And** icons/text accompany color coding

**Given** I want to adjust playback speed
**When** I access video player controls
**Then** I can select: 0.5x, 0.75x, 1x, 1.25x, 1.5x
**And** preference is remembered

**Given** I use the interface
**When** animations play
**Then** they respect `prefers-reduced-motion` setting
**And** I can disable animations in settings

**Given** accessibility audit is performed
**Then** WCAG 2.1 Level AA compliance is verified
**And** any violations are documented and fixed

**Technical Notes:**
- Use semantic HTML elements
- Implement focus management for modals
- Test with screen readers (NVDA, VoiceOver)
- Automated testing with axe-core or similar
- Color contrast checking tools

---

### Epic 6 Summary
- **Total Stories:** 4
- **FRs/NFRs Covered:** 10/10 (100%)
- **Key Deliverables:**
  - Interactive guided tours by role
  - Contextual help documentation
  - Tooltip system for complex controls
  - WCAG 2.1 Level AA accessibility compliance

---

## Overall Epic Summary

| Epic | Title | Stories | FRs Covered | Key Deliverable |
|------|-------|---------|-------------|-----------------|
| 1 | Foundation & Authentication | 9 | 11 | Complete auth system with RBAC |
| 2 | Video Processing Pipeline | 10 | 17 | 3-stage ML pipeline (YOLOv8 → ASR → Crop) |
| 3 | Annotation Workflow | 8 | 14 | Annotator tools with optional ASR Review |
| 4 | Curation & Export | 6 | 21 | Review, slang normalization, JSON export |
| 5 | Audit & Compliance | 5 | 7 | Immutable audit logs, metrics |
| 6 | User Onboarding | 4 | 10 | Tours, help, accessibility (WCAG AA) |
| **Total** | | **42** | **63 FRs** | |

---

## Implementation Order

**Phase 1 (Foundation):**
1. Epic 1: Foundation & Authentication
2. Epic 2: Video Processing Pipeline

**Phase 2 (Core Workflows):**
3. Epic 3: Annotation Workflow
4. Epic 4: Curation & Export

**Phase 3 (Polish):**
5. Epic 5: Audit & Compliance
6. Epic 6: User Onboarding

---
