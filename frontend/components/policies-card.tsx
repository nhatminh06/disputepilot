import type { Policy } from '@/lib/contracts';
import { readable } from '@/lib/display';

export default function PoliciesCard({ policies, investigated }: { policies: Policy[]; investigated: boolean }) {
  return <section className="card" id="policies" aria-labelledby="policies-title">
    <div className="card-heading"><h2 id="policies-title">Policy references</h2><span className="small muted">{policies.length} retrieved</span></div>
    {policies.length ? <div className="policy-grid">{policies.map(policy => {
      const ref = `${policy.policy_id}#${policy.section_id}`;
      return <article className="policy" key={ref} id={`policy-${ref.replace('#', '-')}`}>
        <div className="policy-heading"><span>{readable(policy.policy_id)}</span><span className="demo-label">Synthetic demo policy</span></div>
        <h3>{readable(policy.section_id)}</h3><blockquote>{policy.excerpt}</blockquote>
        <div className="policy-source"><code>{ref}</code><span>{policy.source_path}</span></div>
      </article>;
    })}</div> : <div className="policy-empty"><h3>{investigated ? 'No relevant policies retrieved' : 'No policy sections retrieved yet'}</h3><p>{investigated ? 'The investigation returned no relevant policy sections.' : 'An investigation retrieves relevant sections. Demo policies are not evidence of shipment or delivery.'}</p></div>}
  </section>;
}
