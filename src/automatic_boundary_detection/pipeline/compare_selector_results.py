#!/usr/bin/env python3
"""
Compare two selector analysis results and calculate TP, FP, FN rates.

Each element (identified by XPath ID) is counted only once, regardless of how many selectors match it. What matters is whether the element is hit or not.

Usage:
    python ../shared/compare_selector_results.py <ground_truth.json> <predicted.json> [--output output.json]

Example:
    python pipeline/compare_selector_results.py hand_results.json llm_results.json --output comparison.json
"""

import json
import re
import sys
import argparse
from pathlib import Path
from typing import Set, Dict, List


def extract_all_element_ids(results_file: str) -> Dict:
    """
    Extract all unique element IDs from a results JSON file.
    Returns a dict with:
    - element_ids: set of all unique XPath IDs
    - selector_to_ids: mapping of selector index -> set of element IDs
    - id_to_preview: mapping of XPath ID -> preview text (first one found)
    - id_to_selectors: mapping of XPath ID -> list of selector strings that match it
    - id_to_element_info: mapping of XPath ID -> element characteristics (tagName, className, id)
    - metadata: summary info from the file
    """
    with open(results_file, 'r') as f:
        data = json.load(f)
    
    all_element_ids = set()
    selector_to_ids = {}
    id_to_preview = {}  # XPath -> preview text
    id_to_selectors = {}  # XPath -> list of selector strings
    id_to_element_info = {}  # XPath -> element characteristics (tagName, className, id)
    
    results = data.get('results', [])
    summary = data.get('summary', {})
    
    for result in results:
        idx = result.get('index')
        selector = result.get('selector', '')
        element_ids = result.get('element_ids', [])
        previews = result.get('previews', [])
        element_info = result.get('element_info', {})  # New: element characteristics by XPath
        
        # Filter out None/empty IDs
        valid_ids = {eid for eid in element_ids if eid}
        
        all_element_ids.update(valid_ids)
        selector_to_ids[idx] = valid_ids
        
        # Map element IDs to selectors, previews, and element info
        for i, eid in enumerate(element_ids):
            if eid:
                # Track which selectors match this element
                if eid not in id_to_selectors:
                    id_to_selectors[eid] = []
                if selector and selector not in id_to_selectors[eid]:
                    id_to_selectors[eid].append(selector)
                
                # Map element IDs to previews (previews index corresponds to element_ids index)
                if eid not in id_to_preview:  # Only store first preview found
                    if i < len(previews):
                        preview_text = previews[i].get('text_preview', '')
                        if preview_text:
                            id_to_preview[eid] = preview_text
                
                # Store element characteristics (tagName, className, id)
                if eid in element_info:
                    id_to_element_info[eid] = element_info[eid]
                elif eid not in id_to_element_info:
                    # Fallback: try to extract from XPath or use empty values
                    id_to_element_info[eid] = {
                        'tagName': '',
                        'className': '',
                        'id': '',
                        'textPreview': id_to_preview.get(eid, '')
                    }
    
    return {
        'element_ids': all_element_ids,
        'selector_to_ids': selector_to_ids,
        'id_to_preview': id_to_preview,
        'id_to_selectors': id_to_selectors,
        'id_to_element_info': id_to_element_info,
        'metadata': summary,
        'total_selectors': len(results),
        'selectors_with_matches': sum(1 for r in results if r.get('count', 0) > 0)
    }


def get_element_signature(element_info: Dict) -> str:
    """
    Create a signature string from element characteristics (tagName, className, id).
    This signature groups elements that have the same HTML characteristics.
    
    Example signatures:
    - "span.badge-category__name" (tagName + className)
    - "a#user-link" (tagName + id)
    - "div.post" (tagName + className)
    """
    tag = element_info.get('tagName', '').lower()
    raw_classes = element_info.get('className', '')
    # className can be a dict for SVG elements (SVGAnimatedString: {baseVal, animVal})
    if isinstance(raw_classes, dict):
        raw_classes = raw_classes.get('baseVal', '')
    if not isinstance(raw_classes, str):
        raw_classes = str(raw_classes) if raw_classes else ''
    classes = raw_classes.strip()
    raw_id = element_info.get('id', '')
    if not isinstance(raw_id, str):
        raw_id = str(raw_id) if raw_id else ''
    elem_id = raw_id.strip()
    
    # Build signature: tagName.className (no id — ids can be dynamic)
    parts = []
    if tag:
        parts.append(tag)

    # Add all classes (sorted for consistent signatures)
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


