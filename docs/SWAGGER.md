# Swagger/OpenAPI Documentation Guide

This guide explains how to use and customize the Swagger/OpenAPI documentation in the JBI API.

## Overview

The JBI API provides comprehensive API documentation using:

- **Swagger UI**: Interactive API documentation at `/docs`
- **ReDoc**: Alternative documentation at `/redoc`
- **OpenAPI JSON**: Raw schema at `/openapi.json`

## Accessing the Documentation

Once the server is running:

```bash
# Start the server
uvicorn app.main:app --reload

# Access documentation
open http://localhost:8000/docs    # Swagger UI
open http://localhost:8000/redoc   # ReDoc
```

## Features

### Authentication in Swagger UI

1. Click the **Authorize** button (top-right)
2. Enter your JWT token in format: `Bearer <token>`
3. Click **Authorize** and close the dialog
4. All protected endpoints will now include the Authorization header

### Token Format

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## Configuration Files

### `app/core/swagger_config.py`

Central configuration for Swagger/OpenAPI:

- `TAGS_METADATA`: API tag descriptions
- `SECURITY_SCHEMES`: Authentication schemes
- `SWAGGER_UI_CONFIG`: UI customization
- `RESPONSE_EXAMPLES`: Common response examples

### `app/core/swagger_docs.py`

Helper utilities for endpoint documentation:

- `ApiResponses`: Standard HTTP response definitions
- `EndpointExamples`: Request/response examples
- `DescriptionTemplates`: Reusable documentation templates

## Documenting Endpoints

### Basic Documentation

```python
from fastapi import APIRouter, status
from app.core.swagger_docs import ApiResponses, DescriptionTemplates

router = APIRouter()

@router.get(
    "/items",
    response_model=ItemListResponse,
    summary="List all items",
    description=f"""
    Retrieve a paginated list of items.
    
    {DescriptionTemplates.PAGINATION}
    {DescriptionTemplates.AUTH_REQUIRED}
    """,
    responses={
        **ApiResponses.protected(),
        status.HTTP_200_OK: {
            "description": "List of items",
            "content": {
                "application/json": {
                    "example": {
                        "items": [],
                        "total": 0,
                        "page": 1
                    }
                }
            }
        }
    }
)
async def list_items():
    pass
```

### Protected Endpoint with Role Requirements

```python
from fastapi import APIRouter, Depends
from app.api.deps import require_admin
from app.core.swagger_docs import ApiResponses, DescriptionTemplates

@router.post(
    "/admin/users",
    summary="Create user (admin only)",
    description=f"""
    Create a new user account.
    
    {DescriptionTemplates.ADMIN_REQUIRED}
    """,
    responses=ApiResponses.crud(),
)
async def create_user(
    current_user: CurrentUser = Depends(require_admin)
):
    pass
```

### Common Response Patterns

```python
from app.core.swagger_docs import ApiResponses

# Basic protected endpoint
responses = ApiResponses.protected()
# Returns: {401: {...}, 403: {...}}

# With validation
responses = ApiResponses.with_validation()
# Returns: {401: {...}, 403: {...}, 422: {...}}

# Full CRUD
responses = ApiResponses.crud()
# Returns: {401, 403, 404, 409, 422}

# Custom combination
responses = {
    **ApiResponses.AUTH_REQUIRED,
    **ApiResponses.NOT_FOUND,
    status.HTTP_200_OK: {"description": "Success"},
}
```

## Tag Organization

Tags group related endpoints in the Swagger UI:

| Tag | Description | Roles |
|-----|-------------|-------|
| `health` | System health checks | Any |
| `authentication` | Login, register, password reset | Any |
| `users` | User profile management | Authenticated |
| `jobs` | Video processing jobs | Authenticated |
| `annotations` | Annotation workflow | Annotator, Curator |
| `asr-review` | ASR transcript review | Annotator, Curator |
| `admin` | System administration | Admin only |

## Customizing the OpenAPI Schema

To modify the global OpenAPI schema, edit `app/main.py`:

```python
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Custom Title",
        version="2.0.0",
        description="Custom description",
        routes=app.routes,
    )
    
    # Add custom security schemes
    openapi_schema["components"]["securitySchemes"]["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key"
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema
```

## Best Practices

1. **Always document responses**: Include error responses using `ApiResponses`
2. **Use descriptive summaries**: Keep endpoint summaries concise
3. **Add detailed descriptions**: Explain business logic and requirements
4. **Include examples**: Show realistic request/response payloads
5. **Document security**: Clearly state which endpoints require authentication
6. **Use templates**: Leverage `DescriptionTemplates` for consistency

## Testing with Swagger UI

1. **Authenticate**: Use the Authorize button to set your JWT token
2. **Try endpoints**: Click "Try it out" and fill in parameters
3. **View responses**: See actual server responses with status codes
4. **Copy curl**: Use the curl command for testing outside the UI

## Troubleshooting

### Endpoints Not Appearing

- Ensure router is included in `app/main.py`
- Check that tags match defined tags in `TAGS_METADATA`

### Authentication Not Working

- Verify token format: `Bearer <token>` (with space)
- Check token hasn't expired
- Ensure endpoint has proper dependency: `Depends(get_current_user)`

### Schema Not Updating

- Restart the server
- Clear browser cache for `/openapi.json`
- Check for syntax errors in schema definitions
