#!/usr/bin/env python3
"""
Plot comparison metrics showing overmasking, undermasking, and correct masking.

Usage:
    # Single file
    python plot_comparison_metrics.py comparison_metrics.json --output plot.png

    # Multiple files (merge across pages)
    python plot_comparison_metrics.py page1/metrics.json page2/metrics.json page3/metrics.json --output merged_plot.png

    python ../shared/plot_comparison_metrics.py <RESULTS_DIR>/project/comparison_metrics.json <RESULTS_DIR>/issue/comparison_metrics.json <RESULTS_DIR>/user/comparison_metrics.json --output <RESULTS_DIR>/merged_plot_metrics.png --merged-output <RESULTS_DIR>/merged_metrics.json
"""

import json
import argparse
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend to avoid display issues
import numpy as np
from typing import Dict, List, Optional, Tuple


def load_comparison_metrics(file_path: str) -> Dict:
    """Load comparison metrics from JSON file."""
    with open(file_path, 'r') as f:
        return json.load(f)


def get_element_signature(element_info: Dict) -> str:
    """
    Create a signature string from element characteristics (tagName, className, id).
    """
    tag = element_info.get('tagName', '').lower()
    classes = element_info.get('className', '').strip()
    elem_id = element_info.get('id', '').strip()
    
    parts = []
    if tag:
        parts.append(tag)
    
    if classes:
        class_list = sorted(classes.split())
        for cls in class_list:
            parts.append(f".{cls}")

    signature = ''.join(parts) if parts else 'unknown'
    return signature


def group_elements_by_signature(elements: List[Dict], id_to_element_info: Dict[str, Dict]) -> Dict[str, List[Dict]]:
    """
    Group elements by their HTML characteristics signature.
    Returns a dict mapping signature -> list of elements with that signature.
    """
    grouped = {}
    for elem in elements:
        xpath = elem.get('xpath', '')
        element_info = id_to_element_info.get(xpath, {})
        signature = get_element_signature(element_info)
        
        if signature not in grouped:
            grouped[signature] = []
        grouped[signature].append(elem)
    
    return grouped


