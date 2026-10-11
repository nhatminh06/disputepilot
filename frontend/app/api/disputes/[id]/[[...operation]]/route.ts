import { proxy } from '@/lib/backend';

type Context = { params: Promise<{ id: string; operation?: string[] }> };
export async function GET(request: Request, context: Context) {
  const { id, operation } = await context.params;
  return proxy(request, id, operation);
}
export async function POST(request: Request, context: Context) {
  const { id, operation } = await context.params;
  return proxy(request, id, operation);
}
