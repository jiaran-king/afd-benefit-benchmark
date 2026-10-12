"""Experiment-only host counters; wraps calls without changing return values."""
import json
import time
from collections import Counter
from pathlib import Path


def install(scheduler, output):
    from vllm_ascend.core.compressor_checkpoint import TailCheckpointKey
    from vllm_ascend.patch.platform.patch_kv_cache_coordinator import AscendHybridKVCacheCoordinator

    coordinator = scheduler.checkpoint_coordinator
    pool = scheduler.checkpoint_coordinator.checkpoints
    blocks = scheduler.kv_cache_manager.block_pool
    counters = Counter()
    requests = {}
    lookups = {}
    evicted = {}
    reason = ["unknown"]
    stream = Path(output).open("x", buffering=1)
    peak = {"checkpoint_blocks": 0, "ready": 0, "referenced_blocks": 0}
    min_free = [blocks.get_num_free_blocks()]

    def state():
        ready = sum(entry.ready for entry in pool._entries.values())
        free = blocks.get_num_free_blocks()
        peak["checkpoint_blocks"] = max(peak["checkpoint_blocks"], pool.used_blocks)
        peak["ready"] = max(peak["ready"], ready)
        peak["referenced_blocks"] = max(peak["referenced_blocks"], blocks.num_gpu_blocks - 1 - free)
        min_free[0] = min(min_free[0], free)
        return {"checkpoint_blocks": pool.used_blocks, "ready": ready, "free_blocks": free,
                "min_free_blocks": min_free[0], "peak": dict(peak), "counters": dict(counters)}

    def emit(event, **fields):
        stream.write(json.dumps({"event": event, "time": time.time(), **fields}, separators=(",", ":")) + "\n")

    original_drop = pool._drop
    def drop(handle):
        entry = pool._entries[handle]
        key = entry.key
        result = original_drop(handle)
        evicted[key] = reason[0]
        counters["checkpoint_evicted"] += 1
        counters["checkpoint_evicted_" + reason[0]] += 1
        emit("checkpoint_evicted", handle=handle, position=key.position,
             prefix_hash=bytes(key.prefix_hash).hex(), reason=reason[0])
        return result
    pool._drop = drop

    for method, label in (("reserve", "snapshot_budget"), ("reclaim", "request_admission"),
                          ("discard", "failed_restore_admission"), ("reset", "reset")):
        original = getattr(pool, method)
        def wrap(*args, _original=original, _method=method, _label=label, **kwargs):
            prior = reason[0]
            reason[0] = "snapshot_allocation" if _method == "reclaim" and prior == "snapshot_budget" else _label
            try:
                result = _original(*args, **kwargs)
                if _method == "reserve" and result is not None:
                    counters["checkpoint_created"] += 1
                    evicted.pop(pool._entries[result.handle].key, None)
                    state()
                return result
            finally:
                reason[0] = prior
        setattr(pool, method, wrap)

    original_complete = pool.complete_save
    def complete(handle):
        result = original_complete(handle)
        state()
        return result
    pool.complete_save = complete

    original_evict = blocks._maybe_evict_cached_block
    def evict(block):
        result = original_evict(block)
        counters["ordinary_cached_block_evictions"] += int(result)
        return result
    blocks._maybe_evict_cached_block = evict

    original_allocate = scheduler.kv_cache_manager.allocate_slots
    def allocate(*args, **kwargs):
        result = original_allocate(*args, **kwargs)
        counters["admission_allocation_failed_attempts"] += int(result is None)
        return result
    scheduler.kv_cache_manager.allocate_slots = allocate

    original_lookup = scheduler.kv_cache_manager.get_computed_blocks
    def lookup(req, *args, **kwargs):
        result = original_lookup(req, *args, **kwargs)
        probe_started = time.perf_counter()
        # This base lookup reads the same hash map without touching allocator,
        # references, LRU order or native lookup metrics. Tail groups have
        # already been excluded by CompressorCheckpointCoordinator.
        _, ordinary_hit, _ = AscendHybridKVCacheCoordinator.find_longest_cache_hit(
            coordinator, req.block_hashes, req.num_tokens - 1)
        selected = result[1]
        fields = {"selected_hit": selected, "ordinary_joint_hit": ordinary_hit,
                  "cache_read_enabled": scheduler.kv_cache_manager.prefix_cache_lookup_enabled(req)}
        if ordinary_hit > selected:
            key = TailCheckpointKey(req.block_hashes[ordinary_hit // scheduler.hash_block_size - 1], ordinary_hit)
            fields.update(checkpoint_limits_joint_hit=True,
                          limiting_checkpoint_position=ordinary_hit,
                          limiting_checkpoint_evicted_reason=evicted.get(key),
                          limiting_checkpoint_ready=pool.lookup(key) is not None)
        if ordinary_hit == 0:
            _, hits = coordinator.find_longest_cache_hit_per_group(req.block_hashes, req.num_tokens - 1)
            fields["ordinary_per_group_hits"] = {str(group): hit for group, hit in enumerate(hits)
                if group not in coordinator.tail_managers}
            candidate = pool.find_candidate(req.block_hashes, req.num_tokens - 1,
                                            coordinator.lcm_block_size, scheduler.hash_block_size)
            fields["ready_checkpoint_candidate"] = None if candidate is None else candidate[1]
        lookups[req.request_id] = fields
        fields["observation_seconds"] = time.perf_counter() - probe_started
        counters["lookup_observation_microseconds"] += int(fields["observation_seconds"] * 1e6)
        emit("cache_lookup", request_id=req.request_id, preemptions=req.num_preemptions, **fields)
        return result
    scheduler.kv_cache_manager.get_computed_blocks = lookup

    original_schedule = scheduler.schedule
    def schedule(*args, **kwargs):
        result = original_schedule(*args, **kwargs)
        for rid, count in result.num_scheduled_tokens.items():
            req = scheduler.requests[rid]
            start = req.num_computed_tokens - count
            row = requests.setdefault(rid, {"cached_tokens": min(start, req.num_prompt_tokens), "actual_prefill_tokens": 0})
            row["actual_prefill_tokens"] += max(0, min(req.num_prompt_tokens, start + count) - min(req.num_prompt_tokens, start))
        counters["restore_plans"] += len(result.compressor_restores)
        free = blocks.get_num_free_blocks()
        min_free[0] = min(min_free[0], free)
        peak["referenced_blocks"] = max(peak["referenced_blocks"], blocks.num_gpu_blocks - 1 - free)
        return result
    scheduler.schedule = schedule

    original_free = scheduler._free_request
    def free(req, *args, **kwargs):
        result = original_free(req, *args, **kwargs)
        row = requests.pop(req.request_id, {"cached_tokens": 0, "actual_prefill_tokens": 0})
        counters["requests_finished"] += 1
        counters["preemptions"] += req.num_preemptions
        emit("request_finished", request_id=req.request_id, prompt_tokens=req.num_prompt_tokens,
             output_tokens=req.num_output_tokens, preemptions=req.num_preemptions,
             status=str(req.status), lookup=lookups.pop(req.request_id, None), **row, **state())
        return result
    scheduler._free_request = free
    emit("capacity", N=blocks.num_gpu_blocks, B=pool.max_blocks, R=pool.blocks_per_checkpoint,
         capacity=pool.max_blocks // pool.blocks_per_checkpoint,
         ring_blocks=pool.ring_blocks, alignment=scheduler.checkpoint_coordinator.lcm_block_size,
         scheduler_class=type(scheduler).__name__)
    return state


def record_worker_capacity(runner, config, raw_tensors, output):
    """Record actual allocator backing and ring layout without NPU copies."""
    from vllm.distributed import get_tp_group
    from vllm_ascend.ascend_config import get_ascend_config
    from layout_identity import spec_identity

    dp_rank = runner.vllm_config.parallel_config.data_parallel_rank
    tp_rank = get_tp_group().rank_in_group
    path = Path(output.format(dp_rank=dp_rank, tp_rank=tp_rank))
    storages = {}
    for value in raw_tensors.values():
        storage = value.untyped_storage()
        storages[(str(value.device), storage.data_ptr())] = storage.nbytes()
    specs = runner._get_layer_kv_cache_specs(config)
    groups = []
    for group in config.kv_cache_groups:
        groups.append({"layers": group.layer_names,
            "layer_specs": {layer: spec_identity(specs[layer]) for layer in group.layer_names}})
    planned = sum(tensor.size for tensor in config.kv_cache_tensors)
    moe_layouts = []
    for name, module in runner.model.named_modules():
        if hasattr(module, 'shared_experts'):
            shared = module.shared_experts
            moe_layouts.append({'name': name, 'class': type(module).__name__,
                'ep_size': getattr(module, 'ep_size', None), 'tp_size': getattr(module, 'tp_size', None),
                'shared_experts_class': type(shared).__name__ if shared is not None else None,
                'shared_parameters': {key: list(value.shape) for key, value in shared.named_parameters()}
                    if shared is not None else {}})
            if len(moe_layouts) == 2:
                break
    vconfig = runner.vllm_config
    result = {"runner": type(runner).__name__, "device": str(runner.device), "dp_rank": dp_rank, "tp_rank": tp_rank,
        "N": config.num_blocks, "planned_backing_bytes": planned, "actual_unique_storage_bytes": sum(storages.values()),
        "stride": planned // config.num_blocks, "groups": groups,
        "checkpoint_page_groups": {str(group): {"layers": len(pages), "shapes": [list(page.shape) for page in pages]}
            for group, pages in runner._compressor_checkpoint_pages.items()},
        "prefix_cache": vconfig.cache_config.enable_prefix_caching,
        "shared_compressor_workspace": get_ascend_config().enable_dsv4_shared_compressor_workspace,
        "flashcomm1_effective": get_ascend_config().enable_flashcomm1,
        "shared_expert_dp_effective": get_ascend_config().enable_shared_expert_dp,
        "prefill_mc2_effective": getattr(get_ascend_config(), 'enable_prefill_mc2', None),
        "model_class": type(runner.model).__name__,
        "sample_moe_layouts": moe_layouts,
        "checkpoint_ratio": get_ascend_config().compressor_checkpoint_budget_ratio,
        "async_scheduling": vconfig.scheduler_config.async_scheduling,
        "scheduler": vconfig.scheduler_config.scheduler_cls,
        "max_model_len": vconfig.model_config.max_model_len,
        "max_num_seqs": vconfig.scheduler_config.max_num_seqs,
        "mbt": vconfig.scheduler_config.max_num_batched_tokens,
        "speculative": vconfig.speculative_config is not None, "kv_transfer": vconfig.kv_transfer_config is not None}
    with path.open("x") as stream:
        json.dump(result, stream, indent=2)
