"""Publication figures for five audited single-run deployments."""
import argparse
import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter
import numpy as np

ROOT = Path(__file__).resolve().parents[2] / 'results/2026-10-12-ep16'
OUT = ROOT / 'figures'
GROUPS = ['non_ep4', 'non_ep8', 'non_ep16', 'afd_eager', 'afd_fgraph']
LABELS = ['Non EP4', 'Non EP8', 'Non EP16', 'AFD eager', 'AFD F FULL graph']
TICK_LABELS = ['EP4', 'EP8', 'EP16', 'AFD\neager', 'AFD F FULL\ngraph']
COLORS = ['#7A7F87', '#3B6B91', '#66619C', '#2A806F', '#BB7B38']
MARKERS = ['s', 'o', '^', 'o', 'D']


def load_rows():
    with (ROOT / 'metrics.csv').open(newline='') as stream:
        raw = {row['group']: row for row in csv.DictReader(stream)}
    assert set(raw) == set(GROUPS)
    rows = []
    for group, label in zip(GROUPS, LABELS):
        source = raw[group]
        prompt = int(source['prompt_tokens'])
        cached = int(source['cached_tokens'])
        prefill = int(source['actual_prefill_tokens'])
        assert int(source['sessions']) == 256 and int(source['requests']) == 9078
        assert prompt == 748751397 and prefill >= prompt - cached
        if int(source['preemptions']) == 0:
            assert cached + prefill == prompt
        rows.append({'group': group, 'label': label, 'prompt_tokens': prompt,
                     'kv_gib': float(source['total_actual_unique_kv_gib']),
                     'cached_tokens': cached, 'cache_pct': cached / prompt * 100,
                     'prefill_tokens': prefill, 'prefill_million': prefill / 1e6,
                     'prefill_pct': (prompt - cached) / prompt * 100,
                     'recompute_tokens': prefill - (prompt - cached),
                     'duration_minutes': float(source['duration_seconds']) / 60})
    OUT.mkdir(exist_ok=True)
    with (OUT / 'five-arm-figure-data.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def configure():
    for path in [Path(os.environ.get('REPORT_FONT', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))]:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            family = font_manager.FontProperties(fname=str(path)).get_name()
            break
    else:
        raise RuntimeError('Chinese font not available')
    plt.rcParams.update({'font.family': ['DejaVu Sans', family], 'font.size': 10,
                         'axes.titlesize': 11, 'axes.labelsize': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.edgecolor': '#69737C', 'axes.linewidth': .65,
                         'axes.axisbelow': True, 'grid.color': '#E5E8EB',
                         'grid.linewidth': .6, 'figure.facecolor': 'white',
                         'savefig.facecolor': 'white', 'pdf.fonttype': 42,
                         'svg.fonttype': 'path'})


def save(fig, stem):
    for suffix in ('png', 'svg', 'pdf'):
        fig.savefig(OUT / f'{stem}.{suffix}', dpi=300, bbox_inches='tight', pad_inches=.15)
    plt.close(fig)


def overview(rows):
    panels = [
        ('(a) 实际 KV 容量', '整机实际 KV（GiB）', 'kv_gib', '{:.1f}'),
        ('(b) 缓存采用率', '采用缓存的输入 tokens（%）', 'cache_pct', '{:.1f}%'),
        ('(c) 实际 prefill', '实际 prefill（百万 tokens）', 'prefill_million', '{:.1f}'),
        ('(d) 完整负载耗时', '全程耗时（分钟）', 'duration_minutes', '{:.1f}'),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11.4, 7.5))
    fig.subplots_adjust(left=.08, right=.98, top=.94, bottom=.11, hspace=.62, wspace=.28)
    for ax, (title, ylabel, field, fmt) in zip(axes.flat, panels):
        values = [row[field] for row in rows]
        bars = ax.bar(np.arange(5), values, color=COLORS, width=.63,
                      edgecolor='white', linewidth=.5, zorder=3)
        ax.set_xticks(np.arange(5), TICK_LABELS)
        ax.set_ylim(0, 100 if field == 'cache_pct' else max(values) * 1.22)
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc='left')
        ax.grid(axis='y')
        ax.bar_label(bars, labels=[fmt.format(value) for value in values], padding=3, fontsize=9)
    save(fig, 'fig01_five_arm_overview')


