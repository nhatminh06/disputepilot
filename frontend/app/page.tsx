import { redirect } from 'next/navigation';
import { ShieldCheck } from 'lucide-react';

export default async function Home({ searchParams }: {
  searchParams: Promise<{ dispute_id?: string | string[] }>;
}) {
  const { dispute_id: id } = await searchParams;
  if (typeof id === 'string' && /^[A-Z0-9-]{1,255}$/.test(id.trim())) {
    redirect(`/disputes/${encodeURIComponent(id.trim())}`);
  }
  return <main className="entry-page">
    <section className="card entry-card" aria-labelledby="entry-title">
      <div className="heading-with-icon"><ShieldCheck size={24} /><h1 id="entry-title">DisputePilot</h1></div>
      <p>Open a PayPal Sandbox dispute to inspect its evidence, saved investigations, and audit history.</p>
      <form method="get" action="/">
        <label htmlFor="dispute-id">PayPal dispute ID</label>
        <input id="dispute-id" name="dispute_id" required maxLength={255} pattern="[A-Z0-9\-]+" placeholder="Enter the dispute ID" autoComplete="off" aria-describedby="entry-help" />
        <p id="entry-help">Use the case identifier returned by the PayPal Disputes API.</p>
        {id !== undefined && <p role="alert">Enter a valid dispute ID using uppercase letters, numbers, and hyphens.</p>}
        <button className="button primary" type="submit">Open dispute</button>
      </form>
      <p className="small muted">Local workspace only. Opening a case does not start an investigation or authorize a PayPal action.</p>
    </section>
  </main>;
}
