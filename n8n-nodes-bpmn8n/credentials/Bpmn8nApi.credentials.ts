import type { IAuthenticateGeneric, ICredentialTestRequest, ICredentialType, INodeProperties } from 'n8n-workflow';

/** Where the BPMN nodes reach bpmn8n (Django), and its API token (BPMN8N_API_TOKEN). */
export class Bpmn8nApi implements ICredentialType {
	name = 'bpmn8nApi';
	displayName = 'bpmn8n API';
	properties: INodeProperties[] = [
		{ displayName: 'Base URL', name: 'baseUrl', type: 'string', default: 'http://web:8000' },
		{ displayName: 'API Token', name: 'apiToken', type: 'string', typeOptions: { password: true }, default: '' },
	];
	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: { headers: { Authorization: '=Bearer {{$credentials.apiToken}}' } },
	};
	test: ICredentialTestRequest = {
		request: { baseURL: '={{$credentials.baseUrl}}', url: '/api/openapi.json' },
	};
}
