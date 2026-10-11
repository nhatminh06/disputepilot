import { notFound } from 'next/navigation';
import DisputePage from '@/components/dispute-page';

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[A-Z0-9-]{1,255}$/.test(id)) notFound();
  return <DisputePage key={id} id={id} />;
}
