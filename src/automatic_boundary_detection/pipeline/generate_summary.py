#!/usr/bin/env python3
"""
Generate a summary JSON with per-page TP/FP/FN metrics (per-element and per-group).

Usage:
    python ../shared/generate_summary.py <page1>:<page1_metrics.json> \
                                         <page2>:<page2_metrics.json> \
                                         ... \
                                         --merged <merged_metrics.json> \
                                         --output <summary_all_pages.json>

Page names depend on the site (gitlab: project/issue/user; booking:
homepage/hotel/search; google_flights: details/explore/search).
"""

import json
import argparse
import sys
from pathlib import Path


def extract_metrics(data):
    """Extract per-element and per-group metrics from a comparison_metrics.json."""
    m = data.get('metrics', {})
    s = data.get('signature_metrics', {})

    return {
        'per_element': {
            'tp': m.get('tp_count', 0),
            'fp': m.get('fp_count', 0),
            'fn': m.get('fn_count', 0),
            'precision': m.get('precision', 0.0),
            'recall': m.get('recall', 0.0),
            'f1_score': m.get('f1_score', 0.0),
            'accuracy': m.get('accuracy', 0.0),
        },
        'per_group': {
            'tp': s.get('tp_signature_count', 0),
            'fp': s.get('fp_signature_count', 0),
            'fn': s.get('fn_signature_count', 0),
            'precision': s.get('precision', 0.0),
            'recall': s.get('recall', 0.0),
            'f1_score': s.get('f1_score', 0.0),
            'accuracy': s.get('accuracy', 0.0),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description='Generate per-page summary JSON from comparison metrics',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'pages', nargs='+',
        help='page_name:metrics_file pairs (e.g. project:Results/project/comparison_metrics.json)',
    )
    parser.add_argument('--merged', help='Path to merged_metrics.json')
    parser.add_argument('--output', '-o', required=True, help='Output summary JSON file')

    args = parser.parse_args()

    summary = {'pages': {}}

    for entry in args.pages:
        if ':' not in entry:
            print(f"Error: expected page_name:file format, got: {entry}", file=sys.stderr)
            sys.exit(1)
        page_name, file_path = entry.split(':', 1)
        if not Path(file_path).exists():
            print(f"Error: file not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        with open(file_path, 'r') as f:
            data = json.load(f)
        summary['pages'][page_name] = extract_metrics(data)

    if args.merged:
        if not Path(args.merged).exists():
            print(f"Error: merged file not found: {args.merged}", file=sys.stderr)
            sys.exit(1)
        with open(args.merged, 'r') as f:
            merged_data = json.load(f)
        summary['merged'] = extract_metrics(merged_data)

    with open(args.output, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"Summary saved to: {args.output}")


if __name__ == '__main__':
    main()
