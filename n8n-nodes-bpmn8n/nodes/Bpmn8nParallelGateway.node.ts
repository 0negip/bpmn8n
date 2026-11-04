import type { IExecuteFunctions, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { bpmnDescription } from './shared/Bpmn8nClient';
import { branchOutputs, branchesProperty, readBranches } from './shared/branches';

/** BPMN Parallel Gateway (fork): every item continues on every branch at once. To join the
 * branches again use n8n's Merge node. */
export class Bpmn8nParallelGateway implements INodeType {
	description: INodeTypeDescription = bpmnDescription(
		'parallelGateway',
		'BPMN Parallel Gateway: all branches run; join them with a Merge node',
		{
			subtitle: '={{ "fork into " + (($parameter.branches || {}).values || []).length }}',
			outputs: branchOutputs(),
			credentials: [],
			properties: [branchesProperty()],
		},
	);

	async execute(this: IExecuteFunctions) {
		const items = this.getInputData().map((item, i) => ({ json: item.json, pairedItem: { item: i } }));
		return readBranches(this, 0).map(() => items);
	}
}
