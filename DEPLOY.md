# Pickwatch Dashboard — Coolify Deployment Guide

## Prerequisites
- Coolify access on `178.156.241.169`
- GitHub repo: `github.com/rmarji/pickwatch-dashboard` (main branch)

## Quick Deploy Steps

### 1. Create New Service in Coolify
- Type: **Docker Compose** (or Dockerfile)
- Source: **GitHub** → `rmarji/pickwatch-dashboard`
- Branch: `main`

### 2. Set Environment Variables
```
PICKWATCH_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTM4NDAyLCJjbGFpbXMiOltdLCJpYXQiOjE3NzIxNDYyMjUsImV4cCI6MTc4Nzk1NzQyNX0.DP4m3STL2Lr4kw48ymIUM4QD4zJqIKBmwdvQk-40wT4
PICKWATCH_ORIGIN=https://nflpickwatch.com
PICKWATCH_API_URL=https://api.pickwatch.com/v1
PORT=8080
```

### 3. Configure Domain
Suggested: `pickwatch.claw.jogeeks.com` or sslip.io subdomain

### 4. Deploy & Verify
```bash
curl https://<domain>/api/health
# Should return: {"status": "ok", ...}
```

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `/` | Web dashboard |
| `/api/health` | Health check |
| `/api/picks` | Today's picks |
| `/api/picks?date=YYYY-MM-DD` | Historical picks |

## Health Check
Built into Dockerfile:
- Interval: 30s
- Timeout: 10s
- Endpoint: `http://localhost:8080/api/health`

## Notes
- No database needed (uses SQLite in container, ephemeral)
- Token expires: Feb 2027
- All dependencies stdlib (no pip install needed)
