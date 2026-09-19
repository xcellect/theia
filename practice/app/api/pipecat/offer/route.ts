import 'server-only';
import { proxyPipecat } from '@/lib/pipecat-proxy.mjs';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export async function POST(request: Request) { return proxyPipecat(request, 'offer'); }
export async function PATCH(request: Request) { return proxyPipecat(request, 'offer'); }
