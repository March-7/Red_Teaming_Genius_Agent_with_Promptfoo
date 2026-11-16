const http = require('node:http');
const https = require('node:https');
const net = require('node:net');

function blocked() {
  throw new Error('Network is disabled for offline Promptfoo contract QA');
}

globalThis.fetch = blocked;
http.request = blocked;
http.get = blocked;
https.request = blocked;
https.get = blocked;
net.connect = blocked;
net.createConnection = blocked;
