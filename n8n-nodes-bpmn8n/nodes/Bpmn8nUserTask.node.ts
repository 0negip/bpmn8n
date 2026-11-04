import { HumanTaskNode } from './shared/HumanTaskNode';

export class Bpmn8nUserTask extends HumanTaskNode {
	constructor() {
		super('userTask', 'BPMN User Task: a person completes a form in the bpmn8n inbox, then the process goes on');
	}
}
