import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
  stages: [
    { duration: '30s', target: 5 },   // Ramp up to 5 VUs
    { duration: '1m', target: 10 },   // Stay at 10 VUs
    { duration: '30s', target: 20 },  // Ramp up to 20 VUs
    { duration: '1m', target: 20 },   // Stay at 20 VUs
    { duration: '30s', target: 50 },  // Ramp up to 50 VUs
    { duration: '1m', target: 50 },   // Stay at 50 VUs
    { duration: '30s', target: 0 },   // Ramp down to 0
  ],
  thresholds: {
    http_req_duration: ['p(95)<2000'],
    http_req_failed: ['rate<0.01'],
    // The `errors` Rate tracks checks (201 + category/priority/triaged_by), which
    // is what the triage contract actually promises, so gate on it too.
    errors: ['rate<0.01'],
  },
};

const errorRate = new Rate('errors');
const requestDuration = new Trend('request_duration');
const triageDuration = new Trend('triage_duration');
const fallbackCount = new Counter('fallback_total');

const complaints = [
  { text: "Water main burst on Mall Road since fajr, water entering ground floors of houses", location: "Mall Road, Lahore" },
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
    'response has priority': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.priority !== undefined;
      } catch {
        return false;
      }
    },
    'response has triaged_by': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.triaged_by !== undefined;
      } catch {
        return false;
      }
    },
  });

  if (!success) {
    errorRate.add(1);
  } else {
    errorRate.add(0);
    try {
      const body = JSON.parse(res.body);
      if (body.triage_latency_ms) {
        triageDuration.add(body.triage_latency_ms);
      }
      if (body.triaged_by === 'rules:fallback') {
        fallbackCount.add(1);
      }
    } catch {}
  }

  sleep(Math.random() * 2 + 0.5);
}

export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'summary.json': JSON.stringify(data),
  };
}

function textSummary(data, options) {
  const indent = options.indent || '';
  let output = '\n';
  output += `${indent}=== k6 Load Test Summary ===\n\n`;
  
  if (data.metrics.http_req_duration) {
    const m = data.metrics.http_req_duration;
    output += `${indent}HTTP Request Duration:\n`;
    output += `${indent}  avg: ${formatMs(m.values.avg)}\n`;
    output += `${indent}  min: ${formatMs(m.values.min)}\n`;
    output += `${indent}  max: ${formatMs(m.values.max)}\n`;
    output += `${indent}  p90: ${formatMs(m.values['p(90)'])}\n`;
    output += `${indent}  p95: ${formatMs(m.values['p(95)'])}\n\n`;
  }
  
  if (data.metrics.http_reqs) {
    output += `${indent}Total Requests: ${data.metrics.http_reqs.values.count}\n`;
  }
  
  // `http_req_failed` is a Rate, so `passes` counts the requests that PASSED the
  // failure threshold (i.e. the successful ones). Deriving the failure count as
  // count - passes is the only way to get a real number out of the summary.
  const total = data.metrics.http_reqs?.values?.count || 0;
  const passes = data.metrics.http_req_failed?.values?.passes;
  const failed = passes !== undefined
    ? Math.max(0, total - passes)
    : Math.round((data.metrics.http_req_failed?.values?.rate || 0) * total);
  
  output += `${indent}Failed Requests: ${failed} of ${total}\n`;
  if (data.metrics.http_req_failed) {
    output += `${indent}Failed Rate: ${(data.metrics.http_req_failed.values.rate * 100).toFixed(2)}%\n`;
  }
  
  if (data.metrics.errors) {
    output += `${indent}Error Rate: ${(data.metrics.errors.values.rate * 100).toFixed(2)}%\n`;
  }
  
  if (data.metrics.triage_duration) {
    const m = data.metrics.triage_duration;
    output += `${indent}Triage Latency:\n`;
    output += `${indent}  avg: ${formatMs(m.values.avg)}\n`;
    output += `${indent}  p95: ${formatMs(m.values['p(95)'])}\n\n`;
  }
  
  if (data.metrics.fallback_total) {
    output += `${indent}Fallback Count: ${data.metrics.fallback_total.values.count}\n`;
  }
  
  return output;
}

function formatMs(ms) {
  if (ms === undefined || ms === null) return 'N/A';
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}