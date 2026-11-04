// n8n reads a node's search data (codex) from <Node>.node.json next to it: written from each
// node's description.codex (bpmnDescription), so the two never drift apart.
const fs = require('node:fs');
const path = require('node:path');

const dist = path.join(__dirname, '..', 'dist', 'nodes');
for (const file of fs.readdirSync(dist).filter((f) => f.endsWith('.node.js'))) {
	const exported = require(path.join(dist, file));
	const { codex } = new (Object.values(exported)[0])().description;
	fs.writeFileSync(path.join(dist, file.replace(/\.js$/, '.json')), JSON.stringify({ ...codex, resources: {} }, null, 2));
}
