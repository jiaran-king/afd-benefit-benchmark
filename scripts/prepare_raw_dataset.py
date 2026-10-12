"""Freeze ALL complete, eligible real sessions at 256k; never feed live outputs back.

Each worker writes one session to disk. The parent merges in original source
order and assigns the existing deterministic priorities and balanced routes.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import random
import time


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def initialize(model):
    global tokenizer
    from vllm.tokenizers import get_tokenizer
    tokenizer = get_tokenizer(model, tokenizer_mode='deepseek_v4', trust_remote_code=True)


def freeze_session(index, conversations, maximum, directory):
    assert conversations and len(conversations) % 2 == 0
    history = []
    pairs = len(conversations) // 2
    for turn in range(pairs):
        human, assistant = conversations[2 * turn:2 * turn + 2]
        assert human['from'] == 'human' and assistant['from'] == 'gpt'
        history.append({'role': 'user', 'content': human['value']})
        if turn != pairs - 1:
            history.append({'role': 'assistant', 'content': assistant['value']})
    final_tokens = tokenizer.apply_chat_template(history, tokenize=True, thinking=False)
    check = {'source_index': index, 'turns': pairs, 'final_prompt_tokens': len(final_tokens),
             'accepted': False}
    if len(final_tokens) + 1 > maximum:
        return check | {'exclusion': 'final original prompt + 1 exceeds service limit'}
    history, lengths = [], []
    temporary = Path(directory) / f'session-{index:04d}.jsonl'
    with temporary.open('x') as stream:
        for turn in range(pairs):
            human, assistant = conversations[2 * turn:2 * turn + 2]
            history.append({'role': 'user', 'content': human['value']})
            tokens = final_tokens if turn == pairs - 1 else tokenizer.apply_chat_template(
                history, tokenize=True, thinking=False)
            if len(tokens) + 1 > maximum:
                check.update(exclusion='an earlier original prompt + 1 exceeds service limit',
                             violating_turn=turn, violating_prompt_tokens=len(tokens))
                break
            lengths.append(len(tokens))
            row = {'id': f'source-{index:04d}-turn-{turn:03d}', 'session': index, 'turn': turn,
                'prompt_tokens': len(tokens), 'output_tokens': 1,
                'prompt_sha256': hashlib.sha256(json.dumps(tokens, separators=(',', ':')).encode()).hexdigest(),
                'body': {'model': 'dsv4-benefit', 'prompt': tokens, 'stream': True, 'temperature': 0,
                         'max_tokens': 1, 'min_tokens': 1, 'ignore_eos': True,
                         'stream_options': {'include_usage': True}}}
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            history.append({'role': 'assistant', 'content': assistant['value']})
        else:
            return check | {'accepted': True, 'max_prompt_tokens': max(lengths),
                            'prompt_tokens': sum(lengths), 'lengths': lengths}
    temporary.unlink()
    return check


def quantile(values, q):
    values = sorted(values)
    index = (len(values) - 1) * q
    lower = int(index)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (index - lower)


def run(args):
    source = json.loads(args.sessions.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    temporary = args.output / 'session-parts'
    temporary.mkdir()
    checks = {}
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                             initargs=(str(args.model),)) as executor:
        futures = {executor.submit(freeze_session, i, item['conversations'], args.max_length,
                                   str(temporary)): i for i, item in enumerate(source)}
        for future in as_completed(futures):
            result = future.result()
            checks[result['source_index']] = result
            status = {'finished_sessions': len(checks), 'source_sessions': len(source),
                      'accepted_sessions': sum(c['accepted'] for c in checks.values()), 'time': time.time()}
            (args.output / 'preparation-status.json').write_text(json.dumps(status))
            if len(checks) % 8 == 0 or len(checks) == len(source):
                print(json.dumps(status), flush=True)
    rng = random.Random(args.seed)
    positions, summaries, lengths = {}, [], []
    request_path = args.output / 'requests.jsonl'
    with request_path.open('x') as stream:
        for i in range(len(source)):
            check = checks[i]
            if not check['accepted']:
                continue
            position = rng.random()
            with (temporary / f'session-{i:04d}.jsonl').open() as part:
                for line in part:
                    row = json.loads(line)
                    row['priority'] = position
                    positions[row['id']] = position
                    stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
                    position += rng.expovariate(1.0)
            summaries.append({'session': i, 'turns': check['turns'],
                              'max_prompt_tokens': check['max_prompt_tokens'],
                              'prompt_tokens': check['prompt_tokens']})
            lengths.extend(check.pop('lengths'))
    assert summaries and lengths
    priority_path = args.output / 'priorities.json'
    priority_path.write_text(json.dumps({'seed': args.seed,
        'method': 'per-session uniform start + cumulative exponential(mean=1); dependency-ready selection',
        'positions': positions}, indent=2))
    routes = {}
    for domains, name in ((4, 'nonafd'), (3, 'afd')):
        loads, counts, assignments = [0] * domains, [0] * domains, {}
        for session in sorted(summaries, key=lambda s: (-s['max_prompt_tokens'], s['session'])):
            domain = min(range(domains), key=lambda d: (loads[d], counts[d], d))
            assignments[str(session['session'])] = domain
            loads[domain] += session['max_prompt_tokens']
            counts[domain] += 1
        path = args.output / f'route-{name}.json'
        path.write_text(json.dumps({'domains': domains, 'assignments': assignments,
            'method': 'descending max history length, greedily balance summed history lengths; deterministic',
            'per_domain_max_history_sum': loads, 'per_domain_sessions': counts}, indent=2))
        routes[name] = {'sha256': digest(path), 'domains': domains, 'loads': loads, 'sessions': counts}
    source_requests = sum(len(item['conversations']) // 2 for item in source)
    manifest = {'source_sha256': digest(args.sessions), 'request_sha256': digest(request_path),
        'priorities_sha256': digest(priority_path), 'routes': routes,
        'max_length': args.max_length, 'output_tokens': 1, 'seed': args.seed,
        'source_sessions': len(source), 'source_requests': source_requests,
        'sessions': len(summaries), 'requests': len(lengths), 'prompt_tokens': sum(lengths),
        'session_coverage_fraction': len(summaries) / len(source),
        'request_coverage_fraction': len(lengths) / source_requests,
        'excluded_sessions': len(source) - len(summaries),
        'length_distribution': {'min': min(lengths), 'max': max(lengths),
            'mean': sum(lengths) / len(lengths), 'p50': quantile(lengths, .5),
            'p95': quantile(lengths, .95), 'p99': quantile(lengths, .99),
            'requests_over_128k': sum(n > 131072 for n in lengths),
            'sessions_over_128k': sum(s['max_prompt_tokens'] > 131072 for s in summaries)},
        'selection': 'ALL complete sessions in source order with EVERY original user-round prompt + 1 <= max_length',
        'session_checks': [checks[i] for i in range(len(source))], 'session_summaries': summaries,
        'next_turn_history': 'original dataset messages; generated replay outputs never change next prompt',
        'arrival_times': 'absent; artificial ordinal priorities, no wall-clock waits', 'prepared': time.time(),
        'model_files': {name: digest(args.model / name) for name in
                        ('config.json', 'tokenizer.json', 'tokenizer_config.json')}}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    for part in temporary.iterdir():
        part.unlink()
    temporary.rmdir()
    print(json.dumps({k: v for k, v in manifest.items() if k not in
                      ('session_checks', 'session_summaries')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sessions', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-length', type=int, default=262144, choices=(262144,))
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--seed', type=int, default=20260928, choices=(20260928,))
    run(parser.parse_args())
