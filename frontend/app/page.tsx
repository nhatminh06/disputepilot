import { redirect } from 'next/navigation';
import { ShieldCheck } from 'lucide-react';
import { DEMO_ID, publicDemoEnabled } from '@/lib/public-demo';

export default async function Home({ searchParams }: {
  searchParams: Promise<{ dispute_id?: string | string[] }>;
}) {
  const publicDemo = publicDemoEnabled();
  const { dispute_id: id } = await searchParams;
  const disputeId = typeof id === 'string' ? id.trim() : '';
  if (publicDemo && disputeId === DEMO_ID) {
    redirect(`/disputes/${DEMO_ID}`);
  }
  if (!publicDemo && /^[A-Z0-9-]{1,255}$/.test(disputeId)) {
    redirect(`/disputes/${encodeURIComponent(disputeId)}`);
  }
  return <main className="entry-page">
    <section className="card entry-card" aria-labelledby="entry-title">
      <div className="heading-with-icon"><ShieldCheck size={24} /><h1 id="entry-title">DisputePilot</h1></div>
      <p>{publicDemo
        ? 'Explore a sample dispute investigation, including its evidence, recommendation, and audit history.'
        : 'Open a PayPal Sandbox dispute to inspect its evidence, saved investigations, and audit history.'}</p>
      {publicDemo && <aside className="entry-demo-notice" aria-label="Public demo availability">
        Public demo supports sample case <code>{DEMO_ID}</code> only. Live PayPal disputes are not available.
      </aside>}
      <form method="get" action="/">
        <label htmlFor="dispute-id">{publicDemo ? 'Enter a dispute ID' : 'PayPal dispute ID'}</label>
        <input id="dispute-id" name="dispute_id" required maxLength={255} pattern={publicDemo ? undefined : '[A-Z0-9\-]+'} placeholder={publicDemo ? DEMO_ID : 'Enter the dispute ID'} defaultValue={disputeId} autoComplete="off" aria-describedby="entry-help" />
        <p id="entry-help">{publicDemo ? `Try the sample case ${DEMO_ID}.` : 'Use the case identifier returned by the PayPal Disputes API.'}</p>
        {id !== undefined && <p role="alert">{publicDemo
          ? `Only the sample case ${DEMO_ID} is available in the public demo.`
          : 'Enter a valid dispute ID using uppercase letters, numbers, and hyphens.'}</p>}
        <button className="button primary" type="submit">Open dispute</button>
      </form>
      {publicDemo
        ? <a className="entry-sample-link" href={`/disputes/${DEMO_ID}`}>Explore sample dispute</a>
        : <p className="small muted">Local workspace only. Opening a case does not start an investigation or authorize a PayPal action.</p>}
    </section>
  </main>;
}
