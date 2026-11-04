import type { IExecuteFunctions, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { bpmnDescription } from './shared/Bpmn8nClient';
import { DURATION_SUBTITLE, deadline, durationProperties } from './shared/duration';

const IN_PROCESS_MS = 65_000; // like n8n's Wait node: short waits sleep, long ones park the execution

/** BPMN Timer Intermediate Event: the process waits for a time span or until a moment. */
export class Bpmn8nTimerEvent implements INodeType {
	description: INodeTypeDescription = bpmnDescription(
		'timerEvent',
		'BPMN Timer Event: waits for a time span or until a date (e.g. "2 weeks", a deadline)',
		{ subtitle: DURATION_SUBTITLE, credentials: [], properties: durationProperties('Wait') },
	);

	async execute(this: IExecuteFunctions) {
		const until = deadline(this);
		const ms = until.getTime() - Date.now();
		if (ms < IN_PROCESS_MS) {
			await new Promise((resolve) => setTimeout(resolve, Math.max(ms, 0)));
		} else {
			await this.putExecutionToWait(until);
		}
		return [this.getInputData()];
	}
}
