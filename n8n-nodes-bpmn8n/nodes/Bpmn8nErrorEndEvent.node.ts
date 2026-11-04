import type { IExecuteFunctions, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { Bpmn8nClient, bpmnDescription } from './shared/Bpmn8nClient';

/** BPMN Error End Event: ends the process with a named business error. The execution fails with
 * "<code>: <message>", so n8n's Error Trigger workflow (BPMN's error event sub-process) handles
 * it; the event also enters bpmn8n's process-mining log. For a boundary error event on any node,
 * use n8n's Settings → On Error → "Continue (using error output)". */
export class Bpmn8nErrorEndEvent implements INodeType {
	description: INodeTypeDescription = bpmnDescription(
		'errorEndEvent',
		'BPMN Error End Event: ends the process with a named error (e.g. PARTNER_FAILURE)',
		{
			subtitle: '={{$parameter["code"]}}',
			outputs: [],
			properties: [
				{ displayName: 'Error Code', name: 'code', type: 'string', default: '', required: true,
					placeholder: 'PARTNER_FAILURE' },
				{ displayName: 'Message', name: 'message', type: 'string', default: '',
					placeholder: 'No acknowledgment from {{partner}} within four days' },
			],
		},
	);

	async execute(this: IExecuteFunctions): Promise<never> {
		const { message } = await new Bpmn8nClient(this).post('/api/events', {
			status: 'error',
			message: this.getNodeParameter('message', 0) as string,
			item: this.getInputData()[0]?.json ?? {},
		});
		throw new Error(`${this.getNodeParameter('code', 0)}${message ? `: ${message}` : ''}`);
	}
}
