# Security Hardening Guide

**Document:** Security Hardening Requirements  
**Epic:** 5 - Audit & Compliance (Foundation)  
**Status:** Backlog - Deferred from Story 1.7  
**Created:** 2026-03-24  

---

## Overview

This document tracks security hardening items identified during implementation that require infrastructure-level decisions or broader architectural changes. These items were discovered during Story 1.7 (Admin Modify User Roles) code review but deferred as they require cross-cutting changes.

---

## Deferred Items from Story 1.7

### D1: IP Address Spoofing via X-Forwarded-For

**Severity:** Medium  
**Location:** `app/routers/admin.py:181-188`  
**Discovered:** Code Review 2026-03-24  

#### Issue
The current IP extraction blindly trusts the `X-Forwarded-For` header:

```python
x_forwarded_for = request.headers.get("X-Forwarded-For")
if x_forwarded_for:
    ip_address = x_forwarded_for.split(",")[0].strip()
```

A malicious client can spoof any IP address by sending this header directly to the server.

#### Impact
- Audit logs may contain falsified IP addresses
- Compliance requirements (FR55-FR59) may be compromised
- Security investigations based on audit logs could be misled

#### Proposed Solutions

1. **Trusted Proxy List** (Recommended)
   ```python
   TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", "").split(",")
   # Only trust X-Forwarded-For from known proxies
   ```

2. **Secure Header Alternative**
   ```python
   # Use X-Real-IP or custom header set by trusted reverse proxy
   ip_address = request.headers.get("X-Real-IP") or request.client.host
   ```

3. **Chain Validation**
   ```python
   # Parse the full proxy chain and validate against known hops
   ips = [ip.strip() for ip in x_forwarded_for.split(",")]
   # Find the rightmost IP from a trusted proxy
   ```

#### Implementation Notes
- Requires environment configuration for trusted proxies
- Should be implemented as middleware for all audit-logged endpoints
- Consider using FastAPI's `Forwarded` middleware or similar

---

### D2: Race Condition on Concurrent Role Changes

**Severity:** Medium  
**Location:** `app/services/user_service.py:752-780`  
**Discovered:** Code Review 2026-03-24  

#### Issue
Two administrators updating the same user simultaneously:
1. Admin A reads user (role = annotator)
2. Admin B reads user (role = annotator)
3. Admin A updates to curator
4. Admin B updates to admin
5. Final state: admin (Admin B's change wins)
6. Audit logs show both changes, but intermediate state (curator) was never active

#### Impact
- Lost updates - intermediate changes may be silently overwritten
- Audit log shows changes that were immediately overwritten
- Inconsistent state between what was audited and final state

#### Proposed Solutions

1. **Optimistic Locking** (Recommended)
   ```python
   # Add version/timestamp column to users table
   async def update_role(self, user_id, new_role, expected_version):
       result = await self.session.execute(
           update(User)
           .where(User.id == user_id, User.version == expected_version)
           .values(role=new_role, version=expected_version + 1)
       )
       if result.rowcount == 0:
           raise ConcurrentModificationError()
   ```

2. **Serializable Transactions**
   ```python
   # Use database-level serialization
   async with self.session.begin(isolation_level="SERIALIZABLE"):
       # Read and update in same transaction
   ```

3. **Row-Level Locking**
   ```python
   # SELECT FOR UPDATE
   user = await self.session.execute(
       select(User).where(User.id == user_id).with_for_update()
   )
   ```

#### Implementation Notes
- Affects all user modification endpoints (role, deactivate, update)
- Should be part of repository layer pattern
- Consider optimistic locking for all entities with concurrent modification risk

---

### D3: X-Forwarded-For IP Selection (Wrong IP)

**Severity:** Low  
**Location:** `app/routers/admin.py:184`  
**Discovered:** Code Review 2026-03-24  

#### Issue
The current implementation takes the first IP from the `X-Forwarded-For` chain:

```python
ip_address = x_forwarded_for.split(",")[0].strip()
```

In some proxy chain configurations, the first IP is an internal proxy, not the actual client IP. The chain format is:
```
X-Forwarded-For: client, proxy1, proxy2, ..., proxyN
```

But in certain configurations (e.g., AWS ALB, CloudFlare), the first IP might be added by the closest proxy.

#### Impact
- Audit logs may contain internal proxy IPs instead of actual client IPs
- Geographic/user analysis based on audit logs may be inaccurate

#### Proposed Solutions

1. **Rightmost Trusted IP** (Recommended)
   ```python
   # Find the rightmost IP from a trusted proxy
   ips = [ip.strip() for ip in x_forwarded_for.split(",")]
   for ip in reversed(ips):
       if ip not in TRUSTED_PROXIES:
           return ip  # First non-proxy IP from the right
   ```

2. **Configuration-Based Selection**
   ```python
   # Configure which position to take based on infrastructure
   XFF_IP_POSITION = os.getenv("XFF_IP_POSITION", "first")  # or "last"
   ```

3. **Use Standard Middleware**
   ```python
   # Use Uvicorn/FastAPI's built-in proxy handling
   from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
   ```

#### Implementation Notes
- Depends on specific network topology
- Should be configurable per environment
- Test with actual production proxy chain

---

## Cross-Cutting Concerns

### Audit Logging Reliability

Items D1, D2, D3 all affect audit log accuracy. For Epic 5 (Audit & Compliance), consider:

1. **Audit Log Integrity Verification**
   - Periodic checks that audit entries match actual state
   - Alerting on audit log gaps or anomalies

2. **Client Identity Verification**
   - Beyond IP, consider logging device fingerprints
   - Session/token correlation for non-repudiation

3. **Tamper Detection**
   - Immutable audit log storage
   - Cryptographic signing of audit entries

---

## Recommended Epic 5 Stories

Based on these deferred items, consider adding the following stories to Epic 5:

### Story 5.X: Trusted Proxy Configuration
- Implement trusted proxy list configuration
- Update IP extraction middleware
- Add tests for various proxy chain scenarios

### Story 5.Y: Optimistic Locking Framework
- Add version columns to audit-relevant entities
- Implement optimistic locking in repository layer
- Add conflict detection and retry logic

### Story 5.Z: Audit Log Integrity Verification
- Background job to verify audit log completeness
- Alerting for audit log anomalies
- Dashboard for audit log health

---

## Related Documentation

- `docs/stories/story-1.7-admin-modify-user-roles.md` - Original review context
- `docs/rbac-guide.md` - RBAC implementation
- Architecture Decision Record: "Audit Trail" (in planning artifacts)

---

## Change Log

| Date | Change |
|------|--------|
| 2026-03-24 | Document created with D1-D3 from Story 1.7 code review |

---

## References

- [MDN: X-Forwarded-For](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Forwarded-For)
- [OWASP: Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- SQLAlchemy: [Optimistic Concurrency Control](https://docs.sqlalchemy.org/en/20/orm/versioning.html)
