const http = require('node:http');
const https = require('node:https');

function blocked() {
  throw new Error('Only the approved DashScope generation endpoint is allowed');
}

const underlyingFetch = globalThis.fetch;
globalThis.fetch = (input, options) => {
  const url = new URL(typeof input === 'string' ? input : input.url);
  if (url.origin !== 'https://dashscope.aliyuncs.com' ||
      url.pathname !== '/compatible-mode/v1/chat/completions') {
    return Promise.reject(new Error('Outbound generation host/path is not approved'));
  }
  return underlyingFetch(input, options);
};

// The one-shot provider uses fetch. Other HTTP clients remain disabled.
http.request = blocked;
http.get = blocked;
https.request = blocked;
https.get = blocked;
