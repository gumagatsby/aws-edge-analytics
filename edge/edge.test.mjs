// Runs the CloudFront Functions locally under node:test. The `cloudfront` module
// is replaced with a stub that records logCustomData calls.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

function load(file, vars = {}) {
  let src = readFileSync(new URL(file, import.meta.url), 'utf8');
  for (const [k, v] of Object.entries(vars)) src = src.replaceAll('${' + k + '}', String(v));
  src = src.replace("import cf from 'cloudfront';", '');
  const logged = [];
  const cf = { logCustomData: (s) => logged.push(s) };
  const handler = new Function('cf', src + '\nreturn handler;')(cf);
  return { handler, logged };
}

function event({ uri = '/', cookie, qs = {}, ip = '203.0.113.7', ua = 'Mozilla/5.0' } = {}) {
  const querystring = Object.fromEntries(Object.entries(qs).map(([k, v]) => [k, { value: v }]));
  return {
    viewer: { ip },
    request: { method: 'GET', uri, querystring, headers: { 'user-agent': { value: ua } },
               cookies: cookie ? { ab: { value: cookie } } : {} },
    response: { statusCode: 200, headers: {}, cookies: {} },
  };
}

test('an existing cookie decides the homepage design', () => {
  const { handler, logged } = load('./viewer_request.js', { normalise: true });
  assert.equal(handler(event({ cookie: 'B' })).uri, '/variants/b/index.html');
  assert.equal(handler(event({ cookie: 'A' })).uri, '/index.html');
  assert.deepEqual(logged, ['ab=B', 'ab=A']);
});

test('a folder URL serves that folder\'s index page', () => {
  const { handler } = load('./viewer_request.js', { normalise: true });
  assert.equal(handler(event({ uri: '/insights/' })).uri, '/insights/index.html');
  assert.equal(handler(event({ uri: '/insights/data.json' })).uri, '/insights/data.json');
});

test('request and response functions assign a new visitor to the same group', () => {
  const req = load('./viewer_request.js', { normalise: true });
  const res = load('./viewer_response.js');
  for (let i = 0; i < 50; i++) {
    const e = event({ ip: `198.51.100.${i}`, ua: `agent-${i}` });
    const uri = req.handler(structuredClone(e)).uri;
    const cookie = res.handler(structuredClone(e)).cookies.ab.value;
    assert.equal(uri === '/variants/b/index.html' ? 'B' : 'A', cookie);
  }
  assert.ok(req.logged.every((l) => l.includes(';new=1')));
});

test('groups split roughly in half', () => {
  const { handler } = load('./viewer_request.js', { normalise: true });
  let b = 0;
  for (let i = 0; i < 2000; i++) {
    if (handler(event({ ip: `10.0.${i >> 8}.${i & 255}`, ua: 'Mozilla/5.0' })).uri.startsWith('/variants/b')) b++;
  }
  assert.ok(b > 900 && b < 1100, `B share ${b}/2000`);
});

test('tracking parameters are removed only when normalisation is on', () => {
  const qs = { utm_source: 'news', gclid: 'x', colour: 'red' };
  const on = load('./viewer_request.js', { normalise: true });
  assert.deepEqual(Object.keys(on.handler(event({ uri: '/products/3.html', qs })).querystring), ['colour']);
  assert.match(on.logged[0], /stripped=2/);
  const off = load('./viewer_request.js', { normalise: false });
  assert.equal(Object.keys(off.handler(event({ uri: '/products/3.html', qs })).querystring).length, 3);
});

test('other paths are not rewritten', () => {
  const { handler } = load('./viewer_request.js', { normalise: true });
  assert.equal(handler(event({ uri: '/api/checkout', cookie: 'B' })).uri, '/api/checkout');
});

test('the response function leaves a visitor with a valid cookie alone', () => {
  const { handler } = load('./viewer_response.js');
  assert.equal(handler(event({ cookie: 'A' })).cookies.ab, undefined);
  assert.ok(handler(event({ cookie: 'Z' })).cookies.ab);
});
