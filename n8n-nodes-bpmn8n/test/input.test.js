const { test } = require('node:test');
const assert = require('node:assert');
const { inputRequest, unpackReply } = require('../dist/nodes/shared/input');

test('fields go to /run; empty ones are left to binding by name; the item travels along', () => {
	assert.deepStrictEqual(inputRequest('fields', '/api/tasks/t', { a: 1, b: '', c: null, d: '{{book}}' }, { x: 1 }), {
		path: '/api/tasks/t/run',
		body: { fields: { a: 1, d: '{{book}}' }, item: { x: 1 } },
	});
});

test('text input adds the text and the extraction settings', () => {
	assert.deepStrictEqual(inputRequest('text', '/api/tasks/t', { a: 1 }, {}, '{{message}}', 0.7, true), {
		path: '/api/tasks/t/run',
		body: { fields: { a: 1 }, item: {}, text: '{{message}}', min_confidence: 0.7, verify: true },
	});
});

test('the reply is unpacked into result and extraction', () => {
	const reply = { result: { ok: true }, extracted: { a: { value: 1, confidence: 0.9 } } };
	assert.deepStrictEqual(unpackReply(reply), { result: { ok: true }, extraction: reply.extracted });
});