def partition(rows):
    fig, ax = plt.subplots(figsize=(10.8, 4.6))
    fig.subplots_adjust(left=.19, right=.83, top=.85, bottom=.15)
    y = np.arange(5)
    adopted = np.array([row['cache_pct'] for row in rows])
    prefill = np.array([row['prefill_pct'] for row in rows])
    ax.barh(y, adopted, height=.57, color='#D6DEE5', edgecolor='white')
    ax.barh(y, prefill, left=adopted, height=.57, color='#4D657A', edgecolor='white')
    for i, row in enumerate(rows):
        ax.text(adopted[i] / 2, i, f'{adopted[i]:.2f}%', ha='center', va='center', fontsize=9.5)
        ax.text(adopted[i] + prefill[i] / 2, i, f'{prefill[i]:.2f}%',
                ha='center', va='center', fontsize=9, color='white')
        ax.text(102, i, f"{row['prefill_million']:.2f} M", ha='left', va='center', fontsize=9.5)
    ax.set_yticks(y, LABELS)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks(np.arange(0, 101, 20))
    ax.xaxis.set_major_formatter(PercentFormatter(100, decimals=0))
    ax.set_xlabel('原始输入 tokens 占比')
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y', length=0)
    fig.text(.19, .97, '同一冻结输入：748.751 M tokens / 组', va='top', fontsize=10.5)
    fig.legend(handles=[Patch(facecolor='#D6DEE5', label='采用缓存'),
                        Patch(facecolor='#4D657A', label='未采用缓存的输入')],
               loc='upper left', bbox_to_anchor=(.18, .92), ncol=2, frameon=False)
    save(fig, 'fig02_five_arm_cache_prefill_partition')


def relationships(rows):
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.3, 4.8))
    fig.subplots_adjust(left=.09, right=.98, top=.88, bottom=.23, wspace=.30)
    for ax in (left, right):
        ax.grid(axis='both')
    for i, row in enumerate(rows):
        for ax, x, y in [(left, row['kv_gib'], row['cache_pct']),
                         (right, row['prefill_million'], row['duration_minutes'])]:
            ax.scatter(x, y, marker=MARKERS[i], s=80 if i == 4 else 60,
                       facecolor='none' if i == 4 else COLORS[i], edgecolor=COLORS[i],
                       linewidth=1.4 if i == 4 else .8, zorder=4)
    left.set(xlim=(0, max(row['kv_gib'] for row in rows) * 1.13), ylim=(0, 100),
             xlabel='整机实际 KV 容量（GiB）', ylabel='缓存采用率（%）')
    right.set(xlim=(0, max(row['prefill_million'] for row in rows) * 1.12),
              ylim=(0, max(row['duration_minutes'] for row in rows) * 1.13),
              xlabel='实际 prefill（百万 tokens）', ylabel='全程耗时（分钟）')
    left.set_title('(a) KV 容量与缓存采用率', loc='left')
    right.set_title('(b) 实际 prefill 与全程耗时', loc='left')
    handles = [Line2D([], [], marker=MARKERS[i], linestyle='none', color=COLORS[i],
                      markerfacecolor='none' if i == 4 else COLORS[i], markersize=7,
                      markeredgewidth=1.2, label=LABELS[i]) for i in range(5)]
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(.53, .01),
               ncol=5, frameon=False, fontsize=8.8, columnspacing=1.0)
    save(fig, 'fig03_five_arm_relationships')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=OUT)
    OUT = parser.parse_args().output_dir
    OUT.mkdir(parents=True, exist_ok=True)
    data = load_rows()
    configure()
    overview(data)
    partition(data)
    relationships(data)
    print(f'created three five-arm figures in {OUT}')
