#!/usr/bin/env bash
# Deploy or update the BeeView stack (Windows EC2 + internal ALB) in the landscape-modelling account.
#
#   deploy/aws/deploy.sh package     # build xpollinator.zip, beeview-server.zip, data.zip in ../_deploy (no AWS needed;
#                                    # also the input for deploy/windows/install.ps1 on a plain Windows server)
#   deploy/aws/deploy.sh upload      # package + upload artefacts to the deploy bucket
#   deploy/aws/deploy.sh stack       # create/update the CloudFormation stack
#   deploy/aws/deploy.sh redeploy    # re-run bootstrap.ps1 on the instance via SSM (new artefacts, keeps data)
#   deploy/aws/deploy.sh status
#
# Requires: aws cli logged in (AWS_PROFILE below), tar with zip support (Git for Windows).
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sso-standard-user-414678956813}"
export AWS_DEFAULT_REGION=eu-central-1
STACK=beeview
BUCKET=beeview-deploy-414678956813
PREFIX="${ARTIFACT_PREFIX:-v1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"          # ...\xLandscape
WORK="${DEPLOY_WORK:-$ROOT/_deploy}"
VPC=vpc-0c2ca46d3a0c14840
SUBNETS="subnet-0cf6a7f99dd9eec91,subnet-0d7733ed6c8681da2"   # private subnets 1a, 1b
ZONE=Z05279652JUA9IG0A9IWN                                     # 414678956813.cloud.bayer.com
DOMAIN=beeview.414678956813.cloud.bayer.com
AUTH_MODE="${AUTH_MODE:-none}"                                 # none | oidc (needs secret beeview/entra-oidc)

latest_ami() {
  aws ec2 describe-images --owners 905084838059 --executable-users self \
    --filters "Name=name,Values=bay-windows-2022_*" "Name=state,Values=available" \
    --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text
}

package() {
  mkdir -p "$WORK"
  echo "packaging xPollinator"
  tar -a -cf "$WORK/xpollinator.zip" -C "$ROOT" \
    --exclude=xPollinator/run --exclude=xPollinator/.git --exclude=xPollinator/scripts/homologa \
    --exclude=xPollinator/node_modules --exclude="*/__pycache__" --exclude=xPollinator/.claude \
    --exclude="xPollinator/*.log" xPollinator
  echo "packaging BeeView-server"
  tar -a -cf "$WORK/beeview-server.zip" -C "$ROOT" \
    --exclude=BeeView-server/venv --exclude=BeeView-server/data --exclude=BeeView-server/.git \
    --exclude=BeeView-server/experiments --exclude=BeeView-server/BeeView-portable \
    --exclude="*/__pycache__" --exclude="BeeView-server/*.log" --exclude="BeeView-server/*.png" \
    --exclude=BeeView-server/nul --exclude=BeeView-server/.claude BeeView-server
  echo "packaging data (stop the local BeeView server first: DuckDB holds an exclusive lock)"
  rm -rf "$WORK/data" && mkdir -p "$WORK/data"
  cp "$ROOT/BeeView-server/data/beeview.duckdb" "$WORK/data/" || { echo "beeview.duckdb is locked, stop the server and retry"; exit 1; }
  cp "$ROOT/BeeView-server/data/arr.dat" "$ROOT/BeeView-server/data/"*.csv "$ROOT/BeeView-server/data/"*.json "$ROOT/BeeView-server/data/"Tarn_LULC_v04.* "$WORK/data/"
  cp -r "$ROOT/BeeView-server/data/cache" "$WORK/data/"
  tar -a -cf "$WORK/data.zip" -C "$WORK" data
  cp "$HERE/../windows/install.ps1" "$WORK/"
  ls -la "$WORK"/*.zip "$WORK/install.ps1"
}

upload() {
  package
  # python-3.11-amd64.exe is optional here: bootstrap.ps1 downloads and signature-checks it on the instance when absent.
  for f in xpollinator.zip beeview-server.zip data.zip; do
    aws s3 cp "$WORK/$f" "s3://$BUCKET/$PREFIX/$f" --only-show-errors
  done
  aws s3 cp "$HERE/bootstrap.ps1" "s3://$BUCKET/$PREFIX/bootstrap.ps1" --only-show-errors
  aws s3 ls "s3://$BUCKET/$PREFIX/"
}

stack() {
  local ami; ami="$(latest_ami)"
  echo "AMI: $ami"
  aws cloudformation deploy --stack-name "$STACK" --template-file "$HERE/beeview-ec2-alb.yaml" \
    --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
    --parameter-overrides VpcId="$VPC" PrivateSubnetIds="$SUBNETS" AmiId="$ami" HostedZoneId="$ZONE" \
      DomainName="$DOMAIN" DeployBucket="$BUCKET" ArtifactPrefix="$PREFIX" AuthMode="$AUTH_MODE" \
      AllowedCidrs="10.0.0.0/8"
  status
}

status() {
  aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].[StackStatus,Outputs]' --output table
}

redeploy() {
  local id; id="$(aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' --output text)"
  local cmd; cmd="$(aws ssm send-command --instance-ids "$id" --document-name AWS-RunPowerShellScript \
    --parameters commands="[\"Import-Module AWSPowerShell; Read-S3Object -BucketName $BUCKET -Key $PREFIX/bootstrap.ps1 -File C:\\\\xLandscape\\\\bootstrap.ps1 -Region eu-central-1 | Out-Null; powershell.exe -ExecutionPolicy Bypass -File C:\\\\xLandscape\\\\bootstrap.ps1\"]" \
    --timeout-seconds 3600 --query 'Command.CommandId' --output text)"
  echo "SSM command $cmd on $id"
  aws ssm wait command-executed --command-id "$cmd" --instance-id "$id" || true
  aws ssm get-command-invocation --command-id "$cmd" --instance-id "$id" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text | tail -40
}

case "${1:-}" in
  package) package ;;
  upload) upload ;;
  stack) stack ;;
  redeploy) redeploy ;;
  status) status ;;
  *) echo "usage: $0 package|upload|stack|redeploy|status"; exit 1 ;;
esac
