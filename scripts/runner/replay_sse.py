"""Small shared SSE framing/validation layer for this experiment."""
import json


async def sse_events(lines):
    data = []
    event_type = ''
    async for line in lines:
        if not line:
            if data:
                if event_type == 'error':
                    raise ValueError('SSE error event: ' + '\n'.join(data))
                yield '\n'.join(data)
            data = []
            event_type = ''
        elif line.startswith('data:'):
            value = line[5:]
            data.append(value[1:] if value.startswith(' ') else value)
        elif line.startswith('event:'):
            event_type = line[6:].strip()
    if data:
        raise ValueError('truncated SSE event at EOF')


class CompletionState:
    def __init__(self):
        self.done = False
        self.finish_reasons = []
        self.backend_ids = set()
        self.usage = {}
        self.events = 0
        self.output_token_count = 0
        self.token_ids_observed = False
        self.bos_token_count = 0
        self.text_characters = 0

    def observe(self, raw):
        if self.done:
            raise ValueError('event after DONE')
        self.events += 1
        if raw == '[DONE]':
            self.done = True
            self.validate()
            return None
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError('non-object SSE payload')
        if payload.get('error') or payload.get('type') == 'error':
            raise ValueError('backend error: ' + str(payload))
        if payload.get('id'):
            self.backend_ids.add(payload['id'])
        if isinstance(payload.get('usage'), dict):
            self.usage.update(payload['usage'])
        for choice in payload.get('choices', []):
            tokens = choice.get('token_ids')
            if tokens is not None:
                self.token_ids_observed = True
                self.output_token_count += len(tokens)
                self.bos_token_count += tokens.count(0)
            delta = choice.get('delta') or {}
            self.text_characters += len(delta.get('content') or '') + len(delta.get('reasoning_content') or '') + len(delta.get('reasoning') or '')
            if choice.get('stop_reason') == 'recomputed':
                raise ValueError('recomputed; resubmission forbidden')
            reason = choice.get('finish_reason')
            if reason is not None:
                if reason not in ('stop', 'length', 'tool_calls', 'function_call'):
                    raise ValueError('invalid finish reason: ' + str(reason))
                self.finish_reasons.append(reason)
        return payload

    def validate(self):
        if not self.done or not self.finish_reasons:
            raise ValueError('incomplete completion: missing DONE or finish reason')
        if self.token_ids_observed and self.usage.get('completion_tokens') != self.output_token_count:
            raise ValueError('stream output token IDs do not match completion usage')

    def evidence(self):
        return dict(done_marker=self.done, finish_reasons=self.finish_reasons,
                    backend_response_ids=sorted(self.backend_ids), events=self.events,
                    raw_usage=self.usage, token_ids_observed=self.token_ids_observed,
                    output_token_count=self.output_token_count, bos_token_count=self.bos_token_count,
                    text_characters=self.text_characters)


def generated_delta(payload):
    choices = payload.get('choices') or []
    if not choices:
        return '', False
    choice = choices[0]
    delta = choice.get('delta') or {}
    text = delta.get('content') or delta.get('reasoning_content') or delta.get('reasoning') or choice.get('text') or ''
    generated = bool(text or delta.get('tool_calls') or delta.get('function_call') or choice.get('token_ids'))
    return text, generated
