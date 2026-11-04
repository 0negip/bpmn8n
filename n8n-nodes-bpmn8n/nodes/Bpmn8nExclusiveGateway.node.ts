import { GatewayNode } from './shared/GatewayNode';

export class Bpmn8nExclusiveGateway extends GatewayNode {
	constructor() {
		super('exclusive', 'BPMN Exclusive Gateway: one branch, chosen by Laya (text) or by data conditions', 0);
	}
}
