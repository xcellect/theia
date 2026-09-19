import 'server-only';
import { proxyResearch } from '@/lib/research-proxy.mjs';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: Request, context: Context) {
  const { path } = await context.params;
  return proxyResearch(request, path);
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
