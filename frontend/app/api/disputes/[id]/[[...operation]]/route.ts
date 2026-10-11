import { demoResponse, publicDemoEnabled } from '@/lib/public-demo';

type Context = { params: Promise<{ id: string; operation?: string[] }> };
export async function GET(request: Request, context: Context) {
  const { id, operation } = await context.params;
  if (publicDemoEnabled()) return demoResponse(request, id, operation);
  const { proxy } = await import('@/lib/backend');
  return proxy(request, id, operation);
}
export async function POST(request: Request, context: Context) {
  const { id, operation } = await context.params;
  if (publicDemoEnabled()) return demoResponse(request, id, operation);
  const { proxy } = await import('@/lib/backend');
  return proxy(request, id, operation);
}
