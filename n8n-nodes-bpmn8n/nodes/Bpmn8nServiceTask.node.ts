import { TaskNode } from './shared/TaskNode';

export class Bpmn8nServiceTask extends TaskNode {
	constructor() {
		super('serviceTask', 'BPMN Service Task: calls an automated service exposed by bpmn8n');
	}
}
