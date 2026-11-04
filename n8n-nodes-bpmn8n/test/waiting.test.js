const { test } = require('node:test');
const assert = require('node:assert');
const { Bpmn8nUserTask } = require('../dist/nodes/Bpmn8nUserTask.node.js');
const { Bpmn8nReceiveTask } = require('../dist/nodes/Bpmn8nReceiveTask.node.js');
const { Bpmn8nEventBasedGateway } = require('../dist/nodes/Bpmn8nEventBasedGateway.node.js');

const webhook = (body, parameters = {}) => ({
	getBodyData: () => body,
	getNode: () => ({ name: 'Node' }),
	getNodeParameter: (name) => parameters[name],
});

test('a multi-instance resume brings one item per task, in order', async () => {
	const { workflowData } = await new Bpmn8nUserTask().webhook.call(webhook({ _items: [{ ok: true }, { ok: false }] }));
	assert.deepStrictEqual(workflowData, [[{ json: { ok: true } }, { json: { ok: false } }]]);
});

test('a human task links to its pages: the run\'s task while waiting, the inbox always', () => {
	const { waitingNodeTooltip, hints } = new Bpmn8nUserTask().description;
	assert.match(waitingNodeTooltip, /inbox\/\?workflow=\{\{ \$workflow\.id \}\}&execution=\{\{ \$execution\.id \}\}/);
	assert.deepStrictEqual([hints[0].whenToDisplay, hints[0].location], ['always', 'outputPane']);
	assert.match(hints[0].message, /href="http:\/\/localhost:8000\/inbox\/"/);
});

test('a message resume is one item', async () => {
	const { workflowData } = await new Bpmn8nReceiveTask().webhook.call(webhook({ amount: 9 }));
	assert.deepStrictEqual(workflowData, [[{ json: { amount: 9 } }]]);
});

test('several items cannot wait for one message', async () => {
	const ctx = { getInputData: () => [{ json: {} }, { json: {} }], getNode: () => ({ name: 'Receive' }) };
	await assert.rejects(new Bpmn8nReceiveTask().execute.call(ctx), /2 items arrived/);
});

test('an unknown message is an error, not a timeout', async () => {
	const branches = { branches: { values: [{ name: 'hold-book' }] } };
	const gateway = new Bpmn8nEventBasedGateway();
	const { workflowData } = await gateway.webhook.call(webhook({ _message: 'hold-book' }, branches));
	assert.strictEqual(workflowData[1].length, 1);
	await assert.rejects(gateway.webhook.call(webhook({ _message: 'spam' }, branches)), /no output for message "spam"/);
});

test("bpmn8n's explanation reaches the n8n error", async () => {
	const { Bpmn8nClient } = require('../dist/nodes/shared/Bpmn8nClient.js');
	const ctx = {
		getCredentials: async () => ({ baseUrl: 'http://web:8000' }),
		getNode: () => ({ name: 'Check Amount' }),
		helpers: { httpRequestWithAuthentication: async () => ({ statusCode: 422, body: { detail: "'{{amount}} < 1000': no" } }) },
	};
	await assert.rejects(new Bpmn8nClient(ctx).post('/api/gateways/conditions', {}), /422 '\{\{amount\}\} < 1000': no/);
});