def is_ancestor(ancestor_xpath: str, descendant_xpath: str) -> bool:
    """
    Check if ancestor_xpath is an ancestor (parent/grandparent/etc) of descendant_xpath.
    XPath format: //*[@id="..."]/tag[1]/tag[2]/...
    
    Examples:
    - //div[1] is ancestor of //div[1]/a[1]
    - //*[@id="ember105"]/a[1] is ancestor of //*[@id="ember105"]/a[1]/img[1]
    """
    ancestor = ancestor_xpath.strip()
    descendant = descendant_xpath.strip()
    
    # If they're the same, not ancestor-descendant
    if ancestor == descendant:
        return False
    
    # Check if descendant starts with ancestor followed by '/'
    # This means ancestor is a parent path of descendant
    if descendant.startswith(ancestor + '/'):
        return True
    
    return False


def calculate_metrics(ground_truth_ids: Set[str], predicted_ids: Set[str]) -> Dict:
    """
    Calculate TP, FP, FN, and derived metrics.
    
    - TP (True Positive): Elements found by both ground truth and predicted, OR elements where one is an ancestor/descendant of the other (covers same content, just different nesting level)
    - FP (False Positive): Elements found by predicted but not in ground truth and not related
    - FN (False Negative): Elements found by ground truth but not in predicted and not related
    """
    # First, find exact matches
    exact_tp = ground_truth_ids & predicted_ids
    
    # Remaining elements after exact matches
    remaining_gt = ground_truth_ids - exact_tp
    remaining_pred = predicted_ids - exact_tp
    
    # Find parent-child relationships
    # Strategy: If one element is an ancestor/descendant of another, they cover the same content
    # We need to handle cases where:
    # 1. GT has parent, predicted has child (or vice versa) → both are TP
    # 2. GT has both parent and child, predicted has only parent → child is TP (covered by parent)
    # 3. GT has only parent, predicted has both parent and child → child is TP (covered by parent)
    
    related_tp = set()
    fp_to_remove = set()
    fn_to_remove = set()
    
    # Check relationships between remaining elements
    for gt_xpath in list(remaining_gt):
        for pred_xpath in list(remaining_pred):
            if is_ancestor(gt_xpath, pred_xpath):
                # GT is parent, predicted is child - same content, count as TP
                related_tp.add(gt_xpath)
                related_tp.add(pred_xpath)
                fp_to_remove.add(pred_xpath)
                fn_to_remove.add(gt_xpath)
            elif is_ancestor(pred_xpath, gt_xpath):
                # Predicted is parent, GT is child - same content, count as TP
                related_tp.add(gt_xpath)
                related_tp.add(pred_xpath)
                fp_to_remove.add(pred_xpath)
                fn_to_remove.add(gt_xpath)
    
    # Iteratively find all parent-child relationships
    # We need multiple passes because discovering one relationship can reveal others
    changed = True
    while changed:
        changed = False
        
        # Pass 1: Check if GT children are covered by any matched parent (exact or related)
        for gt_xpath in list(remaining_gt - fn_to_remove):
            for matched_xpath in exact_tp | related_tp:
                if is_ancestor(matched_xpath, gt_xpath):
                    # GT child is covered by matched parent → count as TP
                    if gt_xpath not in related_tp:
                        related_tp.add(gt_xpath)
                        fn_to_remove.add(gt_xpath)
                        changed = True
                    break
        
        # Pass 2: Check if predicted children are covered by any matched parent (exact or related)
        for pred_xpath in list(remaining_pred - fp_to_remove):
            for matched_xpath in exact_tp | related_tp:
                if is_ancestor(matched_xpath, pred_xpath):
                    # Predicted child is covered by matched parent → count as TP
                    if pred_xpath not in related_tp:
                        related_tp.add(pred_xpath)
                        fp_to_remove.add(pred_xpath)
                        changed = True
                    break
        
        # Pass 3: Check if GT has both parent and child, and parent is matched
        # If GT has both parent and child, and parent is in predicted (exact or related),
        # then child should also be TP (covered by parent)
        for gt_child in list(remaining_gt - fn_to_remove):
            for gt_parent in exact_tp | related_tp | (remaining_gt - fn_to_remove):
                if gt_child != gt_parent and is_ancestor(gt_parent, gt_child):
                    # GT has both parent and child
                    # Check if parent is matched (in exact_tp or related_tp)
                    if gt_parent in exact_tp or gt_parent in related_tp:
                        # Parent is matched, so child is also effectively matched → TP
                        if gt_child not in related_tp:
                            related_tp.add(gt_child)
                            fn_to_remove.add(gt_child)
                            changed = True
                        break
        
        # Pass 4: Check if predicted has both parent and child, and parent is matched
        for pred_child in list(remaining_pred - fp_to_remove):
            for pred_parent in exact_tp | related_tp | (remaining_pred - fp_to_remove):
                if pred_child != pred_parent and is_ancestor(pred_parent, pred_child):
                    # Predicted has both parent and child
                    # Check if parent is matched (in exact_tp or related_tp)
                    if pred_parent in exact_tp or pred_parent in related_tp:
                        # Parent is matched, so child is also effectively matched → TP
                        if pred_child not in related_tp:
                            related_tp.add(pred_child)
                            fp_to_remove.add(pred_child)
                            changed = True
                        break
        
        # Pass 5: Check if GT parents are covered by matched children
        # If GT has both parent and child, and child is matched, parent should also be TP
        for gt_parent in list(remaining_gt - fn_to_remove):
            for gt_child in exact_tp | related_tp | (remaining_gt - fn_to_remove):
                if gt_parent != gt_child and is_ancestor(gt_parent, gt_child):
                    # GT has both parent and child
                    # Check if child is matched (in exact_tp or related_tp)
                    if gt_child in exact_tp or gt_child in related_tp:
                        # Child is matched, so parent also effectively covers it → TP
                        if gt_parent not in related_tp:
                            related_tp.add(gt_parent)
                            fn_to_remove.add(gt_parent)
                            changed = True
                        break
        
        # Pass 6: Check if predicted parents are covered by matched children
        for pred_parent in list(remaining_pred - fp_to_remove):
            for pred_child in exact_tp | related_tp | (remaining_pred - fp_to_remove):
                if pred_parent != pred_child and is_ancestor(pred_parent, pred_child):
                    # Predicted has both parent and child
                    # Check if child is matched (in exact_tp or related_tp)
                    if pred_child in exact_tp or pred_child in related_tp:
                        # Child is matched, so parent also effectively covers it → TP
                        if pred_parent not in related_tp:
                            related_tp.add(pred_parent)
                            fp_to_remove.add(pred_parent)
                            changed = True
                        break
    
    # Combine exact and related matches
    tp = exact_tp | related_tp
    
    # FP and FN exclude related elements
    fp = remaining_pred - fp_to_remove
    fn = remaining_gt - fn_to_remove
    
    tp_count = len(tp)
    fp_count = len(fp)
    fn_count = len(fn)
    
    # Calculate precision, recall, F1
    precision = tp_count / (tp_count + fp_count) if (tp_count + fp_count) > 0 else 0.0
    recall = tp_count / (tp_count + fn_count) if (tp_count + fn_count) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # Correct / (correct + incorrect)
    total_identified = tp_count + fp_count + fn_count
    accuracy = tp_count / total_identified if total_identified > 0 else 0.0
    
    # Separate exact TP from related TP for reporting
    exact_tp_list = sorted(list(exact_tp))
    related_tp_list = sorted(list(related_tp - exact_tp))
    
    return {
        'tp': sorted(list(tp)),
        'tp_exact': exact_tp_list,
        'tp_related': related_tp_list,  # Parent-child relationships
        'fp': sorted(list(fp)),
        'fn': sorted(list(fn)),
        'tp_count': tp_count,
        'tp_exact_count': len(exact_tp),
        'tp_related_count': len(related_tp - exact_tp),
        'fp_count': fp_count,
        'fn_count': fn_count,
        'precision': precision,
        'recall': recall,
        'f1_score': f1,
        'accuracy': accuracy,
        'ground_truth_total': len(ground_truth_ids),
        'predicted_total': len(predicted_ids)
    }


