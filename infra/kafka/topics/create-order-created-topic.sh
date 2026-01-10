#!/bin/bash
set -euxo pipefail
topic_name=orders.order-created.v1

/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --topic "orders.order-created.v1" --partitions 3 --replication-factor 1 --if-not-exists