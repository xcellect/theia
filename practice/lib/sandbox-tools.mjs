export const taskTool = {
  type: 'function',
  function: {
    name: 'set_task_status',
    description: 'Set the status of the single local tutorial task. This changes only an in-memory practice board.',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        actionId: { type: 'string', description: 'Stable identifier for this user intent; preserve it when retrying.', minLength: 1, maxLength: 64 },
        taskId: { type: 'string', enum: ['practice-task'] },
        status: { type: 'string', enum: ['todo', 'in_progress', 'done'] },
      },
      required: ['actionId', 'taskId', 'status'],
    },
  },
};

const failure = (code, message) => ({ ok: false, error: { code, message } });

export function createTaskBoard() {
  const task = { id: 'practice-task', title: 'Try the local tutorial action', status: 'todo' };
  const actions = new Map();
  return {
    snapshot() { return [{ ...task }]; },
    execute(name, rawArguments) {
      if (name !== 'set_task_status') return failure('UNKNOWN_TOOL', 'Only set_task_status is allowed.');
      let args;
      try {
        if (typeof rawArguments !== 'string' || rawArguments.length > 2_048) return failure('INVALID_ARGUMENTS', 'Expected a small JSON object.');
        args = JSON.parse(rawArguments);
      } catch { return failure('INVALID_ARGUMENTS', 'Tool arguments must be valid JSON.'); }
      if (!args || Array.isArray(args) || typeof args !== 'object' || Object.keys(args).length !== 3 ||
          !['actionId', 'taskId', 'status'].every((key) => Object.hasOwn(args, key)) ||
          typeof args.actionId !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(args.actionId) ||
          typeof args.taskId !== 'string' || !['todo', 'in_progress', 'done'].includes(args.status)) {
        return failure('INVALID_ARGUMENTS', 'Use actionId, taskId, and a valid status with no extra fields.');
      }
      if (args.taskId !== task.id) return failure('UNKNOWN_TASK', 'Only the local practice task exists.');
      const fingerprint = JSON.stringify([args.taskId, args.status]);
      const prior = actions.get(args.actionId);
      if (prior) {
        if (prior.fingerprint !== fingerprint) return failure('ACTION_ID_CONFLICT', 'This actionId was already used for a different change.');
        return { ...structuredClone(prior.result), replayed: true, changed: false };
      }
      if (actions.size >= 1_000) return failure('ACTION_LIMIT', 'Restart the local board before more tutorial actions.');
      const previousStatus = task.status;
      task.status = args.status;
      const result = { ok: true, actionId: args.actionId, task: { ...task }, previousStatus, changed: previousStatus !== task.status, replayed: false };
      actions.set(args.actionId, { fingerprint, result: structuredClone(result) });
      return result;
    },
  };
}

export async function runToolRoundTrip(provider, { signal } = {}) {
  const board = createTaskBoard();
  const messages = [{ role: 'user', content: 'For this tutorial only, set task practice-task to done using actionId smoke-action-1. Then briefly confirm the tool result.' }];
  const first = await provider.complete(messages, { signal, tools: [taskTool], toolChoice: { type: 'function', function: { name: 'set_task_status' } } });
  const calls = first.message.tool_calls;
  if (!Array.isArray(calls) || calls.length !== 1 || !calls[0].id || calls[0].type !== 'function') throw new Error('Tool smoke expected exactly one function call.');
  const call = calls[0];
  const result = board.execute(call.function?.name, call.function?.arguments);
  if (!result.ok) throw new Error(`Tool smoke rejected arguments: ${result.error.code}.`);
  if (result.task.status !== 'done' || result.actionId !== 'smoke-action-1') throw new Error('Tool smoke did not perform the requested local action.');
  messages.push({ role: 'assistant', content: first.text || null, tool_calls: calls });
  messages.push({ role: 'tool', tool_call_id: call.id, content: JSON.stringify(result) });
  const final = await provider.complete(messages, { signal });
  if (!final.text.trim()) throw new Error('Tool smoke did not receive a final text response.');
  return { result, text: final.text, demo: provider.demo, board: board.snapshot() };
}
