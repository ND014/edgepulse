#!/usr/bin/env bash
set -e

PROJECT_ID="edgepulse-prod-509316"
REGION="asia-south1"
REPO_NAME="edgepulse-repo"
IMAGE_NAME="edgepulse"
FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:latest"

echo "=================================================="
echo "  Deploying EdgePulse to Google Cloud Run"
echo "  Project: ${PROJECT_ID}"
echo "  Region:  ${REGION}"
echo "=================================================="

# 1. Ensure required APIs are enabled
echo "[1/5] Checking Google Cloud APIs..."
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  compute.googleapis.com \
  --project="${PROJECT_ID}" --quiet

# 2. Configure Docker authentication for Artifact Registry
echo "[2/5] Configuring Docker authentication for ${REGION}-docker.pkg.dev..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# 3. Create Artifact Registry repository if it doesn't already exist
echo "[3/5] Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories describe "${REPO_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1 || \
gcloud artifacts repositories create "${REPO_NAME}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="EdgePulse Docker Repository" \
  --project="${PROJECT_ID}" --quiet

# 4. Build Docker image locally in Cloud Shell
echo "[4/5] Building Docker image locally..."
docker build -t "${FULL_IMAGE}" .

# 5. Push image to Artifact Registry
echo "[5/5] Pushing image to Artifact Registry..."
docker push "${FULL_IMAGE}"

# 6. Deploy image directly to Cloud Run
echo "Deploying container image to Cloud Run..."
gcloud run deploy edgepulse \
  --image="${FULL_IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --platform=managed \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --timeout=300 \
  --concurrency=80

echo "=================================================="
echo "  Deployment completed successfully!"
echo "=================================================="
