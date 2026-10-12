from collections import Counter
import json

SPEC_FIELDS = ("block_size", "num_kv_heads", "head_size", "dtype", "compress_ratio", "sliding_window",
    "page_size_bytes", "page_size_padded", "tail_tokens", "ring_blocks_per_request", "state_dim", "scale_dim", "scale_dtype", "model_version")


def spec_identity(spec):
    return {"class": type(spec).__name__, **{name: str(getattr(spec, name)) for name in SPEC_FIELDS if hasattr(spec, name)}}


def group_identity(layer_specs):
    counts = Counter(json.dumps(spec, sort_keys=True) for spec in layer_specs.values())
    return sorted([[json.loads(spec), count] for spec, count in counts.items()], key=lambda pair: json.dumps(pair[0], sort_keys=True))


def layout_identity(groups):
    return sorted([group_identity(group["layer_specs"]) for group in groups], key=lambda value: json.dumps(value, sort_keys=True))
