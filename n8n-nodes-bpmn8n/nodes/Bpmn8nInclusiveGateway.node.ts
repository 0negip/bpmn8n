import { GatewayNode } from './shared/GatewayNode';

export class Bpmn8nInclusiveGateway extends GatewayNode {
	constructor() {
		super('inclusive', 'BPMN Inclusive Gateway: every branch whose Laya answer or data condition is true', 0.5);
	}
}
