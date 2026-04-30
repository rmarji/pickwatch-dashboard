# Deploy Pickwatch Dashboard to Coolify

## Prerequisites

1. GitHub repo cloned to Coolify (or use GitHub App)
2. `PICKWATCH_TOKEN` environment variable set

## Deployment Steps

1. **Create Resource** in Coolify
   - Choose "Docker Compose"
   - Select this repository
   - Select `docker-compose.yml`

2. **Environment Variables**
   - Add: `PICKWATCH_TOKEN=<token>`

3. **Domain**
   - Assign domain: `pickwatch.claw.jogeeks.com`
   - Enable HTTPS

4. **Deploy**
   - Healthcheck: `/health` on port 8080
   - Expected: HTTP 200 with `{"status": "healthy"}`

## API Endpoints

- `GET /health` - Health check
- `GET /api/picks` - Get today's scored picks
- `GET /api/history` - Historical performance
- `GET /api/edge` - Edge analysis

## Verification

```bash
curl https://pickwatch.claw.jogeeks.com/health
curl https://pickwatch.claw.jogeeks.com/api/picks
```
