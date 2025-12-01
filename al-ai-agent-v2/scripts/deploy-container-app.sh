#!/bin/bash

# Azure Container Apps Deployment Script for AI Data Agent API v2
# This script deploys the AI Data Agent API to Azure Container Apps in Central US region
# Optional flag: --with-reindex will reindex the production Qdrant cluster and clear caches post-deploy.

set -e  # Exit on error

WITH_REINDEX=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-reindex)
            WITH_REINDEX=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--with-reindex]"
            exit 1
            ;;
    esac
done

# Configuration variables
RESOURCE_GROUP="rg-ai-agent-v2"
CONTAINER_APP_ENV="env-ai-agent-v2"
CONTAINER_APP_NAME="app-ai-agent-v2"
LOCATION="centralus"  # Central US region
REGISTRY_NAME="acraiaagentv2"  # Azure Container Registry name (must be globally unique, lowercase, alphanumeric)
IMAGE_NAME="ai-agent-v2"
IMAGE_TAG="latest"
APP_INSIGHTS_NAME="insights-ai-agent-v2"
REVISION_SUFFIX="rev-$(date +%Y%m%d%H%M%S)"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Azure Container Apps Deployment for AI Data Agent API v2 ===${NC}"
echo ""

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo -e "${RED}Error: Azure CLI is not installed.${NC}"
    echo "Please install it from: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed.${NC}"
    echo "Please install Docker Desktop from: https://www.docker.com/products/docker-desktop"
    exit 1
fi

# Check if logged in to Azure
echo -e "${YELLOW}Checking Azure login status...${NC}"
if ! az account show &> /dev/null; then
    echo -e "${YELLOW}Not logged in to Azure. Please log in...${NC}"
    az login
fi

# Get current subscription
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo -e "${GREEN}Using subscription: ${SUBSCRIPTION_ID}${NC}"
echo ""

# Check if Container Apps extension is installed
echo -e "${YELLOW}Checking for Container Apps extension...${NC}"
if ! az extension show --name containerapp &> /dev/null; then
    echo -e "${YELLOW}Installing Container Apps extension...${NC}"
    az extension add --name containerapp
else
    echo -e "${GREEN}Container Apps extension already installed.${NC}"
fi
echo ""

# Create resource group
echo -e "${YELLOW}Creating resource group: ${RESOURCE_GROUP}...${NC}"
az group create \
    --name "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --output none 2>/dev/null || echo -e "${BLUE}Resource group already exists.${NC}"

echo -e "${GREEN}Resource group ready.${NC}"
echo ""

