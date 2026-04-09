# Database Loss Analysis Report

## ⚠️ CRITICAL SECURITY ALERT: RANSOMWARE ATTACK DETECTED

**Status**: Database compromised by ransomware  
**Impact**: Complete data loss - all tables, user accounts, job data, annotations are encrypted/deleted  
**Service Status**: API running but returning 503/500 errors due to database unavailability  
**Ransom Demand**: 0.0073 BTC (~$500-700 USD)  
**Deadline**: 48 hours from attack time  
**Threat**: Data will be publicly disclosed and permanently deleted after deadline

---

## Current System State

### Docker Container Status
```
Container                    Status                    Health
─────────────────────────────────────────────────────────────
jbi-service-api-gpu-1        Up 14 hours (unhealthy)   ❌
jbi-service-db-1             Up 7 days (healthy)       ✅
jbi-service-minio-1          Up 7 days (healthy)       ✅
jbi-service-asr-worker-1     Up 6 days (unhealthy)     ❌
jbi-service-cropping-worker-1 Up 6 days (unhealthy)    ❌
jbi-service-detection-worker-1 Up 6 days (unhealthy)   ❌
```

### Database Error Logs
```
FATAL:  database "anotasi_db" does not exist
```

### Health Check Response
```json
{
  "status": "degraded",
  "database": "disconnected",
  "minio": "connected",
  "yolo_model": "loaded",
  "gpu_available": true,
  "disk_space": "OK"
}
```

---

## 🔴 RANSOMWARE EVIDENCE

### Ransom Note Found in Database

During investigation, a database named `readme_to_recover` was discovered with the following ransom message:

```
All your data is backed up. You must pay 0.0073 BTC to 
bc1qh8jhaft6rn6wf0s9efwn4mwv22m6pnr7yjwfeq 

In 48 hours, your data will be publicly disclosed and deleted.

After payment send mail to us: dzen+36nf3@onionmail.org 
and we will provide a link for you to download your data. 
Your DATAID is: 36NF3
```

**Ransomware Details**:
- **Bitcoin Address**: `bc1qh8jhaft6rn6wf0s9efwn4mwv22m6pnr7yjwfeq`
- **Email Contact**: `dzen+36nf3@onionmail.org`
- **DATAID**: `36NF3`
- **Ransom Amount**: 0.0073 BTC
- **Additional Info URL**: `https://is.gd/dzenpsg`
- **Countdown**: 48 hours from attack

### Attack Timeline (Estimated)
- **Volume Created**: March 25, 2026 (21:27:28 UTC)
- **Attack Detected**: April 2, 2026
- **Time Since Attack**: ~7-8 days

---

## Root Cause Analysis: How the Attack Happened

### Attack Vector Analysis

#### 1. Exposed PostgreSQL Port (CRITICAL)

**Configuration in docker-compose.yml**:
```yaml
db:
  ports:
    - "5432:5432"  # ⚠️ EXPOSED TO INTERNET
```

**Security Issue**:
- PostgreSQL port 5432 is mapped to host's public IP
- No firewall rules restricting access
- Default/weak credentials likely used

#### 2. Weak/Default Credentials

**docker-compose.yml**:
```yaml
db:
  environment:
    POSTGRES_DB: anotasi_db
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres  # ⚠️ DEFAULT/WEAK PASSWORD
```

**Attack Method**:
- Automated scanners detected exposed PostgreSQL
- Brute force or default credential attack
- Successful login with `postgres/postgres`
- Malicious actor deleted/dropped all databases
- Created `readme_to_recover` database with ransom note

#### 3. No Network Segmentation

**Missing Security Measures**:
- No Docker network isolation
- No firewall rules (iptables/ufw)
- Database accessible from any IP

---

## Additional Technical Issues Found

### 1. Missing `001_initial_schema` Migration

**File**: `alembic/versions/002_add_auth_tables.py:16`

```python
down_revision: Union[str, None] = '001_initial_schema'
```

**Problem**: Migration `002_add_auth_tables` references `001_initial_schema` as its parent, but **the file `001_initial_schema.py` does not exist**.

### 2. Branched Migration Tree

The migration history has **multiple branches**:

```
008_add_pipeline_tables
    ├── 009_add_asr_review_flag ───────┐
    │                                   ├──> [BRANCH]
    └── 009_add_pipeline_transcripts ──┘
              └── 010_add_video_path_to_transcripts
    └── 010_add_stage2_video_path
```

