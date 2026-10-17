#!/bin/sh
# Remove everything create-host.sh made (instance first; the security group is in use until it is gone).
set -eu
REGION=us-east-1
ID=$(aws ec2 describe-instances --region $REGION --filters Name=tag:project,Values=ratified \
  Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' --output text)
[ -n "$ID" ] && aws ec2 terminate-instances --region $REGION --instance-ids $ID >/dev/null && \
  aws ec2 wait instance-terminated --region $REGION --instance-ids $ID
SG=$(aws ec2 describe-security-groups --region $REGION --filters Name=group-name,Values=ratified-sg --query 'SecurityGroups[0].GroupId' --output text)
[ "$SG" != "None" ] && aws ec2 delete-security-group --region $REGION --group-id "$SG"
aws ec2 delete-key-pair --region $REGION --key-name ratified-key
rm -f "$HOME/.ssh/ratified-key.pem"