# Create Application Insights
echo -e "${YELLOW}Creating Application Insights: ${APP_INSIGHTS_NAME}...${NC}"
APP_INSIGHTS_ID=$(az monitor app-insights component create \
    --app "${APP_INSIGHTS_NAME}" \
    --location "${LOCATION}" \
    --resource-group "${RESOURCE_GROUP}" \
    --application-type web \
    --query id -o tsv 2>/dev/null || \
    az monitor app-insights component show \
        --app "${APP_INSIGHTS_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --query id -o tsv)

APP_INSIGHTS_CONNECTION_STRING=$(az monitor app-insights component show \
    --app "${APP_INSIGHTS_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --query connectionString -o tsv)

echo -e "${GREEN}Application Insights ready.${NC}"
echo ""

# Create Azure Container Registry (if it doesn't exist)
echo -e "${YELLOW}Creating Azure Container Registry: ${REGISTRY_NAME}...${NC}"
REGISTRY_EXISTS=$(az acr show --name "${REGISTRY_NAME}" --resource-group "${RESOURCE_GROUP}" --query name -o tsv 2>/dev/null || echo "")

if [ -z "$REGISTRY_EXISTS" ]; then
    echo -e "${YELLOW}Registry doesn't exist. Creating new registry (this may take a few minutes)...${NC}"
    az acr create \
        --name "${REGISTRY_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --sku Basic \
        --admin-enabled true \
        --output none
    
    echo -e "${GREEN}Container Registry created.${NC}"
else
    echo -e "${BLUE}Container Registry already exists.${NC}"
fi

# Get registry login server and credentials
REGISTRY_LOGIN_SERVER=$(az acr show --name "${REGISTRY_NAME}" --resource-group "${RESOURCE_GROUP}" --query loginServer -o tsv)
REGISTRY_USERNAME=$(az acr credential show --name "${REGISTRY_NAME}" --resource-group "${RESOURCE_GROUP}" --query username -o tsv)
REGISTRY_PASSWORD=$(az acr credential show --name "${REGISTRY_NAME}" --resource-group "${RESOURCE_GROUP}" --query 'passwords[0].value' -o tsv)

echo -e "${GREEN}Registry login server: ${REGISTRY_LOGIN_SERVER}${NC}"
echo ""

# Build and push Docker image
echo -e "${YELLOW}Building Docker image...${NC}"
cd "$(dirname "$0")/.."  # Go to project root

# Login to ACR
echo -e "${YELLOW}Logging into Azure Container Registry...${NC}"
echo "${REGISTRY_PASSWORD}" | docker login "${REGISTRY_LOGIN_SERVER}" --username "${REGISTRY_USERNAME}" --password-stdin

# Build the image for AMD64 platform (required for Azure)
echo -e "${YELLOW}Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG} (AMD64 platform)...${NC}"
docker build --platform linux/amd64 -t "${REGISTRY_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}" .

echo -e "${GREEN}Docker image built successfully.${NC}"
echo ""

# Push the image
echo -e "${YELLOW}Pushing Docker image to registry (this may take a few minutes)...${NC}"
docker push "${REGISTRY_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"

echo -e "${GREEN}Docker image pushed successfully.${NC}"
echo ""

# Create Container Apps environment
echo -e "${YELLOW}Creating Container Apps environment: ${CONTAINER_APP_ENV}...${NC}"
az containerapp env create \
    --name "${CONTAINER_APP_ENV}" \
    --resource-group "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --logs-workspace-id "${APP_INSIGHTS_ID}" \
    --output none 2>/dev/null || echo -e "${BLUE}Container Apps environment already exists.${NC}"

echo -e "${GREEN}Container Apps environment ready.${NC}"
echo ""

# Check for .env file to get environment variables
ENV_FILE="$(dirname "$0")/../.env"
if [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}Found .env file. Environment variables will be loaded.${NC}"
    echo -e "${YELLOW}Note: Make sure your .env file contains all required variables.${NC}"
    # Read .env file and export variables (safer than sourcing)
    export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | xargs) 2>/dev/null || true
else
    echo -e "${YELLOW}Warning: .env file not found.${NC}"
    echo -e "${YELLOW}You'll need to set environment variables manually or ensure they're in your .env file.${NC}"
fi
echo ""

# Create Container App
echo -e "${YELLOW}Creating Container App: ${CONTAINER_APP_NAME}...${NC}"

# Check if container app already exists
APP_EXISTS=$(az containerapp show --name "${CONTAINER_APP_NAME}" --resource-group "${RESOURCE_GROUP}" --query name -o tsv 2>/dev/null || echo "")

# Build environment variables for Azure CLI
# Azure CLI requires env-vars in format: KEY1=value1 KEY2=value2
ENV_VARS_ARGS=(
    "ENVIRONMENT=production"
    "LOG_LEVEL=INFO"
    "APPLICATIONINSIGHTS_CONNECTION_STRING=${APP_INSIGHTS_CONNECTION_STRING}"
)

# Add API key if it exists (check multiple possible names)
if [ ! -z "${AZURE_AGENT_API_KEY:-}" ]; then
    ENV_VARS_ARGS+=("AZURE_AGENT_API_KEY=${AZURE_AGENT_API_KEY}")
elif [ ! -z "${API_KEY:-}" ]; then
    ENV_VARS_ARGS+=("API_KEY=${API_KEY}")
elif [ ! -z "${API_SECRET_KEY:-}" ]; then
    ENV_VARS_ARGS+=("API_SECRET_KEY=${API_SECRET_KEY}")
fi

# Add optional environment variables if they exist
if [ ! -z "${DATABASE_URL:-}" ]; then
    ENV_VARS_ARGS+=("DATABASE_URL=${DATABASE_URL}")
fi
if [ ! -z "${OPEN_ROUTER_KEY:-}" ]; then
    ENV_VARS_ARGS+=("OPEN_ROUTER_KEY=${OPEN_ROUTER_KEY}")
fi
if [ ! -z "${DEFAULT_MODEL_VERSION:-}" ]; then
    ENV_VARS_ARGS+=("DEFAULT_MODEL_VERSION=${DEFAULT_MODEL_VERSION}")
fi
if [ ! -z "${OPEN_ROUTER_BASE_URL:-}" ]; then
    ENV_VARS_ARGS+=("OPEN_ROUTER_BASE_URL=${OPEN_ROUTER_BASE_URL}")
fi
if [ ! -z "${DOMO_CLIENT_ID:-}" ]; then
    ENV_VARS_ARGS+=("DOMO_CLIENT_ID=${DOMO_CLIENT_ID}")
fi
if [ ! -z "${DOMO_SECRET_KEY:-}" ]; then
    ENV_VARS_ARGS+=("DOMO_SECRET_KEY=${DOMO_SECRET_KEY}")
fi
if [ ! -z "${AZURE_STORAGE_ACCOUNT:-}" ]; then
    ENV_VARS_ARGS+=("AZURE_STORAGE_ACCOUNT=${AZURE_STORAGE_ACCOUNT}")
fi
if [ ! -z "${AZURE_STORAGE_CONTAINER:-}" ]; then
    ENV_VARS_ARGS+=("AZURE_STORAGE_CONTAINER=${AZURE_STORAGE_CONTAINER}")
fi
if [ ! -z "${AZURE_API_KEY:-}" ]; then
    ENV_VARS_ARGS+=("AZURE_API_KEY=${AZURE_API_KEY}")
fi
if [ ! -z "${TEST_DATASET_IDS:-}" ]; then
    ENV_VARS_ARGS+=("TEST_DATASET_IDS=${TEST_DATASET_IDS}")
fi
if [ ! -z "${DOMO_MASTER_DATASET_ID:-}" ]; then
    ENV_VARS_ARGS+=("DOMO_MASTER_DATASET_ID=${DOMO_MASTER_DATASET_ID}")
fi
if [ ! -z "${CORS_ORIGINS:-}" ]; then
    ENV_VARS_ARGS+=("CORS_ORIGINS=${CORS_ORIGINS}")
fi
if [ ! -z "${QDRANT_URL:-}" ]; then
    ENV_VARS_ARGS+=("QDRANT_URL=${QDRANT_URL}")
fi
if [ ! -z "${QDRANT_API_KEY:-}" ]; then
    ENV_VARS_ARGS+=("QDRANT_API_KEY=${QDRANT_API_KEY}")
fi
if [ ! -z "${QDRANT_COLLECTION_NAME:-}" ]; then
    ENV_VARS_ARGS+=("QDRANT_COLLECTION_NAME=${QDRANT_COLLECTION_NAME}")
fi
if [ ! -z "${QDRANT_VECTOR_SIZE:-}" ]; then
    ENV_VARS_ARGS+=("QDRANT_VECTOR_SIZE=${QDRANT_VECTOR_SIZE}")
fi
if [ ! -z "${QDRANT_USE_GRPC:-}" ]; then
    ENV_VARS_ARGS+=("QDRANT_USE_GRPC=${QDRANT_USE_GRPC}")
fi

if [ -z "$APP_EXISTS" ]; then
    echo -e "${YELLOW}Creating new Container App with environment variables...${NC}"
    az containerapp create \
        --name "${CONTAINER_APP_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --environment "${CONTAINER_APP_ENV}" \
        --image "${REGISTRY_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}" \
        --registry-server "${REGISTRY_LOGIN_SERVER}" \
        --registry-username "${REGISTRY_USERNAME}" \
        --registry-password "${REGISTRY_PASSWORD}" \
        --target-port 8000 \
        --ingress external \
        --revision-suffix "${REVISION_SUFFIX}" \
        --min-replicas 1 \
        --max-replicas 3 \
        --cpu 0.5 \
        --memory 1.0Gi \
        --env-vars "${ENV_VARS_ARGS[@]}" \
        --output none
    
    echo -e "${GREEN}Container App created successfully.${NC}"
else
    echo -e "${YELLOW}Container App already exists. Updating...${NC}"
    az containerapp update \
        --name "${CONTAINER_APP_NAME}" \
        --resource-group "${RESOURCE_GROUP}" \
        --image "${REGISTRY_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}" \
        --revision-suffix "${REVISION_SUFFIX}" \
        --set-env-vars "${ENV_VARS_ARGS[@]}" \
        --output none
    
    echo -e "${GREEN}Container App updated successfully.${NC}"
fi

if [ "$WITH_REINDEX" = true ]; then
    echo ""
    echo -e "${YELLOW}--with-reindex flag detected. Reindexing production Qdrant and clearing caches...${NC}"
    if [ -z "${PROD_QDRANT_URL:-}" ] || [ -z "${PROD_QDRANT_API_KEY:-}" ]; then
        echo -e "${RED}Error: PROD_QDRANT_URL and PROD_QDRANT_API_KEY must be set to use --with-reindex.${NC}"
        exit 1
    fi
    export QDRANT_URL="${PROD_QDRANT_URL}"
    export QDRANT_API_KEY="${PROD_QDRANT_API_KEY}"
    if [ -n "${PROD_QDRANT_COLLECTION_NAME:-}" ]; then
        export QDRANT_COLLECTION_NAME="${PROD_QDRANT_COLLECTION_NAME}"
    fi
    python scripts/reindex_production.py --yes

    echo -e "${YELLOW}Clearing cached column_search and sql_generation entries...${NC}"
    python - <<'PY'
import os
from sqlalchemy import create_engine, text

db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise SystemExit("DATABASE_URL is required to clear cache entries.")

engine = create_engine(db_url)
with engine.begin() as conn:
    deleted = conn.execute(
        text("DELETE FROM cache_entries WHERE cache_type IN ('column_search', 'sql_generation')")
    )
    print(f"Deleted {deleted.rowcount} cache entries.")
PY
fi

# Get the app URL
APP_URL=$(az containerapp show \
    --name "${CONTAINER_APP_NAME}" \
    --resource-group "${RESOURCE_GROUP}" \
    --query properties.configuration.ingress.fqdn -o tsv)

echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo -e "${GREEN}Your API is now live at:${NC}"
echo -e "${BLUE}https://${APP_URL}${NC}"
echo ""
echo -e "${YELLOW}Test your API:${NC}"
echo -e "curl \"https://${APP_URL}/health\""
echo ""
echo -e "${YELLOW}Other endpoints:${NC}"
echo -e "  Health: https://${APP_URL}/health"
echo -e "  API Docs: https://${APP_URL}/docs"
echo -e "  Query: https://${APP_URL}/api/v1/query"
echo ""
echo -e "${YELLOW}Useful commands:${NC}"
echo -e "  View logs: az containerapp logs show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} --follow"
echo -e "  View app: az containerapp show --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP}"
echo -e "  Scale app: az containerapp update --name ${CONTAINER_APP_NAME} --resource-group ${RESOURCE_GROUP} --min-replicas 1 --max-replicas 5"
echo ""
echo -e "${YELLOW}Note: Make sure your DATABASE_URL points to an accessible PostgreSQL database.${NC}"
echo -e "${YELLOW}      The database should be accessible from Azure Container Apps.${NC}"
echo ""

