import { HumanTaskNode } from './shared/HumanTaskNode';

export class Bpmn8nManualTask extends HumanTaskNode {
	constructor() {
		super('manualTask', 'BPMN Manual Task: work done without IT (e.g. ship a parcel), confirmed in the inbox');
	}
}