def apply_exclusions(element_ids: Set[str], data: Dict, rules: list, label: str) -> Set[str]:
    """
    Remove elements that match exclusion rules.

    Each rule can have:
      - text_equals: exact text match
      - text_regex: regex match on text preview
      - selector_contains: one of the element's selectors contains this substring
    All specified conditions must match (AND logic).
    """
    if not rules:
        return element_ids

    id_to_preview = data['id_to_preview']
    id_to_selectors = data['id_to_selectors']

    excluded = set()
    for xpath in element_ids:
        preview = id_to_preview.get(xpath, '')
        selectors = id_to_selectors.get(xpath, [])
        selectors_str = ' '.join(selectors)

        for rule in rules:
            match = True

            if 'text_equals' in rule:
                if preview != rule['text_equals']:
                    match = False

            if 'text_regex' in rule and match:
                if not re.search(rule['text_regex'], preview):
                    match = False

            if 'selector_contains' in rule and match:
                if rule['selector_contains'] not in selectors_str:
                    match = False

            if match:
                excluded.add(xpath)
                break

    if excluded:
        print(f"  Per-page {label} exclusions: removed {len(excluded)} elements")
        for xpath in sorted(excluded):
            preview = id_to_preview.get(xpath, '')
            print(f"    - \"{preview}\" ({xpath})")

    return element_ids - excluded


