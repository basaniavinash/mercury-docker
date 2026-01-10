#! /bin/bash
set -euxo pipefail

topic_name=inventory.inventory-reserved.v1

/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --topic "${topic_name}" --partitions 3 --replication-factor 1 --if-not-exists