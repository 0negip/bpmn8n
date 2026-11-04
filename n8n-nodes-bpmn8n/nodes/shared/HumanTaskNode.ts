import type { IDataObject, INodeProperties } from 'n8n-workflow';
import { VARIABLES_HINT } from './input';
import { WaitingNode } from './WaitingNode';

declare const process: { env: Record<string, string | undefined> };

/** Where people open bpmn8n's pages (not the Docker-internal URL of the credential). */
const PAGES = (process.env.BPMN8N_PUBLIC_URL ?? 'http://localhost:8000').replace(/\/$/, '');


const PROPERTIES: INodeProperties[] = [
	{ displayName: 'Title', name: 'title', type: 'string', default: '', required: true,
		placeholder: 'Approve {{amount}} EUR for {{employee}}' },
	{
		displayName: 'Lane',
		name: 'lane',
		type: 'string',
		default: '',
		placeholder: 'managers',
		description: 'Role (Django group) whose members can complete it; empty = anyone',
	},
	{ displayName: 'Description', name: 'description', type: 'string', typeOptions: { rows: 2 }, default: '' },
	{
		displayName: 'Form Fields',
		name: 'form',
		type: 'fixedCollection',
		typeOptions: { multipleValues: true, sortable: true },
		default: {},
		placeholder: 'Add Field',
		options: [
			{
				displayName: 'Field',
				name: 'fields',
				values: [
					{ displayName: 'Name', name: 'name', type: 'string', default: '', required: true },
					{ displayName: 'Label', name: 'label', type: 'string', default: '' },
					{
						displayName: 'Type',
						name: 'type',
						type: 'options',
						default: 'string',
						options: [
							{ name: 'Text', value: 'string' },
							{ name: 'Number', value: 'number' },
							{ name: 'Yes/No', value: 'boolean' },
						],
					},
				],
			},
		],
	},
	{
		displayName: 'Context',
		name: 'context',
		type: 'json',
		default: '{}',
		description: 'Data shown to the person, e.g. {"amount": "{{amount}}"}; empty: all the process variables',
	},
	{ displayName: VARIABLES_HINT, name: 'variablesNotice', type: 'notice', default: '' },
];

/** BPMN User Task / Manual Task: a work item in the bpmn8n inbox for a lane (Django group), one per
 * item; the submitted forms are this node's output. Opened, the node links to the pages where people
 * work its tasks: while the editor follows a run, n8n's waiting message links to that run's task;
 * always, a hint links to the inbox (n8n 2.42 hides a waiting node's run when an execution is reopened
 * from the executions list, its own Wait node too). */
export abstract class HumanTaskNode extends WaitingNode {
	protected constructor(kind: 'userTask' | 'manualTask', summary: string) {
		super({
			bpmnType: kind,
			summary,
			subtitle: '={{$parameter["lane"]}}',
			properties: PROPERTIES,
			multiInstance: true,
			waitingNodeTooltip:
				`=This step waits for a person. <a href="${PAGES}/inbox/?workflow={{ $workflow.id }}` +
				`&execution={{ $execution.id }}" target="_blank">Open the task page</a>`,
			hints: [{
				message: `People work these tasks in the inbox (execution number shown): <a href="${PAGES}/inbox/" target="_blank">open the inbox</a>`,
				type: 'info',
				location: 'outputPane',
				whenToDisplay: 'always',
			}],
			register: (ctx, client, resumeUrl, _until, items) => {
				const context = ctx.getNodeParameter('context', 0) as string | IDataObject;
				return client.post('/api/usertasks', {
					kind,
					title: ctx.getNodeParameter('title', 0) as string,
					lane: ctx.getNodeParameter('lane', 0) as string,
					description: ctx.getNodeParameter('description', 0) as string,
					form: ((ctx.getNodeParameter('form', 0) as { fields?: IDataObject[] }).fields ?? []) as IDataObject[],
					context: typeof context === 'string' ? JSON.parse(context || '{}') : context ?? {},
					resume_url: resumeUrl,
					items,
				});
			},
		});
	}
}
