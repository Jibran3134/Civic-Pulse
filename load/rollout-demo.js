import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
  stages: [
    { duration: '30s', target: 20 },   // Ramp up to 20 VUs
    { duration: '2m', target: 20 },    // Steady state for rollout
    { duration: '30s', target: 50 },   // Ramp up during rollout
    { duration: '2m', target: 50 },    // Sustained load during rollout
    { duration: '30s', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(99)<5000'],
    http_req_failed: ['rate<0.001'],   // <0.1% transport failures
    errors: ['rate<0.001'],
    // A "zero-downtime" claim has to mean zero, not "nearly zero": no request may
    // fail its checks (wrong status or missing triage category) during the rollout.
    failed_requests: ['count==0'],
  },
};

const errorRate = new Rate('errors');
const requestDuration = new Trend('request_duration');
const successCount = new Counter('successful_requests');
const failureCount = new Counter('failed_requests');

const complaints = [
  { text: "Water main burst on Mall Road since fajr water entering ground floors", location: "Mall Road, Lahore" },
  { text: "Streetlight not working at intersection of Ferozepur Road and Canal Bank", location: "Ferozepur Road, Lahore" },
  { text: "Garbage not collected for 3 days in Model Town block B", location: "Model Town, Lahore" },
  { text: "Large pothole on Main Boulevard Gulberg causing traffic jams", location: "Main Boulevard Gulberg, Lahore" },
  { text: "Electricity outage in DHA Phase 5 since last night", location: "DHA Phase 5, Lahore" },
  { text: "Sewage overflow near Data Darbar, foul smell everywhere", location: "Data Darbar, Lahore" },
  { text: "Water supply contaminated in Johar Town, yellow color coming from taps", location: "Johar Town, Lahore" },
  { text: "Broken traffic signal at Kalma Chowk causing accidents", location: "Kalma Chowk, Lahore" },
  { text: "Streetlight flickering on MM Alam Road for past week", location: "MM Alam Road, Lahore" },
  { text: "Trash piling up near Liberty Market parking area", location: "Liberty Market, Lahore" },
];

export default function () {
  const complaint = complaints[Math.floor(Math.random() * complaints.length)];
  
  const payload = JSON.stringify({
    text: complaint.text,
    location: complaint.location,
    reporter_contact: `0300-${Math.floor(Math.random() * 9000000) + 1000000}`,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
    timeout: '30s',
  };

  const startTime = Date.now();
  const res = http.post(`${BASE_URL}/api/complaints`, payload, params);
  const duration = Date.now() - startTime;

  requestDuration.add(duration);
  
  const success = check(res, {
    'status is 201': (r) => r.status === 201,
    'response has category': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.category !== undefined;
      } catch {
        return false;
      }
    },
  });

  if (success) {
    successCount.add(1);
    errorRate.add(0);
  } else {
    failureCount.add(1);
    errorRate.add(1);
  }

  sleep(Math.random() * 1 + 0.2);
}

export function handleSummary(data) {
  return {
    'stdout': textSummary(data),
    'summary.json': JSON.stringify(data),
  };
}

// `http_req_failed` is a Rate: its `passes` are the requests that PASSED the
// failure threshold, i.e. the *successful* ones. Reading it as "failed requests"
// (the previous bug) inverted every number and made the verdict meaningless.
function failedRequestCount(data) {
  const total = data.metrics.http_reqs?.values?.count || 0;
  const passes = data.metrics.http_req_failed?.values?.passes;
  if (passes !== undefined) {
    return Math.max(0, total - passes);
  }
  // Older k6 builds omit `passes` in the summary; fall back to the rate.
  const rate = data.metrics.http_req_failed?.values?.rate || 0;
  return Math.round(rate * total);
}

function textSummary(data) {
  const indent = '  ';
  let output = '\n=== ZERO-DOWNTIME ROLLOUT TEST SUMMARY ===\n\n';

  if (data.metrics.http_req_duration) {
    const m = data.metrics.http_req_duration;
    output += `${indent}HTTP Request Duration:\n`;
    output += `${indent}  avg: ${formatMs(m.values.avg)}\n`;
    output += `${indent}  min: ${formatMs(m.values.min)}\n`;
    output += `${indent}  max: ${formatMs(m.values.max)}\n`;
    output += `${indent}  p90: ${formatMs(m.values['p(90)'])}\n`;
    output += `${indent}  p95: ${formatMs(m.values['p(95)'])}\n`;
    output += `${indent}  p99: ${formatMs(m.values['p(99)'])}\n\n`;
  }

  const total = data.metrics.http_reqs?.values?.count || 0;
  const failed = failedRequestCount(data);
  const failureRate = total > 0 ? (failed / total * 100) : 0;

  // Requests that failed OUR checks (status 201 + category present), which is a
  // stricter signal than transport-level http_req_failed alone.
  const checkFailures = data.metrics.failed_requests?.values?.count || 0;
  const checkTotal = data.metrics.successful_requests?.values?.count || 0;

  output += `${indent}Total Requests: ${total}\n`;
  output += `${indent}Failed Requests (HTTP-level): ${failed}\n`;
  output += `${indent}Failed Rate (HTTP-level): ${failureRate.toFixed(4)}%\n`;
  output += `${indent}Checks Passed: ${checkTotal}\n`;
  output += `${indent}Checks Failed: ${checkFailures}\n`;

  if (data.metrics.errors) {
    output += `${indent}Error Rate: ${(data.metrics.errors.values.rate * 100).toFixed(4)}%\n`;
  }

  // Zero-downtime verdict: no request may be lost or fail its checks during the
  // rollout. Derive it from the real numbers, not from a threshold being "close".
  const zeroFailures = failed === 0 && checkFailures === 0 && total > 0;
  output += `\n${indent}=== ZERO-DOWNTIME VERDICT ===\n`;
  if (zeroFailures) {
    output += `${indent}PASS - 0 of ${total} requests failed during the rolling update.\n`;
  } else {
    output += `${indent}FAIL - ${failed} HTTP failure(s) and ${checkFailures} check failure(s) out of ${total} requests.\n`;
    output += `${indent}       Thresholds require http_req_failed rate<0.001 and failed_requests count==0.\n`;
  }

  return output;
}

function formatMs(ms) {
  if (ms === undefined || ms === null) return 'N/A';
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}