**Conflicting Migrations**:
- `009_add_asr_review_flag.py` vs `009_add_pipeline_transcripts.py`
- `010_add_stage2_video_path.py` vs `010_add_video_path_to_transcripts.py`
- `011_add_job_cancellation_fields.py` vs `011_remove_unused_segment_fields.py`

### 3. `Base.metadata.create_all()` in Application Startup

**File**: `app/main.py:47-49`
```python
# Create DB tables (safety net — Alembic is the primary migration tool)
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
```

Creates tables without migrations - can cause schema inconsistencies.

### 4. Missing DATABASE_URL in .env

**Server .env File**:
```bash
# Missing: DATABASE_URL
```

**Default in app/core/config.py**:
```python
database_url: str = "postgresql+asyncpg://postgres:123456@localhost:5432/anotasi_db"
```

Password mismatch with Docker Compose configuration.

---

## Immediate Actions Required

### 🚨 DO NOT PAY THE RANSOM

**Important**: Paying the ransom does NOT guarantee data recovery. Many ransomware groups:
- Take the money and don't provide decryption keys
- Leave backdoors for future attacks
- Sell stolen data even after payment

### Step 1: Isolate the System

```bash
# Stop all services immediately
cd jbi-service
docker compose down

# Check for any suspicious containers
docker ps -a
docker images

# Check running processes
ps aux | grep -E "postgres|docker"
```

### Step 2: Preserve Evidence

```bash
# Save container logs
docker logs jbi-service-db-1 > /tmp/db_logs.txt 2>&1
docker logs jbi-service-api-gpu-1 > /tmp/api_logs.txt 2>&1

# Check for unauthorized access
docker exec jbi-service-db-1 cat /var/log/postgresql/postgresql-*.log | tail -1000
```

### Step 3: Check for Backups

```bash
# Check all possible backup locations
find / -name "*.sql" -o -name "*.dump" 2>/dev/null
find /home/erdefi -name "*backup*" 2>/dev/null
ls -la /var/backups/
ls -la ~/backups/

# Check if MinIO has any backups
docker compose exec minio mc ls local/
```

### Step 4: Secure the Infrastructure

1. **Close PostgreSQL Port**:
```yaml
# docker-compose.yml - REMOVE or MODIFY
db:
  # REMOVE: ports:
  #   - "5432:5432"
  # Only internal services should access DB
```

2. **Change All Passwords**:
```yaml
db:
  environment:
    POSTGRES_PASSWORD: <STRONG_RANDOM_PASSWORD>
```

3. **Enable Firewall**:
```bash
sudo ufw enable
sudo ufw deny 5432/tcp
sudo ufw allow from 127.0.0.1 to any port 5432
```

### Step 5: Rebuild from Scratch (If No Backups)

```bash
# Remove compromised volume
docker volume rm jbi-service_pgdata

# Recreate everything
docker compose up -d db

# Wait for DB to be ready
sleep 10

# Create database
docker compose exec db psql -U postgres -c "CREATE DATABASE anotasi_db;"

# Run migrations
docker compose run --rm api-gpu alembic upgrade head

# Seed data
docker compose run --rm api-gpu python scripts/seed_users.py
```

---

## Recovery Options

### Option 1: Restore from Backup (BEST)

If you have backups from before March 25, 2026:
```bash
# Restore from backup
docker exec -i jbi-service-db-1 psql -U postgres < backup_file.sql
```

### Option 2: Rebuild from Scratch

If no backups exist:
1. Recreate database schema
2. Run migrations
3. Re-seed user accounts
4. Re-upload all videos
5. Re-process all jobs

### Option 3: Check Other Volumes

```bash
# Check the other PostgreSQL volume
docker run --rm -v postgres_pgdata:/data postgres:16-alpine ls -laR /data/
```

**Note**: The `postgres_pgdata` volume is from a different Docker project and may have different data.

---

## Security Hardening Recommendations

### 1. Network Security (CRITICAL)

**Never expose database ports publicly**:
```yaml
# docker-compose.yml
db:
  # NO ports section, or only:
  ports:
    - "127.0.0.1:5432:5432"  # Localhost only
```

### 2. Strong Passwords (CRITICAL)

Generate strong passwords:
```bash
openssl rand -base64 32
```

### 3. Firewall Configuration

```bash
# UFW Rules
sudo ufw default deny incoming
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 8000/tcp  # API (if needed)
sudo ufw enable
```

