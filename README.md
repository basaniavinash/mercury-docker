# Mercury Docker

Docker Compose environment for the full Mercury microservices platform. Brings up every supporting service — databases, message broker, observability stack, authentication, and reverse proxy — with a single command.

---

## Services

| Service | Image | Purpose |
|---------|-------|---------|
| **postgres** | postgres:16 | Primary database for catalog, order, stormhook services |
| **redis** | redis:7.2 | Item cache for catalog-service |
| **kafka** | confluentinc/cp-kafka:7.6 | Event bus (KRaft mode, no Zookeeper) |
| **keycloak** | keycloak:24.0.5 | OIDC/SAML identity provider |
| **otel-collector** | otel/opentelemetry-collector | Telemetry aggregator (HTTP + gRPC) |
| **jaeger** | jaegertracing/all-in-one | Distributed trace UI |
| **prometheus** | prom/prometheus | Metrics scrape + storage |
| **loki** | grafana/loki | Log aggregation |
| **alloy** | grafana/alloy | Log shipping agent |
| **grafana** | grafana/grafana | Unified observability dashboard |
| **cadvisor** | gcr.io/cadvisor | Container resource metrics |
| **nginx** | nginx | Reverse proxy for local routing |
| **coredns** | coredns/coredns | DNS resolution for service discovery |

---

## Observability stack

```
Services (OTEL SDK)
    └─ OTLP → otel-collector
                  ├─ traces → Jaeger
                  ├─ metrics → Prometheus
                  └─ logs → Loki

Alloy (log agent) → scrapes container stdout → Loki

Grafana → unified UI querying Prometheus + Loki + Jaeger
```

Each application container has the OTEL Java agent injected via `JAVA_TOOL_OPTIONS`. This means zero code changes needed in services — tracing and metrics are attached at the infrastructure layer.

---

## Quick start

```bash
docker compose up -d
```

| UI | URL |
|----|-----|
| Grafana | http://localhost:3000 |
| Jaeger | http://localhost:16686 |
| Prometheus | http://localhost:9090 |
| Keycloak admin | http://localhost:8180 |

---

## Design decisions

### Single-node Kafka with KRaft

Kafka runs in combined broker + controller mode (KRaft), eliminating the Zookeeper dependency. A single node is sufficient for local development — no replica complexity, no ZK port to expose.

### OTEL agent injection via environment variable

`JAVA_TOOL_OPTIONS=-javaagent:/otel-agent.jar` is set on app containers rather than baked into application images. This decouples instrumentation from application code — the agent version can be upgraded in one place without touching any service.

### Keycloak for realistic auth testing

Rather than mocking OAuth2, the stack runs a real Keycloak instance. Realm configs are imported on startup from `keycloak/`. This means local integration tests use the same OIDC flow as production.

### CoreDNS for service discovery

A local CoreDNS instance resolves `*.mercury.local` hostnames to the Nginx reverse proxy. Services can call each other by hostname rather than hardcoded `localhost:PORT` — closer to production Kubernetes DNS behavior.
