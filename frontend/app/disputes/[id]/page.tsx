import { notFound } from 'next/navigation';
import DisputePage from '@/components/dispute-page';
import { DEMO_ID, publicDemoEnabled } from '@/lib/public-demo';

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[A-Z0-9-]{1,255}$/.test(id)) notFound();
  const publicDemo = publicDemoEnabled();
  if (publicDemo && id !== DEMO_ID) notFound();
  return <DisputePage key={id} id={id} publicDemo={publicDemo} />;
}
