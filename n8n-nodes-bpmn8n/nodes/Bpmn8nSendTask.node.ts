import { TaskNode } from './shared/TaskNode';

export class Bpmn8nSendTask extends TaskNode {
	constructor() {
		super('sendTask', 'BPMN Send Task: sends a message through bpmn8n');
	}
}
