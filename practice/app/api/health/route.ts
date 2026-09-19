import { readConfig } from '@/lib/config.mjs';
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export async function GET() {
  const configured = (route: string) => { try { readConfig(route); return true; } catch { return false; } };
  return Response.json({ status: 'ok', practice: true, configured: {
    evi: configured('evi'), sambanova: configured('sambanova'),
  } }, { headers: { 'Cache-Control': 'no-store' } });
}
