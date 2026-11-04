import { TaskNode } from './shared/TaskNode';

export class Bpmn8nBusinessRuleTask extends TaskNode {
	constructor() {
		super('businessRuleTask', 'BPMN Business Rule Task: evaluates a bpmn8n business rule');
	}
}
