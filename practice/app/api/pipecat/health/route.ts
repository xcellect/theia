import 'server-only';
import { proxyPipecat } from '@/lib/pipecat-proxy.mjs';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export async function GET(request: Request) { return proxyPipecat(request, 'health'); }
