#!/usr/bin/env bash
set -e

PROJECT_ID="edgepulse-prod-509316"
PROJECT_NUM="508845137062"
REGION="asia-south1"
REPO_NAME="edgepulse-repo"
IMAGE_NAME="edgepulse"
FULL_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:latest"
SA_NAME="edgepulse-builder"
BUILDER_SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=================================================="
echo "  Deploying EdgePulse to Google Cloud Run"
echo "  Project: ${PROJECT_ID}"
echo "  Region:  ${REGION}"
echo "=================================================="

# 1. Ensure required Google Cloud APIs are enabled
echo "[1/5] Checking Google Cloud APIs..."
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  compute.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  --project="${PROJECT_ID}" --quiet

# 2. Ensure dedicated service account exists
echo "[2/5] Setting up dedicated builder & runtime service account..."
gcloud iam service-accounts describe "${BUILDER_SA}" --project="${PROJECT_ID}" >/dev/null 2>&1 || \
gcloud iam service-accounts create "${SA_NAME}" \
  --description="Dedicated Cloud Build & Run service account for EdgePulse" \
  --display-name="EdgePulse Builder & Runtime" \
  --project="${PROJECT_ID}" --quiet

# Grant essential roles to the dedicated service account
echo "Assigning IAM roles to ${BUILDER_SA}..."
for role in roles/cloudbuild.builds.builder roles/logging.logWriter roles/storage.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${BUILDER_SA}" \
    --role="${role}" --quiet >/dev/null 2>&1 || true
done

# Grant current user permission to impersonate this service account
echo "Granting Service Account User permissions..."
gcloud iam service-accounts add-iam-policy-binding "${BUILDER_SA}" \
  --member="user:nithish0014@gmail.com" \
  --role="roles/iam.serviceAccountUser" \
  --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="user:nithish0014@gmail.com" \
  --role="roles/iam.serviceAccountUser" --quiet >/dev/null 2>&1 || true

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

# 4. Build and push image using Google Cloud Build with the dedicated service account
echo "[4/5] Submitting build to Google Cloud Build using ${BUILDER_SA}..."
gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=_IMAGE="${FULL_IMAGE}" \
  --service-account="projects/${PROJECT_ID}/serviceAccounts/${BUILDER_SA}" .

# 5. Deploy container to Cloud Run with dedicated service account for storage access
echo "[5/5] Deploying container to Cloud Run in multiple regions..."

REGIONS=("asia-south1" "asia-southeast1")

for DEPLOY_REGION in "${REGIONS[@]}"; do
  echo ">>> Deploying to ${DEPLOY_REGION}..."
  gcloud run deploy edgepulse \
    --image="${FULL_IMAGE}" \
    --service-account="${BUILDER_SA}" \
    --region="${DEPLOY_REGION}" \
    --project="${PROJECT_ID}" \
    --platform=managed \
    --allow-unauthenticated \
    --memory=512Mi \
    --cpu=1 \
    --timeout=300 \
    --concurrency=80
done

echo "=================================================="
echo "  Deployment completed successfully!"
echo "=================================================="
