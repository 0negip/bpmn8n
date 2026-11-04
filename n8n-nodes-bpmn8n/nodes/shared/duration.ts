import type { INodeProperties } from 'n8n-workflow';

export const UNIT_MS = { seconds: 1e3, minutes: 6e4, hours: 3.6e6, days: 8.64e7, weeks: 6.048e8 } as const;

type Parameters = { getNodeParameter(name: string, itemIndex: number): unknown };

/** "Wait for a time span / until a date" fields, labelled `label` (e.g. "Wait", "Timeout"). */
export function durationProperties(label: string): INodeProperties[] {
	return [
		{
			displayName: label,
			name: 'mode',
			type: 'options',
			default: 'for',
			options: [
				{ name: 'For a Time Span', value: 'for' },
				{ name: 'Until a Date', value: 'until' },
			],
		},
		{ displayName: 'Amount', name: 'amount', type: 'number', typeOptions: { minValue: 0 }, default: 1,
			displayOptions: { show: { mode: ['for'] } } },
		{
			displayName: 'Unit',
			name: 'unit',
			type: 'options',
			default: 'hours',
			displayOptions: { show: { mode: ['for'] } },
			options: Object.keys(UNIT_MS).map((u) => ({ name: u[0].toUpperCase() + u.slice(1), value: u })),
		},
		{ displayName: 'Until', name: 'until', type: 'dateTime', default: '', required: true,
			displayOptions: { show: { mode: ['until'] } } },
	];
}

export const DURATION_SUBTITLE =
	'={{ $parameter.mode === "until" ? "until " + $parameter.until : $parameter.amount + " " + $parameter.unit }}';

/** The moment the configured duration ends. */
export function deadline(ctx: Parameters, i = 0): Date {
	if (ctx.getNodeParameter('mode', i) === 'until') return new Date(ctx.getNodeParameter('until', i) as string);
	const unit = ctx.getNodeParameter('unit', i) as keyof typeof UNIT_MS;
	return new Date(Date.now() + (ctx.getNodeParameter('amount', i) as number) * UNIT_MS[unit]);
}
