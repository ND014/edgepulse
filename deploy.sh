#!/usr/bin/env bash
set -e

PROJECT_ID="edgepulse-prod-509316"
PROJECT_NUM="508845137062"
REGION="asia-south1"
REPO_NAME="edgepulse-repo"
IMAGE_NAME="edgepulse"
FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:latest"
COMPUTE_SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"
CLOUDBUILD_SA="${PROJECT_NUM}@cloudbuild.gserviceaccount.com"

echo "=================================================="
echo "  Deploying EdgePulse to Google Cloud Run"
echo "  Project: ${PROJECT_ID}"
echo "  Region:  ${REGION}"
echo "=================================================="

# 1. Ensure required APIs are enabled
echo "[1/4] Checking Google Cloud APIs..."
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  compute.googleapis.com \
  cloudbuild.googleapis.com \
  --project="${PROJECT_ID}" --quiet

# 2. Ensure IAM roles for Cloud Build and Compute service accounts
echo "[2/4] Ensuring build IAM permissions..."
for role in roles/cloudbuild.builds.builder roles/logging.logWriter roles/storage.objectAdmin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="${role}" --quiet >/dev/null 2>&1 || true
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="${role}" --quiet >/dev/null 2>&1 || true
done

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="user:nithish0014@gmail.com" \
  --role="roles/iam.serviceAccountUser" --quiet >/dev/null 2>&1 || true

# 3. Create Artifact Registry repository if it doesn't already exist
echo "[3/4] Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories describe "${REPO_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1 || \
gcloud artifacts repositories create "${REPO_NAME}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="EdgePulse Docker Repository" \
  --project="${PROJECT_ID}" --quiet

# 4. Build and push image using Google Cloud Build
echo "[4/4] Submitting build to Google Cloud Build..."
gcloud builds submit --tag "${FULL_IMAGE}" .

# 5. Deploy container to Cloud Run
echo "Deploying container to Cloud Run..."
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
