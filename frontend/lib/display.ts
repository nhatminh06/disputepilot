export const factLabels: Record<string, string> = {
  payment_completed: 'Payment completion', shipment_record_exists: 'Shipment record',
  delivery_confirmed: 'Delivery confirmation', shipping_address_matches: 'Shipping address match',
  merchant_policy_supports_contest: 'Merchant policy support', prior_refund_exists: 'Prior refund',
  item_description: 'Item description', condition_evidence: 'Item condition',
  authorization_evidence: 'Payment authorization',
};
export function readable(value: string | null | undefined): string {
  if (!value) return 'Not available';
  return value.replaceAll('_', ' ').replaceAll('-', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
}
export function factLabel(id: string): string { return factLabels[id] || readable(id); }
export function reasonLabel(reason: string | null): string {
  return ({ MERCHANDISE_OR_SERVICE_NOT_RECEIVED: 'Item not received',
    MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED: 'Item not as described',
    UNAUTHORISED: 'Unauthorized payment' } as Record<string, string>)[reason || ''] || readable(reason);
}
export function deadline(value: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return 'Not provided';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC',
  }).format(new Date(value)) + ' UTC';
}