def _load_exclusion_rules(gt_exclude_file: str, page: str | None):
    """
    Resolve per-page exclusion rules. The file is expected to be a JSON dict.

    Lookup order:
      1. If ``page`` is provided AND the file has ``page_exclusions[page]``,
         use that nested block (this is how the gitlab hand config carries exclusions inline alongside its selectors).
      2. Otherwise fall back to top-level ``exclude_from_ground_truth`` /
         ``exclude_from_predicted`` keys (legacy standalone patch file).

    Returns (gt_rules, pred_rules).
    """
    if not (gt_exclude_file and Path(gt_exclude_file).exists()):
        return [], []
    with open(gt_exclude_file, 'r') as f:
        cfg = json.load(f)
    if page and isinstance(cfg.get('page_exclusions'), dict) and page in cfg['page_exclusions']:
        block = cfg['page_exclusions'][page]
        return block.get('exclude_from_ground_truth', []), block.get('exclude_from_predicted', [])
    return cfg.get('exclude_from_ground_truth', []), cfg.get('exclude_from_predicted', [])


def compare_results(ground_truth_file: str, predicted_file: str, output_file: str = None,
                    gt_exclude_file: str = None, page: str = None):
    """
    Compare two selector analysis results and calculate metrics.
    """
    print("="*60)
    print("COMPARING SELECTOR RESULTS")
    print("="*60)
    print(f"Ground Truth: {ground_truth_file}")
    print(f"Predicted:    {predicted_file}\n")

    gt_rules, pred_rules = _load_exclusion_rules(gt_exclude_file, page)

    # Extract element IDs from both files
    print("Extracting element IDs from ground truth...")
    gt_data = extract_all_element_ids(ground_truth_file)
    gt_ids = gt_data['element_ids']
    print(f"  Found {len(gt_ids)} unique elements across {gt_data['selectors_with_matches']} selectors")

    if gt_rules:
        gt_ids = apply_exclusions(gt_ids, gt_data, gt_rules, "GT")
        print(f"  After exclusions: {len(gt_ids)} ground truth elements")

    print("\nExtracting element IDs from predicted...")
    pred_data = extract_all_element_ids(predicted_file)
    pred_ids = pred_data['element_ids']
    print(f"  Found {len(pred_ids)} unique elements across {pred_data['selectors_with_matches']} selectors")

    if pred_rules:
        pred_ids = apply_exclusions(pred_ids, pred_data, pred_rules, "predicted")
        print(f"  After exclusions: {len(pred_ids)} predicted elements")

    # Get element info for signature calculation (needed before metrics)
    gt_element_info = gt_data.get('id_to_element_info', {})
    pred_element_info = pred_data.get('id_to_element_info', {})
    
    # Calculate metrics (individual element level)
    print("\nCalculating metrics (individual element level)...")
    metrics = calculate_metrics(gt_ids, pred_ids)
    
    # Calculate metrics by element signature (treating same tag+class+id = 1)
    # Only considers signatures from elements that were matched (TP, FP, or FN)
    # Applies parent-child logic: if elements with different signatures are parent-child, count as TP
    print("Calculating metrics by element type (grouped by signature, with parent-child logic)...")
    
    # Get signatures from matched elements only (TP, FP, FN)
    # TP elements: already matched, their signatures are TP
    tp_element_signatures = set()
    for xpath in metrics['tp']:
        element_info = gt_element_info.get(xpath) or pred_element_info.get(xpath, {})
        signature = get_element_signature(element_info)
        if signature:
            tp_element_signatures.add(signature)
    
    # FP elements: in predicted but not in ground truth
    fp_element_signatures = {}  # signature -> set of xpaths with that signature
    for xpath in metrics['fp']:
        element_info = pred_element_info.get(xpath, {})
        signature = get_element_signature(element_info)
        if signature:
            if signature not in fp_element_signatures:
                fp_element_signatures[signature] = set()
            fp_element_signatures[signature].add(xpath)
    
    # FN elements: in ground truth but not in predicted
    fn_element_signatures = {}  # signature -> set of xpaths with that signature
    for xpath in metrics['fn']:
        element_info = gt_element_info.get(xpath, {})
        signature = get_element_signature(element_info)
        if signature:
            if signature not in fn_element_signatures:
                fn_element_signatures[signature] = set()
            fn_element_signatures[signature].add(xpath)
    
    # Apply parent-child logic to signatures
    # If an FP element (by XPath) is parent/child of an FN element, their signatures count as TP
    related_signature_tp = set()
    fp_signatures_to_remove = set()
    fn_signatures_to_remove = set()
    
    # Check FP elements against FN elements for parent-child relationships
    for fp_sig, fp_xpaths in fp_element_signatures.items():
        for fp_xpath in fp_xpaths:
            for fn_sig, fn_xpaths in fn_element_signatures.items():
                for fn_xpath in fn_xpaths:
                    # Check if FP element is ancestor/descendant of FN element
                    if is_ancestor(fp_xpath, fn_xpath) or is_ancestor(fn_xpath, fp_xpath):
                        # These signatures are related (parent-child relationship)
                        related_signature_tp.add(fp_sig)
                        related_signature_tp.add(fn_sig)
                        fp_signatures_to_remove.add(fp_sig)
                        fn_signatures_to_remove.add(fn_sig)
                        break
                if fp_sig in related_signature_tp:
                    break
            if fp_sig in related_signature_tp:
                break
    
    # Combine exact TP signatures with related TP signatures
    tp_signatures = tp_element_signatures | related_signature_tp
    
    # FP signatures: FP signatures not in TP and not related
    fp_signatures = set(fp_element_signatures.keys()) - tp_signatures
    
    # FN signatures: FN signatures not in TP and not related
    fn_signatures = set(fn_element_signatures.keys()) - tp_signatures
    
    # Count exact vs related TP signatures
    tp_exact_signatures = tp_element_signatures - related_signature_tp
    tp_related_signatures = related_signature_tp
    
    signature_metrics = {
        'tp_signature_count': len(tp_signatures),
        'tp_exact_signature_count': len(tp_exact_signatures),
        'tp_related_signature_count': len(tp_related_signatures),
        'fp_signature_count': len(fp_signatures),
        'fn_signature_count': len(fn_signatures),
        'ground_truth_signature_total': len(tp_element_signatures | set(fn_element_signatures.keys())),
        'predicted_signature_total': len(tp_element_signatures | set(fp_element_signatures.keys())),
        'tp_signatures': sorted(list(tp_signatures)),
        'tp_exact_signatures': sorted(list(tp_exact_signatures)),
        'tp_related_signatures': sorted(list(tp_related_signatures)),
        'fp_signatures': sorted(list(fp_signatures)),
        'fn_signatures': sorted(list(fn_signatures))
    }
    
    # Calculate precision, recall, F1 for signatures
    sig_tp = signature_metrics['tp_signature_count']
    sig_fp = signature_metrics['fp_signature_count']
    sig_fn = signature_metrics['fn_signature_count']
    
    signature_metrics['precision'] = sig_tp / (sig_tp + sig_fp) if (sig_tp + sig_fp) > 0 else 0.0
    signature_metrics['recall'] = sig_tp / (sig_tp + sig_fn) if (sig_tp + sig_fn) > 0 else 0.0
    signature_metrics['f1_score'] = 2 * (signature_metrics['precision'] * signature_metrics['recall']) / (signature_metrics['precision'] + signature_metrics['recall']) if (signature_metrics['precision'] + signature_metrics['recall']) > 0 else 0.0
    signature_metrics['accuracy'] = sig_tp / (sig_tp + sig_fp + sig_fn) if (sig_tp + sig_fp + sig_fn) > 0 else 0.0
    
    # Build element details with previews and selectors
    gt_previews = gt_data['id_to_preview']
    pred_previews = pred_data['id_to_preview']
    gt_selectors = gt_data['id_to_selectors']
    pred_selectors = pred_data['id_to_selectors']
    
    # Create detailed element lists with previews and selectors
    tp_elements = []
    for xpath in sorted(metrics['tp']):
        # Prefer preview from ground truth, fallback to predicted
        preview = gt_previews.get(xpath) or pred_previews.get(xpath) or ''
        # Get selectors from both (combine and deduplicate)
        gt_sel = gt_selectors.get(xpath, [])
        pred_sel = pred_selectors.get(xpath, [])
        all_selectors = sorted(list(set(gt_sel + pred_sel)))
        # Get element info (prefer GT, fallback to predicted)
        element_info = gt_element_info.get(xpath) or pred_element_info.get(xpath) or {}
        tp_elements.append({
            'xpath': xpath,
            'preview': preview,
            'selectors': all_selectors,
            'ground_truth_selectors': gt_sel,
            'predicted_selectors': pred_sel,
            'tagName': element_info.get('tagName', ''),
            'className': element_info.get('className', ''),
            'id': element_info.get('id', '')
        })
    
    fp_elements = []
    for xpath in sorted(metrics['fp']):
        preview = pred_previews.get(xpath) or ''
        selectors = pred_selectors.get(xpath, [])
        element_info = pred_element_info.get(xpath, {})
        fp_elements.append({
            'xpath': xpath,
            'preview': preview,
            'selectors': selectors,
            'tagName': element_info.get('tagName', ''),
            'className': element_info.get('className', ''),
            'id': element_info.get('id', '')
        })
    
    fn_elements = []
    for xpath in sorted(metrics['fn']):
        preview = gt_previews.get(xpath) or ''
        selectors = gt_selectors.get(xpath, [])
        element_info = gt_element_info.get(xpath, {})
        fn_elements.append({
            'xpath': xpath,
            'preview': preview,
            'selectors': selectors,
            'tagName': element_info.get('tagName', ''),
            'className': element_info.get('className', ''),
            'id': element_info.get('id', '')
        })
    
    # Group FP and FN by element characteristics signature
    # Only group elements whose signatures are actually FP/FN after parent-child logic
    # Filter fp_elements to only include those with signatures that are in fp_signatures
    final_fp_elements = []
    for elem in fp_elements:
        xpath = elem.get('xpath', '')
        element_info = pred_element_info.get(xpath, {})
        signature = get_element_signature(element_info)
        if signature and signature in fp_signatures:
            final_fp_elements.append(elem)
    
    final_fn_elements = []
    for elem in fn_elements:
        xpath = elem.get('xpath', '')
        element_info = gt_element_info.get(xpath, {})
        signature = get_element_signature(element_info)
        if signature and signature in fn_signatures:
            final_fn_elements.append(elem)
    
    fp_grouped = group_elements_by_signature(final_fp_elements, pred_element_info)
    fn_grouped = group_elements_by_signature(final_fn_elements, gt_element_info)
    
    # Print results
    print("\n" + "="*60)
    print("METRICS - Individual Element Level")
    print("="*60)
    print(f"True Positives (TP):  {metrics['tp_count']:4d}  (elements found by both or parent-child)")
    if metrics.get('tp_related_count', 0) > 0:
        print(f"  - Exact matches:     {metrics.get('tp_exact_count', metrics['tp_count']):4d}")
        print(f"  - Parent-child:      {metrics.get('tp_related_count', 0):4d}  (same content, different nesting)")
    print(f"False Positives (FP): {metrics['fp_count']:4d}  (elements found by predicted but not in ground truth)")
    print(f"False Negatives (FN): {metrics['fn_count']:4d}  (elements found by ground truth but not in predicted)")
    print()
    print(f"Precision:  {metrics['precision']:.4f}  (TP / (TP + FP))")
    print(f"Recall:     {metrics['recall']:.4f}  (TP / (TP + FN))")
    print(f"F1 Score:   {metrics['f1_score']:.4f}")
    print(f"Accuracy:   {metrics['accuracy']:.4f}  (TP / (TP + FP + FN))")
    print("="*60)
    
    # Print signature-level metrics
    print("\n" + "="*60)
    print("METRICS - Element Type Level (same tag+class+id = 1, only matched elements, with parent-child logic)")
    print("="*60)
    print(f"True Positives (TP):  {signature_metrics['tp_signature_count']:4d}  (element types found by both or parent-child)")
    if signature_metrics.get('tp_related_signature_count', 0) > 0:
        print(f"  - Exact matches:     {signature_metrics.get('tp_exact_signature_count', signature_metrics['tp_signature_count']):4d}")
        print(f"  - Parent-child:      {signature_metrics.get('tp_related_signature_count', 0):4d}  (related elements with different signatures)")
    print(f"False Positives (FP): {signature_metrics['fp_signature_count']:4d}  (element types found by predicted but not in ground truth)")
    print(f"False Negatives (FN): {signature_metrics['fn_signature_count']:4d}  (element types found by ground truth but not in predicted)")
    print()
    print(f"Ground Truth Element Types: {signature_metrics['ground_truth_signature_total']}  (from matched elements only)")
    print(f"Predicted Element Types:     {signature_metrics['predicted_signature_total']}  (from matched elements only)")
    print()
    print(f"Precision:  {signature_metrics['precision']:.4f}  (TP / (TP + FP))")
    print(f"Recall:     {signature_metrics['recall']:.4f}  (TP / (TP + FN))")
    print(f"F1 Score:   {signature_metrics['f1_score']:.4f}")
    print(f"Accuracy:   {signature_metrics['accuracy']:.4f}  (TP / (TP + FP + FN))")
    print("="*60)
    
    # Show signature-level FP/FN
    if signature_metrics['fp_signature_count'] > 0:
        print(f"\nFalse Positive Element Types ({signature_metrics['fp_signature_count']}):")
        for sig in signature_metrics['fp_signatures'][:10]:
            print(f"  - {sig}")
        if len(signature_metrics['fp_signatures']) > 10:
            print(f"  ... and {len(signature_metrics['fp_signatures']) - 10} more")
    
    if signature_metrics['fn_signature_count'] > 0:
        print(f"\nFalse Negative Element Types ({signature_metrics['fn_signature_count']}):")
        for sig in signature_metrics['fn_signatures'][:10]:
            print(f"  - {sig}")
        if len(signature_metrics['fn_signatures']) > 10:
            print(f"  ... and {len(signature_metrics['fn_signatures']) - 10} more")
    
    # Show FP grouped by element characteristics (summary)
    if metrics['fp_count'] > 0:
        print(f"\nFalse Positives - Grouped by Element Type ({metrics['fp_count']} total, {len(fp_grouped)} unique element types):")
        # Sort by count (most common first)
        fp_sorted = sorted(fp_grouped.items(), key=lambda x: len(x[1]), reverse=True)
        for signature, elements in fp_sorted[:10]:  # Show top 10 groups
            count = len(elements)
            first_elem = elements[0]
            preview_str = f" - \"{first_elem['preview'][:50]}\"" if first_elem.get('preview') else ""
            selectors_str = f" [selectors: {', '.join(first_elem['selectors'][:2])}]" if first_elem.get('selectors') else ""
            if len(first_elem.get('selectors', [])) > 2:
                selectors_str += f" (+{len(first_elem['selectors']) - 2} more)"
            print(f"  [{count:3d}x] {signature}{preview_str}{selectors_str}")
        if len(fp_sorted) > 10:
            print(f"  ... and {len(fp_sorted) - 10} more element types")
    
    # Show FN grouped by element characteristics (summary)
    if metrics['fn_count'] > 0:
        print(f"\nFalse Negatives - Grouped by Element Type ({metrics['fn_count']} total, {len(fn_grouped)} unique element types):")
        # Sort by count (most common first)
        fn_sorted = sorted(fn_grouped.items(), key=lambda x: len(x[1]), reverse=True)
        for signature, elements in fn_sorted[:10]:  # Show top 10 groups
            count = len(elements)
            first_elem = elements[0]
            preview_str = f" - \"{first_elem['preview'][:50]}\"" if first_elem.get('preview') else ""
            selectors_str = f" [selectors: {', '.join(first_elem['selectors'][:2])}]" if first_elem.get('selectors') else ""
            if len(first_elem.get('selectors', [])) > 2:
                selectors_str += f" (+{len(first_elem['selectors']) - 2} more)"
            print(f"  [{count:3d}x] {signature}{preview_str}{selectors_str}")
        if len(fn_sorted) > 10:
            print(f"  ... and {len(fn_sorted) - 10} more element types")
    
    # Show individual elements (detailed listing)
    if metrics['fp_count'] > 0:
        print(f"\nFalse Positives - Individual Elements (first 10 of {metrics['fp_count']}):")
        for i, elem in enumerate(fp_elements[:10], 1):
            preview_str = f" - \"{elem['preview'][:60]}\"" if elem['preview'] else ""
            selectors_str = f" [selectors: {', '.join(elem['selectors'][:3])}]" if elem['selectors'] else ""
            if len(elem['selectors']) > 3:
                selectors_str += f" (+{len(elem['selectors']) - 3} more)"
            print(f"  [{i}] {elem['xpath']}{preview_str}{selectors_str}")
        if len(fp_elements) > 10:
            print(f"  ... and {len(fp_elements) - 10} more")
    
    if metrics['fn_count'] > 0:
        print(f"\nFalse Negatives - Individual Elements (first 10 of {metrics['fn_count']}):")
        for i, elem in enumerate(fn_elements[:10], 1):
            preview_str = f" - \"{elem['preview'][:60]}\"" if elem['preview'] else ""
            selectors_str = f" [selectors: {', '.join(elem['selectors'][:3])}]" if elem['selectors'] else ""
            if len(elem['selectors']) > 3:
                selectors_str += f" (+{len(elem['selectors']) - 3} more)"
            print(f"  [{i}] {elem['xpath']}{preview_str}{selectors_str}")
        if len(fn_elements) > 10:
            print(f"  ... and {len(fn_elements) - 10} more")
    
    # Create output data
    output_data = {
        'ground_truth_file': ground_truth_file,
        'predicted_file': predicted_file,
        'ground_truth_metadata': gt_data['metadata'],
        'predicted_metadata': pred_data['metadata'],
        'metrics': {
            'tp_count': metrics['tp_count'],
            'tp_exact_count': metrics.get('tp_exact_count', metrics['tp_count']),
            'tp_related_count': metrics.get('tp_related_count', 0),
            'fp_count': metrics['fp_count'],
            'fn_count': metrics['fn_count'],
            'precision': metrics['precision'],
            'recall': metrics['recall'],
            'f1_score': metrics['f1_score'],
            'accuracy': metrics['accuracy'],
            'ground_truth_total': metrics['ground_truth_total'],
            'predicted_total': metrics['predicted_total']
        },
        'signature_metrics': signature_metrics,
        'element_details': {
            'tp': tp_elements,
            'fp': fp_elements,
            'fn': fn_elements
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
                'total_selectors': gt_data['total_selectors'],
                'selectors_with_matches': gt_data['selectors_with_matches'],
                'selector_to_ids': {str(k): list(v) for k, v in gt_data['selector_to_ids'].items()}
            },
            'predicted': {
                'total_selectors': pred_data['total_selectors'],
                'selectors_with_matches': pred_data['selectors_with_matches'],
                'selector_to_ids': {str(k): list(v) for k, v in pred_data['selector_to_ids'].items()}
            }
        }
    }
    
    # Save to file if requested
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\n\nResults saved to: {output_file}\n")
    
    return output_data


