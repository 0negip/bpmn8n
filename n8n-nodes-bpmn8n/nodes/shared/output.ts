import type { IDataObject, INodeProperties } from 'n8n-workflow';

export type OutputMode = 'result' | 'merge' | 'key';

export const OUTPUT_PROPERTIES: INodeProperties[] = [
	{
		displayName: 'Output',
		name: 'output',
		type: 'options',
		default: 'result',
		options: [
			{ name: 'Task Result Only', value: 'result', description: 'The item becomes what the task returns' },
			{ name: 'Input + Task Result', value: 'merge', description: 'The result fields are added to the incoming item' },
			{ name: 'Input + Result Under a Key', value: 'key', description: 'The incoming item, plus the result in one field' },
		],
	},
	{
		displayName: 'Result Key',
		name: 'outputKey',
		type: 'string',
		default: 'result',
		displayOptions: { show: { output: ['key'] } },
	},
];

/** The item a task passes on, per the node's "Output" setting. */
export function shapeOutput(mode: OutputMode, input: IDataObject, result: IDataObject, key = 'result'): IDataObject {
	if (mode === 'merge') return { ...input, ...result };
	if (mode === 'key') return { ...input, [key]: result };
	return result;
}
