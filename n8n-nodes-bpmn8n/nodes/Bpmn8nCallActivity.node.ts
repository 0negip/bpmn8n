import type { IExecuteFunctions, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { bpmnDescription } from './shared/Bpmn8nClient';

/** BPMN Call Activity: runs another workflow (a reusable sub-process, started by its "When
 * Executed by Another Workflow" trigger) with these items and continues with its result.
 * ponytail: the sub-process should not wait (user/receive tasks): it runs to the end in one go. */
export class Bpmn8nCallActivity implements INodeType {
	description: INodeTypeDescription = bpmnDescription(
		'callActivity',
		'BPMN Call Activity: runs a reusable sub-process (another workflow) and continues with its result',
		{
			subtitle: '={{ $parameter.workflowId.cachedResultName || $parameter.workflowId.value }}',
			credentials: [],
			properties: [{ displayName: 'Sub-Process', name: 'workflowId', type: 'workflowSelector', default: '', required: true }],
		},
	);

	async execute(this: IExecuteFunctions) {
		const { value: id } = this.getNodeParameter('workflowId', 0, {}) as { value: string }; // as n8n's Execute Workflow
		const parent = this.getWorkflowDataProxy(0);
		// like n8n's Execute Workflow: links parent and child executions; a manual run uses the draft
		const result = await this.executeWorkflow({ id }, this.getInputData(), undefined, {
			parentExecution: { executionId: parent.$execution.id, workflowId: parent.$workflow.id as string, shouldResume: true },
			executionMode: this.getMode(),
		});
		return result.data.map((items) => items ?? []);
	}
}
