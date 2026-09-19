import 'server-only';
import { createHumeToken } from '@/lib/hume-token.mjs';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function POST(request: Request) { return createHumeToken(request); }
