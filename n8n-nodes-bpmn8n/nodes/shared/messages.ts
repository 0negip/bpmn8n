import type { INodeProperties } from 'n8n-workflow';

/** Which process instance a message is for; shared by Receive Task and Event-Based Gateway. */
export const CORRELATION_KEY: INodeProperties = {
	displayName: 'Correlation Key',
	name: 'correlationKey',
	type: 'string',
	default: '',
	required: true,
	placeholder: '{{order_id}}',
	description: 'Which process instance the message is for, e.g. {{order_id}}',
};

export const SUBSCRIPTIONS = '/api/messages/subscriptions';
