# API Key Authentication

The production API now requires API key authentication for all endpoints except the health check.

## How It Works

- **Production**: API key authentication is **required** when `ENVIRONMENT=production` and `API_KEY` (or `API_SECRET_KEY`) is set
- **Development**: API key authentication is **disabled** (for local testing)
- **Health Check**: The `/health` endpoint remains public (no authentication required)

## Setting Up API Key

### 1. Generate an API Key

Generate a secure API key:

```bash
# Option 1: Using OpenSSL
openssl rand -hex 32

# Option 2: Using Python
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Add to Environment Variables

Add the API key to your `.env` file:

```bash
API_KEY=your-generated-api-key-here
```

Or use `API_SECRET_KEY` (both are supported):

```bash
API_SECRET_KEY=your-generated-api-key-here
```

### 3. Deploy to Azure

The deployment script automatically includes the API key from your `.env` file:

```bash
./scripts/deploy-container-app.sh
```

Or manually set it in Azure:

```bash
az containerapp update \
  --name app-ai-agent-v2 \
  --resource-group rg-ai-agent-v2 \
  --set-env-vars API_KEY=your-generated-api-key-here
```

## Using the API

### With curl

```bash
curl -X POST "https://app-ai-agent-v2.ambitiousdesert-4823611f.centralus.azurecontainerapps.io/api/v1/query" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
    "query": "What are 5 properties that were lost in September 2025?",
    "user_id": "test_user"
  }'
```

### With test_query.py

```bash
# Set API key as environment variable
export API_KEY=your-api-key-here
python3 test_query.py --env prod -q "Your question here"

# Or pass it directly
python3 test_query.py --env prod -q "Your question here" --api-key your-api-key-here
```

### With Python requests

```python
import requests

url = "https://app-ai-agent-v2.ambitiousdesert-4823611f.centralus.azurecontainerapps.io/api/v1/query"
headers = {
    "Content-Type": "application/json",
    "X-API-Key": "your-api-key-here"
}
payload = {
    "query": "Your question here",
    "user_id": "test_user"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

## Error Responses

### Missing API Key (401)

```json
{
  "detail": "API key is required. Please provide X-API-Key header."
}
```

### Invalid API Key (403)

```json
{
  "detail": "Invalid API key."
}
```

## Security Best Practices

1. **Use Strong Keys**: Generate keys with at least 32 characters
2. **Rotate Regularly**: Change API keys periodically
3. **Store Securely**: Never commit API keys to version control
4. **Use Environment Variables**: Store keys in `.env` files (not in code)
5. **Limit Access**: Only share API keys with authorized users
6. **Monitor Usage**: Check Azure Container Apps logs for suspicious activity

## Protected Endpoints

All API endpoints require authentication in production:
- `POST /api/v1/query` - Query endpoint
- `POST /api/v1/query/stream` - Streaming query endpoint
- `GET /api/v1/conversations/{user_id}` - Get user conversations
- `GET /api/v1/conversations/{conversation_id}/messages` - Get conversation messages
- `POST /api/v1/conversations` - Create conversation
- `DELETE /api/v1/conversations/{conversation_id}` - Delete conversation

## Public Endpoints

These endpoints do NOT require authentication:
- `GET /health` - Health check
- `GET /` - Root endpoint
- `GET /docs` - API documentation (Swagger UI)





