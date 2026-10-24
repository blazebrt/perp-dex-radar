"""Outcome-independent A6 matching and complete-cohort price contrasts."""
import copy
import math
from tools.v9 import control_cohort as C


def require(ok,message):
    if not ok:raise ValueError(message)


def observed(outcome):
    require(outcome['net_R'] is None and outcome['funding_path_known'] is False and
            outcome['promotion_authority'] is False and outcome['full_matched_authority'] is False,
            'unsupported funding/authority')
    value=outcome['price_after_cost_R']
    known=outcome['status']=='PRICE_OBSERVED_FUNDING_UNKNOWN'
    require(outcome['price_path_known'] is known,'price status mismatch')
    require((C.number(value) if known else value is None),'price value/status mismatch')
    return known


def match(signal,candidates,execute):
    """execute(asset, decision, direction, geometry, eligible) must use bound sources.

    Fix the entire selection before any outcome call. Always attempt the candidate;
    retain sparse control outcomes without manufacturing a paired contrast.
    """
    feature=signal['features']
    require(all(feature[k]==signal[k] for k in ('asset','decision_time','direction')) and
            feature['eligible'] is signal['original_eligible'],'signal feature mismatch')
    require(type(signal['source_ordinal']) is int and signal['source_ordinal']>=0,'invalid signal ordinal')
    cohort=C.select(signal['trial_id'],feature,candidates)
    def attempt(asset,eligible):
        outcome=execute(asset,signal['decision_time'],signal['direction'],copy.deepcopy(signal['geometry']),eligible)
        require(outcome['decision_time']==signal['decision_time'] and outcome['entry_time']==signal['decision_time']
                and outcome['direction']==signal['direction'] and outcome['geometry']==signal['geometry'],
                'execution geometry/timing mismatch')
        observed(outcome)
        return outcome
    candidate=attempt(signal['asset'],signal['original_eligible'])
    controls=[dict(asset=row['asset'],outcome=attempt(row['asset'],True)) for row in cohort['controls']]
    paired=cohort['status']=='DIAGNOSTIC_COHORT_50'
    resolved=paired and observed(candidate) and all(observed(row['outcome']) for row in controls)
    control_mean=math.fsum(row['outcome']['price_after_cost_R'] for row in controls)/50 if resolved else None
    difference=candidate['price_after_cost_R']-control_mean if resolved else None
    require(difference is None or math.isfinite(difference),'nonfinite paired contrast')
    return dict(signal_id=signal['signal_id'],source_ordinal=signal['source_ordinal'],trial_id=signal['trial_id'],
        signal_asset=signal['asset'],decision_time=signal['decision_time'],direction=signal['direction'],
        cohort=cohort,candidate=candidate,controls=controls,
        pair_status='PRICE_PAIR_OBSERVED' if resolved else ('UNRESOLVED_PAIR' if paired else 'NO_FIFTY_CONTROL_COHORT'),
        candidate_price_R=candidate['price_after_cost_R'] if resolved else None,
        control_mean_price_R=control_mean,price_difference_R=difference,net_difference_R=None,
        full_matched_authority=False,promotion_authority=False)
