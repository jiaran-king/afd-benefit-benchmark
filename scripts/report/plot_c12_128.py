"""Figures for the audited prefix-on C12 / 128-session deployment comparison."""
import argparse
import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[2] / 'results/2026-10-14-c12-128'
GROUPS = ['non_ep4', 'non_ep8', 'non_ep16', 'afd_eager']
LABELS = ['EP4', 'EP8', 'EP16', 'AFD eager']
COLORS = ['#7A7F87', '#3B6B91', '#66619C', '#2A806F']


def configure():
    font = Path(os.environ.get('REPORT_FONT', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
    if not font.exists():
        raise RuntimeError('Set REPORT_FONT to an available Chinese font file')
    font_manager.fontManager.addfont(str(font))
    family = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({'font.family': ['DejaVu Sans', family], 'font.size': 10,
        'axes.titlesize': 11, 'axes.labelsize': 10, 'axes.spines.top': False,
        'axes.spines.right': False, 'axes.axisbelow': True, 'grid.color': '#E5E8EB',
        'grid.linewidth': .6, 'figure.facecolor': 'white', 'savefig.facecolor': 'white',
        'pdf.fonttype': 42, 'svg.fonttype': 'path'})


def save(fig, out, name):
    for ext in ['png', 'svg', 'pdf']:
        fig.savefig(out / f'{name}.{ext}', dpi=240, bbox_inches='tight', pad_inches=.16)
    plt.close(fig)


def plot(out):
    out.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'metrics.csv').open() as f:
        raw = {r['group']: r for r in csv.DictReader(f)}
    rows = []
    for g, label in zip(GROUPS, LABELS):
        r = raw[g]
        assert int(r['requests']) == 3725 and int(r['sessions']) == 128
        rows.append(dict(group=g, label=label, kv_gib=float(r['actual_unique_kv_gib']),
            cache_pct=float(r['hit_rate']) * 100,
            prefill_tokens=int(r['actual_prefill_tokens']),
            prefill_million=int(r['actual_prefill_tokens']) / 1e6,
            duration_seconds=float(r['duration_seconds']),
            duration_minutes=float(r['duration_seconds']) / 60))
    with (out / 'four-arm-figure-data.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    panels = [
        ('(a) 实际 KV 容量', '整机实际 KV（GiB）', 'kv_gib', '{:.1f}'),
        ('(b) 缓存采用率', '采用缓存的输入 tokens（%）', 'cache_pct', '{:.2f}%'),
        ('(c) 实际 prefill', '实际 prefill（百万 tokens）', 'prefill_million', '{:.2f}'),
        ('(d) 完整负载耗时', '全程耗时（分钟）', 'duration_minutes', '{:.2f}')]
    fig, axes = plt.subplots(2, 2, figsize=(10.7, 7.1))
    fig.subplots_adjust(left=.09, right=.98, top=.93, bottom=.09, hspace=.53, wspace=.30)
    for ax, (title, label, field, fmt) in zip(axes.flat, panels):
        values = [r[field] for r in rows]
        bars = ax.bar(np.arange(4), values, color=COLORS, width=.62, zorder=3)
        ax.set_xticks(np.arange(4), LABELS)
        ax.set_ylim(0, 105 if field == 'cache_pct' else max(values) * 1.23)
        ax.set_title(title, loc='left')
        ax.set_ylabel(label)
        ax.grid(axis='y')
        ax.bar_label(bars, labels=[fmt.format(x) for x in values], padding=3, fontsize=9)
    save(fig, out, 'fig01_four_arm_overview')

    with (ROOT / 'per-die-memory.csv').open() as f:
        memory = list(csv.DictReader(f))
    roles = [('non_ep4', 'nonafd', 'EP4 / 16 DIE'), ('non_ep8', 'nonafd', 'EP8 / 16 DIE'),
        ('non_ep16', 'nonafd', 'EP16 / 16 DIE'), ('afd_eager', 'attention', 'AFD A / 12 DIE'),
        ('afd_eager', 'ffn', 'AFD F / 4 DIE')]
    fig, axes = plt.subplots(1, 2, figsize=(10.7, 4.0), sharey=True)
    fig.subplots_adjust(left=.19, right=.98, top=.85, bottom=.19, wspace=.28)
    for ax in axes:
        ax.grid(axis='x')
        ax.set_xlim(0, 50)
        ax.set_xlabel('每 DIE（GiB）')
    for i, (g, role, label) in enumerate(roles):
        rs = [r for r in memory if r['group'] == g and r['role'] == role]
        color = COLORS[GROUPS.index(g)]
        for ax, field in zip(axes, ['weights_load_gib_reported', 'kv_actual_gib']):
            values = [float(r[field]) for r in rs if r[field]]
            if values:
                mean = sum(values) / len(values)
                ax.barh(i, mean, height=.57, color=color, zorder=3)
                ax.errorbar(mean, i, xerr=[[max(0., mean-min(values))], [max(0., max(values)-mean)]], fmt='none', color='#293742', capsize=3, zorder=4)
                ax.text(mean + .7, i, f'{mean:.2f}', va='center', fontsize=9)
            else:
                ax.text(.6, i, '无 attention KV 分配记录', va='center', color='#5F6670', fontsize=9)
    axes[0].set_yticks(range(5), [r[2] for r in roles])
    axes[0].invert_yaxis()
    axes[0].set_title('(a) 权重加载阶段占用', loc='left')
    axes[1].set_title('(b) 实际唯一 KV storage', loc='left')
    save(fig, out, 'fig02_per_die_memory')
    print(f'Created two four-arm figures in {out}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'figures')
    args = parser.parse_args()
    configure()
    plot(args.output_dir)