def main():
    parser = argparse.ArgumentParser(
        description='Compare two selector analysis results and calculate TP, FP, FN rates',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('ground_truth', help='Path to ground truth results JSON file')
    parser.add_argument('predicted', help='Path to predicted results JSON file')
    parser.add_argument('--output', '-o', help='Output JSON file (default: print to stdout)')
    parser.add_argument('--gt-exclude',
                        help='Exclusion JSON. Either a standalone patch (top-level '
                             'exclude_from_ground_truth/exclude_from_predicted keys) or a hand '
                             'config carrying a page_exclusions block (combine with --page).')
    parser.add_argument('--page',
                        help='Page name (e.g. project, issue, user). When supplied alongside '
                             '--gt-exclude, exclusions are read from config[page_exclusions][page].')

    args = parser.parse_args()

    if not Path(args.ground_truth).exists():
        print(f"Error: Ground truth file not found: {args.ground_truth}", file=sys.stderr)
        sys.exit(1)

    if not Path(args.predicted).exists():
        print(f"Error: Predicted file not found: {args.predicted}", file=sys.stderr)
        sys.exit(1)

    compare_results(args.ground_truth, args.predicted, args.output,
                    gt_exclude_file=args.gt_exclude, page=args.page)


if __name__ == '__main__':
    main()
