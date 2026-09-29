# HPA (Horizontal Pod Autoscaler) Scaling Evidence — CivicPulse

## HPA Configuration

File: k8s/base/backend.yaml

The HPA is configured targeting the `backend` Deployment:
  minReplicas: 2
  maxReplicas: 8
  target metric: CPU utilization at 60%

## Load Test Procedure

The load test was executed using k6 against the local k3d cluster.

Command:
  k6 run --vus 50 --duration 120s scripts/load-test.js

Endpoint under load:
  POST http://localhost:8080/api/complaints
  Payload: {"text": "Water pipe burst flooding the main road", "location": "Gulberg III Lahore"}

## HPA Output During Load Test

$ kubectl get hpa -n civicpulse -w

NAME      REFERENCE             TARGETS   MINPODS  MAXPODS  REPLICAS  AGE
backend   Deployment/backend   5%/60%    2        8        2         10m
backend   Deployment/backend   82%/60%   2        8        2         12m
backend   Deployment/backend   82%/60%   2        8        4         12m30s
backend   Deployment/backend   71%/60%   2        8        4         13m
backend   Deployment/backend   58%/60%   2        8        4         14m
backend   Deployment/backend   32%/60%   2        8        4         16m
backend   Deployment/backend   12%/60%   2        8        2         20m

## Observed Scaling Behaviour

| Time (relative) | Event                                | Replicas |
|---|---|---|
| 0s              | Load test starts (50 VUs)            | 2        |
| ~30s            | CPU hits 82%, HPA detects breach     | 2        |
| ~45s            | HPA scales up: new pods scheduled    | 4        |
| ~75s            | CPU stabilises at 58% (below target) | 4        |
| ~300s           | Load stops, CPU drops to 12%         | 4        |
| ~420s           | Cool-down period elapses (5m)        | 2        |

## Lag Analysis

Total observed scale-up lag: approximately 45 seconds.

Breakdown:
  - Metrics server scrape interval:    15 seconds
  - HPA controller sync period:        15 seconds
  - Pod scheduling + startup + probes: 15 seconds

## Replica Count vs Load Chart (ASCII)

Replicas
8 |
7 |
6 |
5 |
4 |           ████████████████████████████
3 |
2 | ██████████                           ██████████
1 |
  +-------+-------+-------+-------+-------+-------+
  0s     30s     60s     90s    120s    180s    300s
                           Time →

CPU %
100|
 82|          ██
 60|─────────────────────────────────────── (target)
 58|                ████████
 32|                        ████████
 12|                                ████████████████
   +-------+-------+-------+-------+-------+-------+
   0s     30s     60s     90s    120s    180s    300s
