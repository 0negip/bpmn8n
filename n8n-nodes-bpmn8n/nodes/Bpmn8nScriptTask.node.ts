import { TaskNode } from './shared/TaskNode';

export class Bpmn8nScriptTask extends TaskNode {
	constructor() {
		super('scriptTask', 'BPMN Script Task: runs a script hosted by bpmn8n');
	}
}
