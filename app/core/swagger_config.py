"""
Swagger/OpenAPI Configuration Module.

This module provides configuration for Swagger UI, ReDoc, and OpenAPI schema generation.
It includes security schemes, tag metadata, and documentation utilities.
"""

from typing import Dict, Any, List


# ============================================================================
# Tag Metadata for Organized API Documentation
# ============================================================================

TAGS_METADATA: List[Dict[str, str]] = [
    {
        "name": "health",
        "description": """
        Health check and system status endpoints.
        
        Use these endpoints to monitor system health and for load balancer health checks.
        """,
    },
    {
        "name": "authentication",
        "description": """
        User authentication and account management.
        
        - **Login**: Obtain JWT access and refresh tokens
        - **Register**: Create new user accounts
        - **Verify Email**: Confirm email addresses
        - **Password Reset**: Recover forgotten passwords
        - **Token Refresh**: Get new access tokens using refresh tokens
        - **Logout**: Revoke tokens and end sessions
        """,
    },
    {
        "name": "users",
        "description": """
        User profile management.
        
        Endpoints for users to manage their own profiles and account settings.
        """,
    },
    {
        "name": "admin",
        "description": """
        Administrative endpoints for system management.
        
        **Requires admin role.**
        
        ## Available Operations
        
        - User management (list, create, update roles, deactivate)
        - System configuration
        - Monitoring and metrics
        - Failed job inspection
        - ASR confidence statistics
        """,
    },
    {
        "name": "jobs",
        "description": """
        Video processing job management.
        
        ## Workflow
        
        1. **Upload**: Submit video for processing
        2. **Monitor**: Check job status and progress
        3. **Retrieve**: Download processed segments and transcripts
        
        ## Processing Pipeline
        
        Video → JBI Detection → Segmentation → ASR → Review Queue
        """,
    },
    {
        "name": "annotations",
        "description": """
        Annotation workflow for video segments.
        
        ## Workflow Stages
        
        1. **Draft**: Create and save annotation drafts
        2. **Preview**: Verify timestamps with video playback
        3. **Submit**: Send for curator review
        4. **Review**: Curator approves or rejects
        
        ## Status Values
        
        - `DRAFT`: Work in progress
        - `PENDING`: Awaiting submission
        - `SUBMITTED`: Under review
        - `APPROVED`: Accepted
        - `REJECTED`: Needs revision
        """,
    },
    {
        "name": "asr-review",
        "description": """
        ASR (Automatic Speech Recognition) review queue.
        
        ## Purpose
        
        Review and validate automatically generated transcripts for accuracy.
        
        ## Actions
        
        - **Approve**: Transcript is accurate, move to annotation queue
        - **Correct**: Fix errors, then move to annotation queue
        - **Flag**: Mark for reprocessing (poor audio quality, etc.)
        
        ## Confidence Scores
        
        - Low: < 0.5 (flagged for review)
        - Medium: 0.5 - 0.9
        - High: >= 0.9
        """,
    },
]


# ============================================================================
# Security Schemes
# ============================================================================

SECURITY_SCHEMES: Dict[str, Any] = {
    "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": """
        JWT token-based authentication.
        
        ## Usage
        
        Include the token in the Authorization header:
        
        ```
        Authorization: Bearer <your-jwt-token>
        ```
        
        ## Obtaining a Token
        
        1. Call `POST /api/v1/auth/login` with email and password
        2. Use the `access_token` from the response
        3. Token expires after 15 minutes (configurable)
        4. Use `refresh_token` to get a new access token
        
        ## Token Structure
        
        The JWT token contains:
        - `sub`: User ID
        - `role`: User role (admin, annotator, curator)
        - `email`: User email
        - `exp`: Expiration timestamp
        """,
    }
}


# ============================================================================
# Response Examples
# ============================================================================

RESPONSE_EXAMPLES: Dict[str, Any] = {
    "validation_error": {
        "description": "Validation Error",
        "content": {
            "application/json": {
                "example": {
                    "detail": [
                        {
                            "loc": ["body", "email"],
                            "msg": "invalid email format",
                            "type": "value_error.email"
                        }
                    ]
                }
            }
        }
    },
    "unauthorized": {
        "description": "Unauthorized",
        "content": {
            "application/json": {
                "example": {
                    "detail": "Invalid or expired token"
                }
            }
        }
    },
    "forbidden": {
        "description": "Forbidden - Insufficient permissions",
        "content": {
            "application/json": {
                "example": {
                    "detail": "Admin access required"
                }
            }
        }
    },
    "not_found": {
        "description": "Resource not found",
        "content": {
            "application/json": {
                "example": {
                    "detail": "Resource not found"
                }
            }
        }
    },
    "conflict": {
        "description": "Conflict - Resource already exists",
        "content": {
            "application/json": {
                "example": {
                    "detail": "User with this email already exists"
                }
            }
        }
    },
    "rate_limited": {
        "description": "Rate limit exceeded",
        "content": {
            "application/json": {
                "example": {
                    "detail": "Rate limit exceeded. Try again in 15 minutes."
                }
            }
        }
    },
    "server_error": {
        "description": "Internal server error",
        "content": {
            "application/json": {
                "example": {
                    "detail": "An unexpected error occurred"
                }
            }
        }
    },
}


# ============================================================================
# Common Response Models for Swagger
# ============================================================================

COMMON_RESPONSES: Dict[int, Dict[str, Any]] = {
    400: RESPONSE_EXAMPLES["validation_error"],
    401: RESPONSE_EXAMPLES["unauthorized"],
    403: RESPONSE_EXAMPLES["forbidden"],
    404: RESPONSE_EXAMPLES["not_found"],
    409: RESPONSE_EXAMPLES["conflict"],
    429: RESPONSE_EXAMPLES["rate_limited"],
    500: RESPONSE_EXAMPLES["server_error"],
}


# ============================================================================
# Swagger UI Configuration
# ============================================================================

SWAGGER_UI_CONFIG: Dict[str, Any] = {
    "swagger_js_url": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.9.0/swagger-ui-bundle.js",
    "swagger_css_url": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.9.0/swagger-ui.css",
    "swagger_favicon_url": "https://fastapi.tiangolo.com/img/favicon.png",
    "init_oauth": {
        "clientId": "jbi-api-client",
        "appName": "JBI Detection & Segmentation API",
        "usePkceWithAuthorizationCodeGrant": True,
    },
}

REDOC_CONFIG: Dict[str, str] = {
    "redoc_js_url": "https://cdn.jsdelivr.net/npm/redoc@2.1.3/bundles/redoc.standalone.js",
    "redoc_favicon_url": "https://fastapi.tiangolo.com/img/favicon.png",
}
