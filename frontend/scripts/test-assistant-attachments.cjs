// Run with node --test scripts/test-assistant-attachments.cjs; no browser or network required.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function client() {
  let token = 'first-account';
  const requests = [];
  const context = {
    exports: {}, window: {}, AbortController, TextDecoder, Uint8Array, btoa,
    sessionStorage: { getItem: () => token },
    require: (name) => name.endsWith('/api') ? { API_URL: 'https://example.test', TOKEN_KEY: 'token' } : {},
    fetch: async (url, options) => { requests.push(options); return new Response(''); },
  };
  const source = fs.readFileSync(path.join(__dirname, '../src/lib/assistant-api.ts'), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
  return { api: context.exports, requests, switchAccount: () => { token = 'second-account'; } };
}

test('account switching during file encoding never posts the old chat with the new token', async () => {
  const { api, requests, switchAccount } = client();
  let finish;
  const file = { name: 'test.jpg', size: 3, arrayBuffer: () => new Promise(resolve => { finish = resolve; }) };
  const pending = api.streamChat('Read this', [], () => {}, new AbortController().signal, false, null, [file]);
  switchAccount();
  finish(new Uint8Array([255, 216, 255]).buffer);
  await assert.rejects(pending);
  assert.equal(requests.length, 0);
});

test('unchanged account sends the attachment with its original token', async () => {
  const { api, requests } = client();
  const file = { name: 'test.jpg', size: 3, arrayBuffer: async () => new Uint8Array([255, 216, 255]).buffer };
  await api.streamChat('Read this', [], () => {}, new AbortController().signal, false, null, [file]);
  assert.equal(requests[0].headers.Authorization, 'Bearer first-account');
  assert.equal(JSON.parse(requests[0].body).attachments[0].data, '/9j/');
});
