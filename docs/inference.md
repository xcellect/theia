# Inference practice

This is generic tutorial code prepared on September 18, 2026. Event credentials,
the exact available model, quota, and rules for reusing practice code are still
unknown. The tool fixture changes only process-local memory. It is not an
integrated voice project or evidence of a real sponsor request.

## Run it

From `practice/`:

```bash
npm run smoke:fake
npm run smoke:fake -- --tools
node --test tests/inference.test.mjs
```

The fake provider uses no network, returns fixed `DEMO DATA` text, and exercises
the same HTTP-response parsing and SSE paths as the real provider. Its timing is
an artificial local delay and must not be used as a provider benchmark.

Once the account owner has established access and confirmed credit/budget, put
the key and exact model ID in the ignored `practice/.env.local`:

```dotenv
SAMBANOVA_API_KEY=
SAMBANOVA_MODEL=
SAMBANOVA_BASE_URL=https://api.sambanova.ai/v1
PROVIDER_TIMEOUT_MS=30000
```

The URL above is the public-cloud practice default. Use the assigned event base
URL when supplied; its API prefix may differ. The client appends
`/chat/completions`. No model is selected automatically. Model availability and
tool support must be verified for the actual account and endpoint.

```bash
npm run check:config -- sambanova
npm run smoke:sambanova
# Optional: two additional requests to verify function calling.
npm run smoke:sambanova -- --tools
```

Each ordinary smoke run sends exactly two requests: one non-streaming, then one
streaming. `--tools` adds a tool-selection request and a follow-up containing the
structured local result. There are no automatic retries. Ctrl+C cancels active
work. The script explicitly loads `.env.local`, then `.env`, while preserving
values already provided by the process environment.

## Implementation and measurements

`practice/lib/sambanova.mjs` is a small native-fetch client for the documented
OpenAI-compatible chat-completions HTTP format. It sends the SambaNova key in a
server-side Authorization header. HTTPS is required, redirects are disabled,
and endpoint URLs containing embedded credentials, query strings, or fragments
are rejected. No SDK or extra dependency is needed for this bounded smoke.

Streaming text is written as each content delta arrives. Empty, role-only,
comment, and usage chunks are ignored; split network chunks, split UTF-8, CRLF,
and multiline SSE data are handled. `[DONE]` is required, so truncated streams
cannot pass. The script reports latency to the first text delta containing a
non-whitespace character separately from total time through `[DONE]`. It also
reports non-streaming completion time. These are text-inference measurements,
not microphone-to-audio latency.

Timeouts cover connection setup and response-body reads. Caller cancellation and
early stream termination cancel the reader and abort the request. Responses and
individual SSE events have size limits. Fixed error messages distinguish
authentication, model access, quota, invalid requests, transport, timeout,
cancellation, empty output, and malformed response errors. Provider error bodies
are never printed. The CLI strips terminal controls and redacts configured
credential values, including values split across successive streaming chunks.
Only a credential-free endpoint and the configured model are printed.

The server-only interface is:

```js
import { createSambaNovaProvider, createFakeProvider } from './lib/sambanova.mjs';

const provider = createFakeProvider({ scenario: 'success', chunkDelayMs: 25 });
// For real inference: createSambaNovaProvider(readConfig('sambanova')).
const messages = [{ role: 'user', content: 'Hello' }];
const result = await provider.complete(messages, { signal });
// result: { text, message, totalMs, demo }
for await (const event of provider.stream(messages, { signal })) {
  // Text: { type: 'text', text, elapsedMs, demo }
  // Completion: { type: 'done', firstTextMs, totalMs, demo }
}
```

A UI route can consume this iterator on the server and forward text/status
events; it must keep the `demo` label visible and pass request cancellation
through. The fake provider supports `success`, `auth`, `model`, `quota`,
`transport`, and `timeout` scenarios. Never silently fall back from real
inference to fake output.

## Local action fixture

`createTaskBoard()` in `practice/lib/sandbox-tools.mjs` creates the single
`practice-task` in `todo`. The allowlisted `set_task_status` tool accepts only
`actionId`, `taskId`, and a status of `todo`, `in_progress`, or `done`. JSON,
argument shape, identifiers, and allowed status values are checked on the
server before mutation. Unknown tasks/tools and extra properties fail.

Reusing an action ID with the same arguments returns the stored result without
applying the change again. Reusing it with different arguments fails with
`ACTION_ID_CONFLICT`. A new action can restore `todo`. Returned objects cannot
mutate internal state. Each CLI run creates a fresh board; exiting discards it.

`runToolRoundTrip(provider)` requires exactly one call, executes it, returns a
structured result using its `tool_call_id`, and requires a nonempty final model
response. Fake success proves the harness only. Real tool support remains
unverified until that round trip passes with the assigned model and endpoint.

## Observed evidence

| Check on September 18, 2026 | Result |
| --- | --- |
| `node --test tests/inference.test.mjs` | PASS: 20 automated tests; synthetic provider responses, no external calls |
| `npm run smoke:fake -- --tools` | PASS: fixed text, incremental stream, local mutation, and follow-up; **DEMO DATA** |
| Fake first nonempty text / streaming total | 78.2 ms / 209.1 ms in one local run; artificial, not provider performance |
| `npm run smoke:sambanova` | BLOCKED: exits 1 with `Missing variables: SAMBANOVA_API_KEY, SAMBANOVA_MODEL` before any request |
| Actual non-streaming / streaming / tool response | NOT RUN: no credential, account model, quota, or real latency evidence |

The coordinator records overall checklist state in [readiness.md](readiness.md).
After a real run, preserve its sanitized endpoint, exact model, output, first
text time, and total time there. Do not mark C03–C05 or C07 complete from fake
results.

## Official references checked

- [SambaNova quickstart](https://docs.sambanova.ai/docs/en/get-started/quickstart): native SDK, compatible clients, and direct HTTP examples.
- [OpenAI compatibility](https://docs.sambanova.ai/docs/en/features/openai-compatibility): configured base URL/key and incremental content deltas.
- [Function calling](https://docs.sambanova.ai/docs/en/features/function-calling): tool schema, forced tool choice, and returning results in a second request.
- [API keys and URLs](https://docs.sambanova.ai/docs/en/get-started/api-keys-urls): public-cloud and deployment-specific connection details.
