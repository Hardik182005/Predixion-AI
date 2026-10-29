#!/usr/bin/env bash
# Builds one commit with Cloud Build and deploys it to the predixion-ai Cloud Run service by image digest.
# The build context is a `git archive` of the commit, so untracked files and .env never leave this machine.
# The one-time setup (registry, bucket, service accounts, secrets) is in docs/deployment.md.
#
# Usage: GCP_ACCOUNT=you@example.com deploy/deploy.sh [git-ref]    (default HEAD)
set -euo pipefail

ref="${1:-HEAD}"
account="${GCP_ACCOUNT:?Set GCP_ACCOUNT to the gcloud account to deploy with.}"
project="${GCP_PROJECT:-quantfolio-511108}"
region="${GCP_REGION:-asia-south1}"
service="${SERVICE:-predixion-ai}"
bucket="gs://${BUILD_BUCKET:-predixion-ai-511108-build}"
state_bucket="${STATE_BUCKET:-predixion-ai-511108-state}"
image="$region-docker.pkg.dev/$project/predixion-ai/predixion-ai"
build_sa="predixion-build@$project.iam.gserviceaccount.com"
run_sa="predixion-run@$project.iam.gserviceaccount.com"
gc=(gcloud --account="$account" --project="$project" --quiet)

# gcloud on Windows needs native paths; Git Bash provides cygpath.
native() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

commit="$(git rev-parse --verify "$ref^{commit}")"
tag="${commit:0:12}"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
git -c core.autocrlf=false -c core.eol=lf archive --format=tar.gz -o "$workdir/source.tgz" "$commit"
git show "$commit:deploy/cloudbuild.yaml" >"$workdir/cloudbuild.yaml"

echo "Building $image:$tag from commit $commit"
"${gc[@]}" builds submit "$(native "$workdir/source.tgz")" \
  --region="$region" \
  --config="$(native "$workdir/cloudbuild.yaml")" \
  --substitutions="_IMAGE=$image,_TAG=$tag" \
  --service-account="projects/$project/serviceAccounts/$build_sa" \
  --gcs-source-staging-dir="$bucket/source" \
  --gcs-log-dir="$bucket/logs"

digest="$("${gc[@]}" artifacts docker images describe "$image:$tag" --format='value(image_summary.digest)')"
number="$("${gc[@]}" projects describe "$project" --format='value(projectNumber)')"
url="https://$service-$number.$region.run.app"

# Visitors get fixture runs by default and may choose live research, within the live-run limits below.
# LIVE_RUNS_PER_DAY x MAX_COST_USD_PER_RUN bounds daily provider spend (20 x $0.30 = $6 at most). The ledger on the
# state bucket keeps that count across restarts and scale-to-zero; if it cannot be written, live runs are refused.
env=(
  PREDIXION_ENV=production
  PREDIXION_MODE=fixture
  AUTH_MODE=token
  PUBLIC_ACCESS=live
  LIVE_RUNS_PER_USER_PER_HOUR=3
  LIVE_RUNS_PER_DAY=20
  LIVE_LEDGER_PATH=/app/ledger/live-runs.json
  MAX_COST_USD_PER_RUN=0.30
  MAX_CONCURRENT_RUNS=3
  MAX_QUEUED_RUNS=6
  RUN_RETENTION_DAYS=1
  HSTS_MAX_AGE_S=31536000
  "CORS_ORIGINS=$url"
  LOG_LEVEL=INFO
)
secrets=(
  OPENAI_API_KEY=predixion-openai-api-key:latest
  TAVILY_API_KEY=predixion-tavily-api-key:latest
  GROQ_API_KEY=predixion-groq-api-key:latest
  API_TOKEN_HASHES=predixion-api-token-hashes:latest
)
join() { local IFS=,; printf '%s' "$*"; }

# One instance only: runs live in that process's memory and SQLite on its local disk (see docs/deployment.md).
# CPU stays allocated between requests so a run keeps going after the browser stops watching.
# Cloud Storage volumes need the gen2 environment; the mount belongs to the image's non-root user (uid 10001).
echo "Deploying $image@$digest"
# Git Bash on Windows would rewrite the /app/... paths in these two arguments into Windows paths; elsewhere this is unused.
MSYS2_ARG_CONV_EXCL="--add-volume-mount=;--set-env-vars=" "${gc[@]}" run deploy "$service" \
  --region="$region" \
  --image="$image@$digest" \
  --service-account="$run_sa" \
  --allow-unauthenticated \
  --port=8000 \
  --cpu=1 \
  --memory=1Gi \
  --no-cpu-throttling \
  --cpu-boost \
  --concurrency=60 \
  --min-instances=0 \
  --max-instances=1 \
  --timeout=300   --execution-environment=gen2   --clear-volumes   --clear-volume-mounts   --add-volume="name=ledger,type=cloud-storage,bucket=$state_bucket,mount-options=uid=10001;gid=10001"   --add-volume-mount="volume=ledger,mount-path=/app/ledger" \
  --labels="app=predixion-ai,commit=$tag" \
  --set-env-vars="$(join "${env[@]}")" \
  --set-secrets="$(join "${secrets[@]}")"

"${gc[@]}" run services describe "$service" --region="$region" \
  --format='value(status.url,status.latestReadyRevisionName)'
