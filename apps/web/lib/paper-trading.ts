import { z } from 'zod';

const numericField = (field: string) =>
  z.preprocess((value) => {
    if (value === '' || value == null) return value;
    return Number(value);
  }, z.number({ invalid_type_error: `${field} must be numeric.` }).positive(`${field} must be greater than zero.`));

const optionalNumericField = (field: string) =>
  z.preprocess((value) => {
    if (value === '') return null;
    if (value == null) return value;
    return Number(value);
  }, z.number({ invalid_type_error: `${field} must be numeric.` }).positive(`${field} must be greater than zero.`).nullable().optional());

const optionalIntegerField = (field: string) =>
  z.preprocess((value) => {
    if (value === '') return null;
    if (value == null) return value;
    return Number(value);
  }, z.number({ invalid_type_error: `${field} must be numeric.` }).int(`${field} must be an integer.`).positive(`${field} must be greater than zero.`).nullable().optional());

const lowercaseString = (value: unknown) =>
  typeof value === 'string' ? value.toLowerCase() : value;

const orderPreviewShape = {
  ticker: z.string().trim().min(1, 'ticker is required.').transform((value) => value.toUpperCase()),
  side: z.preprocess(lowercaseString, z.enum(['buy', 'sell'])),
  qty: numericField('qty'),
  order_type: z.preprocess(lowercaseString, z.enum(['market', 'limit'])).default('market'),
  limit_price: optionalNumericField('limit_price'),
  preview_audit_id: optionalIntegerField('preview_audit_id'),
  idempotency_key: z.string().trim().min(8).max(128).nullable().optional(),
  mode: z.literal('dry_run').nullable().optional(),
  entry_price: optionalNumericField('entry_price'),
  stop_price: optionalNumericField('stop_price'),
  target_price: optionalNumericField('target_price'),
  recommended_action_snapshot: z.string().trim().nullable().optional(),
};

export const orderPreviewRequestSchema = z
  .object(orderPreviewShape)
  .superRefine((payload, context) => {
    if (payload.order_type === 'limit' && payload.limit_price == null) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['limit_price'],
        message: 'limit_price is required for limit orders.',
      });
    }
  });

export const orderPlaceRequestSchema = z
  .object({
    ...orderPreviewShape,
    dry_run: z.boolean().optional(),
  })
  .superRefine((payload, context) => {
    if (payload.mode !== 'dry_run' && payload.dry_run !== true) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['mode'],
        message: 'mode must be "dry_run".',
      });
    }
    if (payload.dry_run === false) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['dry_run'],
        message: 'dry_run cannot be false.',
      });
    }
  });

export function parseOrderPayload(payload: unknown, place = false) {
  const parsed = place
    ? orderPlaceRequestSchema.safeParse(payload)
    : orderPreviewRequestSchema.safeParse(payload);
  if (!parsed.success) {
    return {
      ok: false as const,
      detail: parsed.error.issues.map((issue) => issue.message).join(' '),
    };
  }
  return { ok: true as const, payload: parsed.data };
}
