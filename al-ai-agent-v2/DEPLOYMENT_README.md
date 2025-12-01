# AI Data Agent API v2 - Azure Container Apps Deployment

This guide covers deploying the AI Data Agent API v2 to Azure Container Apps.

## Prerequisites

1. **Azure CLI** - [Install Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
2. **Docker Desktop** - [Install Docker Desktop](https://www.docker.com/products/docker-desktop)
3. **Azure Subscription** - Active subscription with billing enabled
4. **Azure Account Permissions** - Contributor or Owner role
5. **Environment Variables** - `.env` file configured with all required variables

## Required Environment Variables

Before deploying, ensure your `.env` file contains:

- `DATABASE_URL` - PostgreSQL connection string (must be accessible from Azure)
- `OPEN_ROUTER_KEY` - OpenRouter API key
- `DEFAULT_MODEL_VERSION` - Default model ID (e.g., `google/gemini-2.5-flash`)
- `DOMO_CLIENT_ID` and `DOMO_SECRET_KEY` - Domo credentials
- `AZURE_STORAGE_ACCOUNT`, `AZURE_STORAGE_CONTAINER`, `AZURE_API_KEY` - Azure Blob Storage
- `TEST_DATASET_IDS` - Comma-separated dataset IDs
- `DOMO_MASTER_DATASET_ID` - Master dataset ID for indexing

## Important: Database Configuration

**The API requires a PostgreSQL database with pgvector extension.**

The database must be:
- Accessible from Azure Container Apps (not localhost)
- Have pgvector extension enabled
- Contain the necessary tables (created by `scripts/init_db.py`)

Options:
1. **Azure Database for PostgreSQL** - Recommended for production
2. **Azure Container Apps with PostgreSQL** - For development
3. **External PostgreSQL** - If you have an existing database

## Quick Deployment

### 1. Verify Prerequisites

```bash
# Check Azure CLI
az --version

# Check Docker
docker --version

# Login to Azure
az login

# Verify subscription
az account show
```

### 2. Review Configuration

Edit `scripts/deploy-container-app.sh` and verify:
- `RESOURCE_GROUP` - Resource group name
- `CONTAINER_APP_NAME` - Container app name
- `REGISTRY_NAME` - Must be globally unique (lowercase, alphanumeric)
- `LOCATION` - Central US (`centralus`)

### 3. Ensure .env File is Configured

```bash
# Make sure .env file exists and has all required variables
cd /Users/Ariel.Herrera/Code/asset-living-projects/ai-projects/al-ai-agent-v2
# Review your .env file
```

### 4. Run Deployment

```bash
./scripts/deploy-container-app.sh
```

**Estimated time: 15-20 minutes**

The script will:
1. Create resource group in Central US
2. Create Application Insights
3. Create Azure Container Registry
4. Build Docker image (AMD64 platform)
5. Push image to registry
6. Create Container Apps environment
7. Deploy container app with environment variables
8. Configure public HTTPS ingress

## Post-Deployment

### Get Your API URL

```bash
az containerapp show \
  --name app-ai-agent-v2 \
  --resource-group rg-ai-agent-v2 \
  --query properties.configuration.ingress.fqdn -o tsv
```

### Test Your API

```bash
# Health check
curl "https://<your-url>/health"

# Query endpoint
curl -X POST "https://<your-url>/api/v1/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "What are 5 properties that were lost in September 2025?", "user_id": "test_user"}'
```

## Updating Environment Variables

If you need to update environment variables after deployment:

```bash
az containerapp update \
  --name app-ai-agent-v2 \
  --resource-group rg-ai-agent-v2 \
  --set-env-vars NEW_VAR=value
```

Or edit the deployment script and re-run it.

## Troubleshooting

### Database Connection Issues

The database must be accessible from Azure. If using a local database:
- Use Azure Database for PostgreSQL instead
- Or set up a VPN/private endpoint

### Missing Environment Variables

Check logs:
```bash
az containerapp logs show \
  --name app-ai-agent-v2 \
  --resource-group rg-ai-agent-v2 \
  --tail 100
```

### Container App Not Starting

Check the app status:
```bash
az containerapp show \
  --name app-ai-agent-v2 \
  --resource-group rg-ai-agent-v2 \
  --query properties.runningStatus
```

## Cost Considerations

- **Consumption-based pricing**: ~$0.000012/vCPU-second + ~$0.0000015/GB-second
- **Estimated monthly cost**: $15-50/month for moderate usage
- **Scales to zero** when not in use (default configuration)

## Self-Hosted Qdrant Plan (Azure Container Apps)

To support column-level retrieval in production, we will self-host Qdrant as a dedicated Azure Container App that lives alongside the API.

### Target Architecture

| Item | Value |
|------|-------|
| Resource Group | `rg-ai-agent-v2` |
| Container App Environment | `env-ai-agent-v2` |
| Qdrant App Name | `qdrant-ai-agent` |
| Image | `qdrant/qdrant:latest` |
| CPU / Memory | 1 vCPU / 2 GiB (starter) |
| Storage | Azure Files share mounted to `/qdrant/storage` (>=20 GiB) |
| Ports | 6333 HTTP API, 6334 gRPC |
| Auth | Qdrant API key via `QDRANT__AUTH__API_KEY` |

### Provisioning Steps

1. **Persistent storage (Azure Files)**
   ```bash
   STORAGE_ACCOUNT=staiagentqdrant
   FILE_SHARE=qdrantdata

   az storage account create \
     --name $STORAGE_ACCOUNT \
     --resource-group rg-ai-agent-v2 \
     --location centralus \
     --sku Standard_LRS

   STORAGE_KEY=$(az storage account keys list \
     --account-name $STORAGE_ACCOUNT \
     --resource-group rg-ai-agent-v2 \
     --query "[0].value" -o tsv)

   az storage share create \
     --account-name $STORAGE_ACCOUNT \
     --account-key $STORAGE_KEY \
     --name $FILE_SHARE \
     --quota 100
   ```

2. **Deploy the Qdrant container app**
   ```bash
   QDRANT_API_KEY=$(openssl rand -hex 32)

   az containerapp create \
     --name qdrant-ai-agent \
     --resource-group rg-ai-agent-v2 \
     --environment env-ai-agent-v2 \
     --image qdrant/qdrant:latest \
     --target-port 6333 \
     --ingress external \
     --min-replicas 0 \
     --max-replicas 1 \
     --cpu 1 \
     --memory 2Gi \
     --secrets qdrant-api-key=$QDRANT_API_KEY storage-key=$STORAGE_KEY \
     --env-vars \
        QDRANT__SERVICE__GRPC_PORT=6334 \
        QDRANT__STORAGE__STORAGE_PATH=/qdrant/storage \
        QDRANT__AUTH__API_KEY=secretref:qdrant-api-key \
     --volume name=qdrantdata \
        storage-type=AzureFile \
        storage-name=$FILE_SHARE \
        mount-path=/qdrant/storage \
        storage-account-name=$STORAGE_ACCOUNT \
        storage-account-key-secret=storage-key
   ```

3. **Record Qdrant endpoint**
   ```bash
   QDRANT_FQDN=$(az containerapp show \
     --name qdrant-ai-agent \
     --resource-group rg-ai-agent-v2 \
     --query properties.configuration.ingress.fqdn -o tsv)
   echo "Qdrant URL: https://${QDRANT_FQDN}"
   ```

### Wire the API

Add these variables to the production `.env` (or Container App secrets) before redeploying `app-ai-agent-v2`:

```
QDRANT_URL=https://qdrant-ai-agent.<fqdn>
QDRANT_API_KEY=<same key as above>
QDRANT_COLLECTION_NAME=column_embeddings
QDRANT_VECTOR_SIZE=1536
QDRANT_USE_GRPC=false  # set true only if exposing gRPC
```

Then rerun `./scripts/deploy-container-app.sh` (it now passes the Qdrant env vars and creates a unique revision suffix).

### Post-Deployment Checklist

1. Populate Qdrant with column embeddings:
   ```bash
   python scripts/reindex_production.py --yes
   ```
2. Verify Qdrant health: `curl https://qdrant-ai-agent.<fqdn>/healthz`
3. Run prod smoke tests via `python test_query.py --env prod --question "..."`
4. Monitor logs for both apps (`app-ai-agent-v2` and `qdrant-ai-agent`).

### Maintenance Notes

- **Backups:** Take Azure Files snapshots or leverage Qdrant's native snapshot API regularly.
  ```bash
  az storage share snapshot \
    --account-name staiagentqdrant \
    --account-key <storage-key> \
    --name qdrantdata
  ```
- **Monitoring:** Tail logs via `az containerapp logs show --name qdrant-ai-agent --resource-group rg-ai-agent-v2 --follow`.
- **Scaling:** Increase replicas or vCPU/memory with `az containerapp update --name qdrant-ai-agent --cpu 2 --memory 4Gi --max-replicas 2`.
- **Key rotation:** Generate a new `QDRANT_API_KEY`, update the `qdrant-ai-agent` secret, redeploy `app-ai-agent-v2` with the new key, then run `python scripts/reindex_production.py --yes`.
- **Security:** Restrict ingress with IP allow-lists or move both container apps into a shared VNet/private endpoint when possible. Store secrets (API key, storage key) in a managed vault.

## Next Steps

1. Set up Azure Database for PostgreSQL (if not already done)
2. Initialize database tables in production database
3. Index datasets using `scripts/setup_vectors.py` (adapt for production)
4. Configure custom domain (optional)
5. Set up monitoring alerts

