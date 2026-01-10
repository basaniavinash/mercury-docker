#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for Kafka..."
for i in {1..120}; do
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list >/dev/null 2>&1 && break
  sleep 1
done

echo "Creating topics..."
bash /var/kafka/topics/create-order-created-topic.sh
bash /var/kafka/topics/create-inventory-reserved-topic.sh
bash /var/kafka/topics/create-inventory-rejected-topic.sh

echo "Done."