### 4. Docker Network Isolation

```yaml
# docker-compose.yml
networks:
  backend:
    internal: true  # No external access
  frontend:
    driver: bridge

services:
  db:
    networks:
      - backend
  api-gpu:
    networks:
      - backend
      - frontend
    ports:
      - "8000:8000"
```

### 5. Automated Backups (CRITICAL)

```yaml
# docker-compose.yml
  pgbackup:
    image: postgres:16-alpine
    volumes:
      - jbi-service_pgdata:/data:ro
      - ./backups:/backups
    command: >
      sh -c '
        while true; do
          pg_dump -h db -U postgres anotasi_db > /backups/backup_$$(date +%Y%m%d_%H%M%S).sql
          find /backups -name "backup_*.sql" -mtime +7 -delete
          sleep 3600
        done
      '
```

### 6. Fail2Ban for Intrusion Prevention

```bash
sudo apt install fail2ban
sudo systemctl enable fail2ban
```

Configure for PostgreSQL:
```ini
# /etc/fail2ban/jail.local
[postgres]
enabled = true
port = 5432
filter = postgres
logpath = /var/log/postgresql/postgresql-*.log
maxretry = 3
bantime = 3600
```

### 7. PostgreSQL Hardening

**pg_hba.conf**:
```
# Reject all connections except from internal Docker network
host all all 0.0.0.0/0 reject
host all all 172.0.0.0/8 md5  # Docker networks
host all all 127.0.0.1/32 md5
```

### 8. Disable Root Login & Use SSH Keys

```bash
# On host server
sudo passwd -l root
sudo nano /etc/ssh/sshd_config
# Set: PermitRootLogin no
# Set: PasswordAuthentication no
sudo systemctl restart sshd
```

---

## Monitoring & Alerting

### 1. Database Connection Monitoring

```bash
# Add to cron (crontab -e)
*/5 * * * * docker exec jbi-service-db-1 psql -U postgres -c "SELECT 1;" || echo "DB DOWN" | mail -s "Database Alert" admin@example.com
```

### 2. Log Aggregation

```yaml
# Add to docker-compose.yml
  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"
    volumes:
      - ./loki-config.yml:/etc/loki/local-config.yaml
```

### 3. Health Check Improvements

Add more comprehensive health checks to catch attacks early.

---

## Incident Response Checklist

- [x] Ransomware identified
- [ ] Isolate affected systems
- [ ] Preserve logs and evidence
- [ ] Check for backups
- [ ] Assess data loss scope
- [ ] Report incident to relevant authorities (if required)
- [ ] Secure infrastructure
- [ ] Rebuild/restore services
- [ ] Implement monitoring
- [ ] Security audit
- [ ] Document lessons learned

---

## Files Requiring Changes

| File | Issue | Priority |
|------|-------|----------|
| `docker-compose.yml` | PostgreSQL port exposed to internet | 🔴 CRITICAL |
| `docker-compose.yml` | Weak default password | 🔴 CRITICAL |
| `.env` | Missing DATABASE_URL | 🟡 HIGH |
| `alembic/versions/002_add_auth_tables.py` | Missing parent migration | 🟡 HIGH |
| `app/main.py` | Uses `create_all()` instead of migrations | 🟡 MEDIUM |
| `alembic/versions/` | Multiple branched migrations | 🟡 MEDIUM |

---

## Conclusion

The database loss was caused by a **ransomware attack**, not a technical error. The attack was possible due to:

1. **Exposed PostgreSQL port** (5432) on the public internet
2. **Weak/default credentials** (`postgres/postgres`)
3. **No firewall protection**
4. **No backup strategy**

### Immediate Priority:

1. **DO NOT PAY RANSOM** - No guarantee of recovery
2. **Secure the infrastructure** - Close ports, change passwords, enable firewall
3. **Check for backups** - Look everywhere for any `.sql` files
4. **Rebuild the system** - From backup or from scratch
5. **Implement security measures** - Prevent future attacks

### Prevention:

1. Never expose database ports publicly
2. Use strong, unique passwords
3. Enable firewall (UFW)
4. Set up automated backups (off-site)
5. Regular security audits
6. Intrusion detection (Fail2Ban)
7. Network segmentation
8. Regular security updates

---

*Report generated: 2026-04-02*  
*Classification: CONFIDENTIAL - SECURITY INCIDENT*  
*Analyst: AI Troubleshooting System*
