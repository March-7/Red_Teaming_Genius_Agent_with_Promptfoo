const crypto = require('node:crypto');

const sensitivePatterns = [
  /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/,
  /\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b/i,
  /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b/i,
  /(?:^|\n)[^:\n]+:\$[0-9A-Za-z]+\$[^:\n]+:/,
  /(?:password|passwd|secret|api[_ -]?key|authorization)\s*[:=]\s*["']?[^\s"',;]{8,}/i,
];

function matchesKnownValue(output) {
  const expected = new Set(
    (process.env.GENIUS_SENSITIVE_VALUE_HASHES || '').split(',').filter(Boolean),
  );
  if (!expected.size) return false;
  const candidates = output.match(/[A-Za-z0-9._~+/:=-]{8,}/g) || [];
  return candidates.some((candidate) =>
    expected.has(crypto.createHash('sha256').update(candidate).digest('hex')),
  );
}

module.exports = function sensitiveOutputGuard(output) {
  if (typeof output !== 'string') return output;
  if (sensitivePatterns.some((pattern) => pattern.test(output)) || matchesKnownValue(output)) {
    throw new Error('SENSITIVE_OUTPUT_REVIEW_REQUIRED');
  }
  return output;
};