def merge_metrics(metrics1: Dict, metrics2: Dict) -> Dict:
    """
    Merge two comparison metrics as if they are from the same page.
    Combines TP, FP, FN sets and recalculates metrics with full format.
    """
    # Get element details from both - create xpath -> element mapping
    elem_details1 = metrics1.get('element_details', {})
    elem_details2 = metrics2.get('element_details', {})
    
    tp1_dict = {e['xpath']: e for e in elem_details1.get('tp', [])}
    fp1_dict = {e['xpath']: e for e in elem_details1.get('fp', [])}
    fn1_dict = {e['xpath']: e for e in elem_details1.get('fn', [])}
    
    tp2_dict = {e['xpath']: e for e in elem_details2.get('tp', [])}
    fp2_dict = {e['xpath']: e for e in elem_details2.get('fp', [])}
    fn2_dict = {e['xpath']: e for e in elem_details2.get('fn', [])}
    
    # Merge: combine all elements
    all_tp_xpaths = set(tp1_dict.keys()) | set(tp2_dict.keys())
    all_fp_xpaths = set(fp1_dict.keys()) | set(fp2_dict.keys())
    all_fn_xpaths = set(fn1_dict.keys()) | set(fn2_dict.keys())
    
    # Remove overlaps: if something is TP, it can't be FP or FN
    all_fp_xpaths = all_fp_xpaths - all_tp_xpaths
    all_fn_xpaths = all_fn_xpaths - all_tp_xpaths
    
    # Build merged element_details lists
    merged_tp_elements = []
    for xpath in sorted(all_tp_xpaths):
        # Prefer from file 1, fallback to file 2
        elem = tp1_dict.get(xpath) or tp2_dict.get(xpath)
        if elem:
            merged_tp_elements.append(elem)
    
    merged_fp_elements = []
    for xpath in sorted(all_fp_xpaths):
        elem = fp1_dict.get(xpath) or fp2_dict.get(xpath)
        if elem:
            merged_fp_elements.append(elem)
    
    merged_fn_elements = []
    for xpath in sorted(all_fn_xpaths):
        elem = fn1_dict.get(xpath) or fn2_dict.get(xpath)
        if elem:
            merged_fn_elements.append(elem)
    
    # Build id_to_element_info mapping for grouping
    id_to_element_info = {}
    for elem in merged_tp_elements + merged_fp_elements + merged_fn_elements:
        xpath = elem.get('xpath', '')
        if xpath:
            id_to_element_info[xpath] = {
                'tagName': elem.get('tagName', ''),
                'className': elem.get('className', ''),
                'id': elem.get('id', '')
            }
    
    # Group elements by signature
    fp_grouped = group_elements_by_signature(merged_fp_elements, id_to_element_info)
    fn_grouped = group_elements_by_signature(merged_fn_elements, id_to_element_info)
    
    # Calculate merged metrics
    merged_tp_count = len(all_tp_xpaths)
    merged_fp_count = len(all_fp_xpaths)
    merged_fn_count = len(all_fn_xpaths)
    
    # Calculate ground_truth_total and predicted_total
    gt_total1 = metrics1.get('metrics', {}).get('ground_truth_total', 0)
    gt_total2 = metrics2.get('metrics', {}).get('ground_truth_total', 0)
    pred_total1 = metrics1.get('metrics', {}).get('predicted_total', 0)
    pred_total2 = metrics2.get('metrics', {}).get('predicted_total', 0)
    
    # For merged, we need to count unique elements from both
    gt_elements1 = set(tp1_dict.keys()) | set(fn1_dict.keys())
    gt_elements2 = set(tp2_dict.keys()) | set(fn2_dict.keys())
    pred_elements1 = set(tp1_dict.keys()) | set(fp1_dict.keys())
    pred_elements2 = set(tp2_dict.keys()) | set(fp2_dict.keys())
    
    merged_gt_total = len(gt_elements1 | gt_elements2)
    merged_pred_total = len(pred_elements1 | pred_elements2)
    
    merged_precision = merged_tp_count / (merged_tp_count + merged_fp_count) if (merged_tp_count + merged_fp_count) > 0 else 0.0
    merged_recall = merged_tp_count / (merged_tp_count + merged_fn_count) if (merged_tp_count + merged_fn_count) > 0 else 0.0
    merged_f1 = 2 * (merged_precision * merged_recall) / (merged_precision + merged_recall) if (merged_precision + merged_recall) > 0 else 0.0
    merged_accuracy = merged_tp_count / (merged_tp_count + merged_fp_count + merged_fn_count) if (merged_tp_count + merged_fp_count + merged_fn_count) > 0 else 0.0
    
    # For TP exact/related counts, we need to check parent-child relationships
    # For simplicity, we'll set them to the same as tp_count
    merged_tp_exact_count = merged_tp_count  # Simplified
    merged_tp_related_count = 0  # Simplified
    
    # Merge signature metrics
    sig_metrics1 = metrics1.get('signature_metrics', {})
    sig_metrics2 = metrics2.get('signature_metrics', {})
    
    tp_sig1 = set(sig_metrics1.get('tp_signatures', []))
    fp_sig1 = set(sig_metrics1.get('fp_signatures', []))
    fn_sig1 = set(sig_metrics1.get('fn_signatures', []))
    
    tp_sig2 = set(sig_metrics2.get('tp_signatures', []))
    fp_sig2 = set(sig_metrics2.get('fp_signatures', []))
    fn_sig2 = set(sig_metrics2.get('fn_signatures', []))
    
    # Merge signatures
    all_tp_sig = tp_sig1 | tp_sig2
    all_fp_sig = fp_sig1 | fp_sig2
    all_fn_sig = fn_sig1 | fn_sig2
    
    # Remove overlaps
    all_fp_sig = all_fp_sig - all_tp_sig
    all_fn_sig = all_fn_sig - all_tp_sig
    
    merged_tp_sig_count = len(all_tp_sig)
    merged_fp_sig_count = len(all_fp_sig)
    merged_fn_sig_count = len(all_fn_sig)
    
    # Calculate signature totals
    gt_sig1 = set(sig_metrics1.get('tp_signatures', [])) | set(sig_metrics1.get('fn_signatures', []))
    gt_sig2 = set(sig_metrics2.get('tp_signatures', [])) | set(sig_metrics2.get('fn_signatures', []))
    pred_sig1 = set(sig_metrics1.get('tp_signatures', [])) | set(sig_metrics1.get('fp_signatures', []))
    pred_sig2 = set(sig_metrics2.get('tp_signatures', [])) | set(sig_metrics2.get('fp_signatures', []))
    
    merged_gt_sig_total = len(gt_sig1 | gt_sig2)
    merged_pred_sig_total = len(pred_sig1 | pred_sig2)
    
    merged_sig_precision = merged_tp_sig_count / (merged_tp_sig_count + merged_fp_sig_count) if (merged_tp_sig_count + merged_fp_sig_count) > 0 else 0.0
    merged_sig_recall = merged_tp_sig_count / (merged_tp_sig_count + merged_fn_sig_count) if (merged_tp_sig_count + merged_fn_sig_count) > 0 else 0.0
    merged_sig_f1 = 2 * (merged_sig_precision * merged_sig_recall) / (merged_sig_precision + merged_sig_recall) if (merged_sig_precision + merged_sig_recall) > 0 else 0.0
    merged_sig_accuracy = merged_tp_sig_count / (merged_tp_sig_count + merged_fp_sig_count + merged_fn_sig_count) if (merged_tp_sig_count + merged_fp_sig_count + merged_fn_sig_count) > 0 else 0.0
    
    # Merge metadata
    gt_meta1 = metrics1.get('ground_truth_metadata', {})
    gt_meta2 = metrics2.get('ground_truth_metadata', {})
    pred_meta1 = metrics1.get('predicted_metadata', {})
    pred_meta2 = metrics2.get('predicted_metadata', {})
    
    # Merge selector breakdown
    selector_breakdown1 = metrics1.get('selector_breakdown', {})
    selector_breakdown2 = metrics2.get('selector_breakdown', {})
    
    # Merge selector_to_ids (combine selectors from both)
    gt_selector_to_ids1 = selector_breakdown1.get('ground_truth', {}).get('selector_to_ids', {})
    gt_selector_to_ids2 = selector_breakdown2.get('ground_truth', {}).get('selector_to_ids', {})
    pred_selector_to_ids1 = selector_breakdown1.get('predicted', {}).get('selector_to_ids', {})
    pred_selector_to_ids2 = selector_breakdown2.get('predicted', {}).get('selector_to_ids', {})
    
    # Combine selector IDs (union of all selectors)
    all_gt_selectors = set(gt_selector_to_ids1.keys()) | set(gt_selector_to_ids2.keys())
    all_pred_selectors = set(pred_selector_to_ids1.keys()) | set(pred_selector_to_ids2.keys())
    
    merged_gt_selector_to_ids = {}
    for sel_id in all_gt_selectors:
        ids1 = set(gt_selector_to_ids1.get(sel_id, []))
        ids2 = set(gt_selector_to_ids2.get(sel_id, []))
        merged_gt_selector_to_ids[sel_id] = sorted(list(ids1 | ids2))
    
    merged_pred_selector_to_ids = {}
    for sel_id in all_pred_selectors:
        ids1 = set(pred_selector_to_ids1.get(sel_id, []))
        ids2 = set(pred_selector_to_ids2.get(sel_id, []))
        merged_pred_selector_to_ids[sel_id] = sorted(list(ids1 | ids2))
    
    return {
        'ground_truth_file': metrics1.get('ground_truth_file', '') + ' + ' + metrics2.get('ground_truth_file', ''),
        'predicted_file': metrics1.get('predicted_file', '') + ' + ' + metrics2.get('predicted_file', ''),
        'ground_truth_metadata': {
            **gt_meta1,
            'totalElements': gt_meta1.get('totalElements', 0) + gt_meta2.get('totalElements', 0),
            'uniqueElements': merged_gt_total
        },
        'predicted_metadata': {
            **pred_meta1,
            'totalElements': pred_meta1.get('totalElements', 0) + pred_meta2.get('totalElements', 0),
            'uniqueElements': merged_pred_total
        },
        'metrics': {
            'tp_count': merged_tp_count,
            'tp_exact_count': merged_tp_exact_count,
            'tp_related_count': merged_tp_related_count,
            'fp_count': merged_fp_count,
            'fn_count': merged_fn_count,
            'precision': merged_precision,
            'recall': merged_recall,
            'f1_score': merged_f1,
            'accuracy': merged_accuracy,
            'ground_truth_total': merged_gt_total,
            'predicted_total': merged_pred_total
        },
        'signature_metrics': {
            'tp_signature_count': merged_tp_sig_count,
            'tp_exact_signature_count': merged_tp_sig_count,  # Simplified
            'tp_related_signature_count': 0,  # Simplified
            'fp_signature_count': merged_fp_sig_count,
            'fn_signature_count': merged_fn_sig_count,
            'ground_truth_signature_total': merged_gt_sig_total,
            'predicted_signature_total': merged_pred_sig_total,
            'tp_signatures': sorted(list(all_tp_sig)),
            'tp_exact_signatures': sorted(list(all_tp_sig)),  # Simplified
            'tp_related_signatures': [],
            'fp_signatures': sorted(list(all_fp_sig)),
            'fn_signatures': sorted(list(all_fn_sig)),
            'precision': merged_sig_precision,
            'recall': merged_sig_recall,
            'f1_score': merged_sig_f1,
            'accuracy': merged_sig_accuracy
        },
        'element_details': {
            'tp': merged_tp_elements,
            'fp': merged_fp_elements,
            'fn': merged_fn_elements
        },
        'element_groups': {
            'fp_by_signature': {sig: len(elems) for sig, elems in fp_grouped.items()},
            'fn_by_signature': {sig: len(elems) for sig, elems in fn_grouped.items()},
            'fp_grouped_details': {sig: [{'xpath': e['xpath'], 'preview': e.get('preview', '')} for e in elems[:3]] 
                                   for sig, elems in fp_grouped.items()},
            'fn_grouped_details': {sig: [{'xpath': e['xpath'], 'preview': e.get('preview', '')} for e in elems[:3]] 
                                   for sig, elems in fn_grouped.items()}
        },
        'selector_breakdown': {
            'ground_truth': {
                'total_selectors': max(selector_breakdown1.get('ground_truth', {}).get('total_selectors', 0),
                                      selector_breakdown2.get('ground_truth', {}).get('total_selectors', 0)),
                'selectors_with_matches': len([s for s in merged_gt_selector_to_ids.values() if s]),
                'selector_to_ids': merged_gt_selector_to_ids
            },
            'predicted': {
                'total_selectors': max(selector_breakdown1.get('predicted', {}).get('total_selectors', 0),
                                      selector_breakdown2.get('predicted', {}).get('total_selectors', 0)),
                'selectors_with_matches': len([s for s in merged_pred_selector_to_ids.values() if s]),
                'selector_to_ids': merged_pred_selector_to_ids
            }
        },
        'signature_summary': {
            # Only include signatures that are actually FP/FN after parent-child logic
            # Filter fp_grouped to only include signatures in all_fp_sig (final FP signatures)
            'fp_signatures': [
                {
                    'signature': sig,
                    'count': len(elems),
                    'description': f'{len(elems)} element{"s" if len(elems) > 1 else ""} with signature "{sig}"',
                    'examples': [
                        {
                            'xpath': e.get('xpath', ''),
                            'preview': e.get('preview', '')[:100]  # Limit preview length
                        }
                        for e in elems[:3]  # First 3 examples
                    ]
                }
                for sig, elems in sorted(
                    [(sig, elems) for sig, elems in fp_grouped.items() if sig in all_fp_sig],
                    key=lambda x: (-len(x[1]), x[0])
                )
            ],
            # Filter fn_grouped to only include signatures in all_fn_sig (final FN signatures)
            'fn_signatures': [
                {
                    'signature': sig,
                    'count': len(elems),
                    'description': f'{len(elems)} element{"s" if len(elems) > 1 else ""} with signature "{sig}"',
                    'examples': [
                        {
                            'xpath': e.get('xpath', ''),
                            'preview': e.get('preview', '')[:100]  # Limit preview length
                        }
                        for e in elems[:3]  # First 3 examples
                    ]
                }
                for sig, elems in sorted(
                    [(sig, elems) for sig, elems in fn_grouped.items() if sig in all_fn_sig],
                    key=lambda x: (-len(x[1]), x[0])
                )
            ],
            'total_fp_signatures': merged_fp_sig_count,
            'total_fn_signatures': merged_fn_sig_count,
            'total_fp_elements': merged_fp_count,
            'total_fn_elements': merged_fn_count
        }
    }


