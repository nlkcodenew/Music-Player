const MAX_REQUEST_BYTES = 800000;
const MAX_TITLE_CHARS = 240;
const MAX_BODY_CHARS = 60000;
const MAX_COMMENT_CHARS = 45000;
const DEDUPE_SECONDS = 30 * 24 * 60 * 60;
const RATE_LIMIT_MAX = 20;
const RATE_LIMIT_WINDOW_SECONDS = 10 * 60;

const TOKEN_PATTERN = /\b(?:ghp|github_pat|gho|ghu|ghs|ghr)_[^\s,}\]["']+/g;
const SECRET_LINE_PATTERN = /^([^\n]*(?:token|password|passwd|secret|serial[-_ ]?(?:number|no)|machine[-_ ]?id)[^:=\n]*[:=]\s*)[^\s,}\]]+/gim;
const PRIVATE_IP_PATTERN = /\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b/g;
const MAC_PATTERN = /\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b/gi;

function jsonResponse(payload, status) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function sanitize(value) {
  return String(value)
    .replace(TOKEN_PATTERN, "[REDACTED_TOKEN]")
    .replace(SECRET_LINE_PATTERN, "$1[REDACTED]")
    .replace(PRIVATE_IP_PATTERN, "[PRIVATE_IP]")
    .replace(MAC_PATTERN, "[MAC_ADDRESS]")
    .replaceAll("\u0000", "");
}

function validBase(payload) {
  return payload &&
    payload.schema === 1 &&
    payload.app === "trimui-music-player" &&
    typeof payload.version === "string" &&
    /^[0-9]+\.[0-9]+\.[0-9]+(?:[-A-Za-z0-9.]+)?$/.test(payload.version) &&
    typeof payload.fingerprint === "string" &&
    /^[a-f0-9]{64}$/.test(payload.fingerprint);
}

function validPayload(payload) {
  return validBase(payload) &&
    typeof payload.title === "string" &&
    payload.title.startsWith("[device-log]") &&
    payload.title.length <= MAX_TITLE_CHARS &&
    typeof payload.body === "string" &&
    payload.body.length <= MAX_BODY_CHARS &&
    Array.isArray(payload.comments) &&
    payload.comments.length <= 7 &&
    payload.comments.every(
      (comment) => typeof comment === "string" && comment.length <= MAX_COMMENT_CHARS,
    );
}

async function rateLimitKey(request) {
  const address = request.headers.get("cf-connecting-ip") || "unknown";
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`trimui-music-player-relay-rate-v1\u0000${address}`),
  );
  return Array.from(new Uint8Array(digest))
    .slice(0, 12)
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function enforceRateLimit(request, env) {
  if (!env.REPORTS) {
    return false;
  }
  const now = Math.floor(Date.now() / 1000);
  const window = Math.floor(now / RATE_LIMIT_WINDOW_SECONDS);
  const key = `rate:${await rateLimitKey(request)}:${window}`;
  const count = Number(await env.REPORTS.get(key) || 0);
  if (count >= RATE_LIMIT_MAX) {
    return true;
  }
  await env.REPORTS.put(key, String(count + 1), {
    expirationTtl: RATE_LIMIT_WINDOW_SECONDS * 2,
  });
  return false;
}

async function githubRequest(env, path, body) {
  return fetch(`https://api.github.com/repos/${env.GITHUB_REPO}${path}`, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "trimui-music-player-issue-relay",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify(body),
  });
}

async function createIssue(payload, env) {
  const reportKey = `report:${payload.fingerprint}`;
  let issueNumber = 0;
  if (env.REPORTS) {
    const existing = await env.REPORTS.get(reportKey, "json");
    if (existing && existing.issue_number) {
      issueNumber = existing.issue_number;
    }
  }
  if (!issueNumber) {
    const response = await githubRequest(env, "/issues", {
      title: sanitize(payload.title).slice(0, MAX_TITLE_CHARS),
      body: sanitize(payload.body).slice(0, MAX_BODY_CHARS),
    });
    if (!response.ok) {
      console.error("GitHub issue creation failed", response.status);
      return jsonResponse({ error: "github_rejected_report" }, 502);
    }
    const issue = await response.json();
    if (!Number.isInteger(issue.number)) {
      return jsonResponse({ error: "github_invalid_response" }, 502);
    }
    issueNumber = issue.number;
    if (env.REPORTS) {
      await env.REPORTS.put(
        reportKey,
        JSON.stringify({ issue_number: issueNumber }),
        { expirationTtl: DEDUPE_SECONDS },
      );
    }
  }
  for (let index = 0; index < payload.comments.length; index += 1) {
    const part = index + 2;
    const partKey = `comment:${payload.fingerprint}:${part}`;
    if (env.REPORTS && await env.REPORTS.get(partKey)) {
      continue;
    }
    const response = await githubRequest(
      env,
      `/issues/${issueNumber}/comments`,
      { body: sanitize(payload.comments[index]).slice(0, MAX_COMMENT_CHARS) },
    );
    if (!response.ok) {
      console.error("GitHub issue comment failed", response.status);
      return jsonResponse({ error: "github_rejected_comment" }, 502);
    }
    if (env.REPORTS) {
      await env.REPORTS.put(partKey, "1", { expirationTtl: DEDUPE_SECONDS });
    }
  }
  return jsonResponse({ accepted: true }, 201);
}

async function handleReport(request, env) {
  if (!env.GITHUB_TOKEN || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(env.GITHUB_REPO || "")) {
    return jsonResponse({ error: "relay_not_configured" }, 503);
  }
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return jsonResponse({ error: "unsupported_media_type" }, 415);
  }
  if (await enforceRateLimit(request, env)) {
    return jsonResponse({ error: "rate_limited" }, 429);
  }
  const contentLength = Number(request.headers.get("content-length") || 0);
  if (contentLength > MAX_REQUEST_BYTES) {
    return jsonResponse({ error: "payload_too_large" }, 413);
  }
  const rawBody = await request.arrayBuffer();
  if (rawBody.byteLength > MAX_REQUEST_BYTES) {
    return jsonResponse({ error: "payload_too_large" }, 413);
  }
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(rawBody));
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }
  if (!validPayload(payload)) {
    return jsonResponse({ error: "invalid_report" }, 400);
  }
  return createIssue(payload, env);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse({ ok: true }, 200);
    }
    if (request.method !== "POST" || url.pathname !== "/report") {
      return jsonResponse({ error: "not_found" }, 404);
    }
    try {
      return await handleReport(request, env);
    } catch (error) {
      console.error("Report relay failed", error && error.name ? error.name : "Error");
      return jsonResponse({ error: "relay_error" }, 500);
    }
  },
};
