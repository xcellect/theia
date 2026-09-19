// Incremental SSE decoding: transport chunks need not end on a UTF-8 or event boundary.
export async function* readSSE(body, { signal, maxEventBytes = 65_536 } = {}) {
  if (!body?.getReader) throw new Error('Missing response stream.');
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let lines = [];
  let eventSize = 0;
  const lineEvent = (line) => {
    if (line === '') {
      const data = lines.length ? lines.join('\n') : null;
      lines = [];
      eventSize = 0;
      return data;
    }
    eventSize += line.length;
    if (eventSize > maxEventBytes) throw new Error('SSE event exceeds size limit.');
    if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''));
    return null;
  };
  try {
    while (true) {
      const { value, done } = await withAbort(reader.read(), signal);
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let match;
      while ((match = /[\r\n]/.exec(buffer))) {
        const index = match.index;
        if (!done && buffer[index] === '\r' && index === buffer.length - 1) break;
        const width = buffer[index] === '\r' && buffer[index + 1] === '\n' ? 2 : 1;
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + width);
        const event = lineEvent(line);
        if (event !== null) yield event;
      }
      if (buffer.length + eventSize > maxEventBytes) throw new Error('SSE event exceeds size limit.');
      if (done) {
        // The SSE specification dispatches events only after a blank line. A truncated
        // final event is intentionally not treated as a successful completion.
        return;
      }
    }
  } finally {
    // Cancel on early consumer return as well as normal EOF, without waiting forever
    // on a broken underlying transport's cancel implementation.
    reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function withAbort(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) {
    Promise.resolve(promise).catch(() => {});
    return Promise.reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
  }
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      cleanup();
      reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
    };
    const cleanup = () => signal.removeEventListener('abort', onAbort);
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then((value) => { cleanup(); resolve(value); }, (error) => { cleanup(); reject(error); });
  });
}
