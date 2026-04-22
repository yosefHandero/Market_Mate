import { z } from 'zod';

const journalDecisionSchema = z.enum(['watching', 'took', 'skipped']);
const positiveNullableNumber = z.number().positive().nullable();
const finiteNullableNumber = z.number().finite().nullable();

function trimmedNullableString(maxLength: number) {
  return z
    .string()
    .trim()
    .max(maxLength)
    .transform((value) => (value.length ? value : null))
    .nullable();
}

export const journalEntryCreateSchema = z
  .object({
    ticker: z
      .string()
      .trim()
      .min(1, 'Ticker is required.')
      .max(16, 'Ticker must be 16 characters or fewer.')
      .transform((value) => value.toUpperCase()),
    run_id: trimmedNullableString(120),
    decision: journalDecisionSchema,
    entry_price: positiveNullableNumber,
    exit_price: positiveNullableNumber,
    pnl_pct: finiteNullableNumber,
    notes: z.string().trim().max(2000, 'Notes must be 2000 characters or fewer.'),
    signal_label: trimmedNullableString(80),
    score: finiteNullableNumber,
    news_source: trimmedNullableString(80),
    override_reason: trimmedNullableString(200).optional().default(null),
    action_state: z.enum(['watching', 'reviewed', 'took', 'skipped']).nullable().optional(),
  })
  .superRefine((value, ctx) => {
    if (value.exit_price != null && value.entry_price == null) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Exit price requires an entry price.',
        path: ['exit_price'],
      });
    }
  });

export const journalEntryUpdateSchema = z.object({
  decision: journalDecisionSchema.optional(),
  entry_price: positiveNullableNumber.optional(),
  exit_price: positiveNullableNumber.optional(),
  pnl_pct: finiteNullableNumber.optional(),
  notes: z
    .string()
    .trim()
    .max(2000, 'Notes must be 2000 characters or fewer.')
    .nullable()
    .optional(),
  override_reason: trimmedNullableString(200).optional(),
  action_state: z.enum(['watching', 'reviewed', 'took', 'skipped']).nullable().optional(),
});

export function formatZodError(error: z.ZodError) {
  return error.issues.map((issue) => issue.message).join(' ');
}