def plot_metrics(metrics: Dict, output_file: Optional[str] = None):
    """
    Plot overmasking, undermasking, and correct masking for both per-item and per-group.
    """
    # Extract metrics
    item_metrics = metrics.get('metrics', {})
    sig_metrics = metrics.get('signature_metrics', {})
    
    # Per-item (individual element level)
    item_tp = item_metrics.get('tp_count', 0)
    item_fp = item_metrics.get('fp_count', 0)
    item_fn = item_metrics.get('fn_count', 0)
    
    # Per-group (signature level)
    sig_tp = sig_metrics.get('tp_signature_count', 0)
    sig_fp = sig_metrics.get('fp_signature_count', 0)
    sig_fn = sig_metrics.get('fn_signature_count', 0)
    
    # Find max value across both plots for consistent y-axis range
    max_item = max(item_tp, item_fp, item_fn, 1)  # At least 1 to avoid division by zero
    max_sig = max(sig_tp, sig_fp, sig_fn, 1)
    max_value = max(max_item, max_sig)
    # Add 10% padding
    y_max = max_value * 1.1
    
    # Create figure with fixed size BEFORE plotting
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Per-item plot
    categories = ['Correct\nMasking\n(TP)', 'Overmasking\n(FP)', 'Undermasking\n(FN)']
    item_values = [item_tp, item_fp, item_fn]
    item_colors = ['#2ecc71', '#f39c12', '#e74c3c']  # Green, Orange, Red
    
    bars1 = ax1.bar(categories, item_values, color=item_colors, alpha=0.8, edgecolor='black', linewidth=1.5)
    ax1.set_ylabel('Number of Elements', fontsize=12, fontweight='bold')
    ax1.set_title('Per-element', fontsize=14, fontweight='bold')
    ax1.set_ylim(0, y_max)
    ax1.grid(axis='y', alpha=0.3, linestyle='--')
    
    # Add value labels on bars
    for bar, value in zip(bars1, item_values):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(value)}',
                ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    # Add metrics text
    precision = item_metrics.get('precision', 0)
    recall = item_metrics.get('recall', 0)
    f1 = item_metrics.get('f1_score', 0)
    metrics_text = f'Precision: {precision:.3f}\nRecall: {recall:.3f}\nF1: {f1:.3f}'
    ax1.text(0.98, 0.98, metrics_text, transform=ax1.transAxes,
            fontsize=10, verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Per-group plot
    sig_values = [sig_tp, sig_fp, sig_fn]
    bars2 = ax2.bar(categories, sig_values, color=item_colors, alpha=0.8, edgecolor='black', linewidth=1.5)
    ax2.set_ylabel('Number of Element Types', fontsize=12, fontweight='bold')
    ax2.set_title('Per-group (same tag and classes)', fontsize=14, fontweight='bold')
    ax2.set_ylim(0, y_max)
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    
    # Add value labels on bars
    for bar, value in zip(bars2, sig_values):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(value)}',
                ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    # Add metrics text
    sig_precision = sig_metrics.get('precision', 0)
    sig_recall = sig_metrics.get('recall', 0)
    sig_f1 = sig_metrics.get('f1_score', 0)
    sig_metrics_text = f'Precision: {sig_precision:.3f}\nRecall: {sig_recall:.3f}\nF1: {sig_f1:.3f}'
    ax2.text(0.98, 0.98, sig_metrics_text, transform=ax2.transAxes,
            fontsize=10, verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    if output_file:
        output_path = Path(output_file)
        base_name = output_path.stem
        output_dir = output_path.parent

        png_file = output_dir / f"{base_name}.png"
        plt.savefig(png_file, dpi=300, bbox_inches='tight', format='png')
        print(f"PNG saved to: {png_file}")
        
        pdf_file = output_dir / f"{base_name}.pdf"
        fig.savefig(pdf_file, format='pdf', bbox_inches='tight', pad_inches=0.05,
                   facecolor='white', edgecolor='none', dpi=300)
        print(f"PDF saved to: {pdf_file}")
    else:
        plt.show()
    
    plt.close()
    
    # Also create a separate plot for per-group only
    if output_file:
        output_path = Path(output_file)
        base_name = output_path.stem
        output_dir = output_path.parent
        
        # Create separate figure for per-group only
        fig_group = plt.figure(figsize=(7, 6))
        ax_group = fig_group.add_subplot(1, 1, 1)
        
        # Per-group plot only
        categories = ['Correct\nMasking\n(TP)', 'Overmasking\n(FP)', 'Undermasking\n(FN)']
        sig_values = [sig_tp, sig_fp, sig_fn]
        item_colors = ['#2ecc71', '#f39c12', '#e74c3c']  # Green, Orange, Red
        
        bars_group = ax_group.bar(categories, sig_values, color=item_colors, alpha=0.8, edgecolor='black', linewidth=1.5)
        ax_group.set_ylabel('Element groups', fontsize=12, fontweight='bold')
        ax_group.set_ylim(0, max_sig * 1.1)
        ax_group.grid(axis='y', alpha=0.3, linestyle='--')
        
        # Add value labels on bars
        for bar, value in zip(bars_group, sig_values):
            height = bar.get_height()
            ax_group.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(value)}',
                    ha='center', va='bottom', fontsize=11, fontweight='bold')
        
        # Add metrics text
        sig_precision = sig_metrics.get('precision', 0)
        sig_recall = sig_metrics.get('recall', 0)
        sig_f1 = sig_metrics.get('f1_score', 0)
        sig_metrics_text = f'Precision: {sig_precision:.3f}\nRecall: {sig_recall:.3f}\nF1: {sig_f1:.3f}'
        ax_group.text(0.98, 0.98, sig_metrics_text, transform=ax_group.transAxes,
                fontsize=10, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        plt.tight_layout()
        
        # Save per-group only PNG
        png_group_file = output_dir / f"{base_name}_group.png"
        fig_group.savefig(png_group_file, dpi=300, bbox_inches='tight', format='png')
        print(f"Per-group PNG saved to: {png_group_file}")
        
        # Save per-group only PDF
        pdf_group_file = output_dir / f"{base_name}_group.pdf"
        fig_group.savefig(pdf_group_file, format='pdf', bbox_inches='tight', pad_inches=0.05,
                         facecolor='white', edgecolor='none', dpi=300)
        print(f"Per-group PDF saved to: {pdf_group_file}")
        
        plt.close(fig_group)


def main():
    parser = argparse.ArgumentParser(
        description='Plot comparison metrics showing overmasking, undermasking, and correct masking',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('files', nargs='+', help='One or more comparison metrics JSON files')
    parser.add_argument('--output', '-o', help='Output plot file (default: show plot)')
    parser.add_argument('--merged-output', help='Save merged metrics JSON to this file (only when merging multiple files)')

    args = parser.parse_args()

    # Load all files
    all_metrics = []
    for f in args.files:
        if not Path(f).exists():
            print(f"Error: File not found: {f}", file=sys.stderr)
            sys.exit(1)
        all_metrics.append(load_comparison_metrics(f))

    if len(all_metrics) == 1:
        # Single file - just plot
        plot_metrics(all_metrics[0], args.output)
    else:
        # Merge all files pairwise
        merged = all_metrics[0]
        for i in range(1, len(all_metrics)):
            merged = merge_metrics(merged, all_metrics[i])

        # Save merged metrics if requested
        if args.merged_output:
            with open(args.merged_output, 'w') as f:
                json.dump(merged, f, indent=2)
            print(f"Merged metrics saved to: {args.merged_output}")

        # Plot merged metrics
        if args.output:
            print(f"\nGenerating merged plot")
            plot_metrics(merged, args.output)
        else:
            plot_metrics(merged, args.output)


if __name__ == '__main__':
    import sys
    main()
