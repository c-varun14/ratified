#!/bin/sh
# Create the Ratified demo host: one t3.small (Amazon Linux 2023) in us-east-1 with its
# own key pair and security group (80 public, 22 from this machine only), all tagged
# project=ratified. Prints the public IP. Roughly $16/month while running; see teardown.
set -eu
REGION=us-east-1
KEY=ratified-key
PEM="$HOME/.ssh/$KEY.pem"
HERE=$(cd "$(dirname "$0")" && pwd)
MYIP=$(curl -s https://checkip.amazonaws.com)
VPC=$(aws ec2 describe-vpcs --region $REGION --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)

EXISTING=$(aws ec2 describe-instances --region $REGION --filters Name=tag:project,Values=ratified \
  Name=instance-state-name,Values=pending,running --query 'Reservations[0].Instances[0].[InstanceId,PublicIpAddress]' --output text)
if [ -n "$EXISTING" ] && [ "$EXISTING" != "None" ]; then
  set -- $EXISTING
  SG=$(aws ec2 describe-security-groups --region $REGION --filters Name=group-name,Values=ratified-sg --query 'SecurityGroups[0].GroupId' --output text)
  aws ec2 authorize-security-group-ingress --region $REGION --group-id "$SG" --protocol tcp --port 22 --cidr "$MYIP/32" >/dev/null 2>&1 || true
  echo "instance=$1 already running; ip=$2 (ssh allowed from $MYIP)"
  echo "$2" > "$HERE/.host"
  exit 0
fi

if [ ! -f "$PEM" ]; then
  aws ec2 create-key-pair --region $REGION --key-name $KEY \
    --tag-specifications 'ResourceType=key-pair,Tags=[{Key=project,Value=ratified}]' \
    --query KeyMaterial --output text > "$PEM"
  chmod 400 "$PEM"
fi

SG=$(aws ec2 create-security-group --region $REGION --group-name ratified-sg \
  --description "Ratified demo: http public, ssh from deploy host" --vpc-id "$VPC" \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=project,Value=ratified}]' \
  --query GroupId --output text)
aws ec2 authorize-security-group-ingress --region $REGION --group-id "$SG" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
aws ec2 authorize-security-group-ingress --region $REGION --group-id "$SG" --protocol tcp --port 22 --cidr "$MYIP/32" >/dev/null

ID=$(aws ec2 run-instances --region $REGION \
  --image-id resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --instance-type t3.small --key-name $KEY --security-group-ids "$SG" \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=12,VolumeType=gp3,DeleteOnTermination=true}' \
  --user-data "file://$HERE/userdata.sh" \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=project,Value=ratified},{Key=Name,Value=ratified}]' \
  --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-running --region $REGION --instance-ids "$ID"
IP=$(aws ec2 describe-instances --region $REGION --instance-ids "$ID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "instance=$ID sg=$SG ip=$IP"
echo "$IP" > "$HERE/.host"
