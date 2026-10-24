"""A6 independent four-hour hypothetical execution; funding is always unknown."""
import math
from numbers import Real

BAR=14400
TAKER=.00045
MAKER=.00015
SLIP=.001


def require(ok,message):
    if not ok:raise ValueError(message)


def finite(value):
    return isinstance(value,Real) and not isinstance(value,bool) and math.isfinite(value)


def simulate(rows,decision,direction,geometry,eligible,disputed_opens,archive_end):
    """Rows are source-bound opens; archive_end is the exclusive observation end.

    One invocation is one independent attempt; there is no cross-signal state.
    Costs are fixed fractions of entry notional, not actual fill estimates.
    """
    require(type(decision) is int and decision>=0 and decision % BAR==0 and
            type(archive_end) is int and archive_end>=0 and archive_end % BAR==0,'invalid clock')
    require(type(direction) is int and direction in (-1,1) and type(eligible) is bool,'invalid direction/eligibility')
    require(set(geometry)=={'stop','target','trail','be','hold'},'invalid geometry schema')
    stop,target,trail,be=(geometry[k] for k in ('stop','target','trail','be'))
    hold=geometry['hold']
    require(all(finite(v) for v in (stop,target,trail,be)) and stop>0 and min(target,trail,be)>=0
            and type(hold) is int and hold>0,'invalid geometry')
    require(disputed_opens is not None,'explicit dispute inventory required')
    disputes=set(disputed_opens)
    require(all(type(t) is int and t>=0 and t % BAR==0 for t in disputes),'invalid disputes')
    result=dict(decision_time=decision,entry_time=decision,direction=direction,geometry=dict(geometry),
        status='UNEXECUTED',reason=None,entry_price=None,exit_time=None,exit_price=None,
        initial_risk=None,gross_R=None,cost_R=None,price_after_cost_R=None,net_R=None,
        funding_path_known=False,price_path_known=False,price_uncertainty_time=None,
        funding_reason='UNAVAILABLE_COVERAGE_AND_INTRABAR_ORDERING',
        full_matched_authority=False,promotion_authority=False)
    if not eligible:return dict(result,reason='ENTRY_INELIGIBLE')

    def observed(t):
        if t>=archive_end:return None,'ARCHIVE_END'
        if t in disputes:return None,'DISPUTED_BAR'
        row=rows.get(t)
        if row is None:return None,'MISSING_BAR'
        try:values=[row[k] for k in ('o','h','l','c','qv')]
        except (KeyError,TypeError):return None,'MALFORMED_BAR'
        if not all(finite(v) for v in values):return None,'MALFORMED_BAR'
        o,h,l,c,v=values
        if min(o,h,l,c)<=0 or h<max(o,c) or l>min(o,c) or h<l or v<0:return None,'MALFORMED_BAR'
        if v==0:return None,'ZERO_VOLUME_BAR'
        return (float(o),float(h),float(l),float(c)),None

    first,reason=observed(decision)
    if reason:return dict(result,reason=reason,price_uncertainty_time=decision)
    entry=first[0];risk=entry*stop
    active_stop=entry-direction*risk
    initial_stop=active_stop
    target_price=entry+direction*target*risk
    require(all(math.isfinite(v) for v in (risk,active_stop,target_price)) and risk>0,'nonfinite execution geometry')
    result.update(entry_price=entry,initial_risk=risk,status='UNRESOLVED_PRICE')
    best=entry
    for offset in range(hold):
        t=decision+offset*BAR
        bar,reason=observed(t)
        if reason:return dict(result,reason=reason,price_uncertainty_time=t)
        o,h,l,c=bar
        exit_price=None
        if offset and direction*(o-active_stop)<=0:exit_price,reason=o,'GAP_STOP'
        elif (l<=active_stop if direction==1 else h>=active_stop):
            exit_price=active_stop
            reason='TIGHTENED_STOP' if direction*(active_stop-initial_stop)>0 else 'STOP'
        elif target>0 and (h>=target_price if direction==1 else l<=target_price):exit_price,reason=target_price,'TARGET'
        elif offset==hold-1:exit_price,reason=c,'TIME'
        if exit_price is not None:
            gross=direction*(exit_price/entry-1)/stop
            cost=(TAKER+SLIP+(MAKER if reason=='TARGET' else TAKER+SLIP))/stop
            require(all(math.isfinite(v) for v in (gross,cost,gross-cost)),'nonfinite price outcome')
            return dict(result,status='PRICE_OBSERVED_FUNDING_UNKNOWN',reason=reason,
                exit_time=t+BAR,exit_price=exit_price,gross_R=gross,cost_R=cost,
                price_after_cost_R=gross-cost,price_path_known=True)
        if trail>0:
            best=max(best,c) if direction==1 else min(best,c)
            proposed=best-direction*entry*trail
            require(math.isfinite(proposed),'nonfinite trailing geometry')
            active_stop=max(active_stop,proposed) if direction==1 else min(active_stop,proposed)
        favorable=(h-entry)/risk if direction==1 else (entry-l)/risk
        require(math.isfinite(favorable),'nonfinite favorable excursion')
        if be>0 and favorable>=be:
            active_stop=max(active_stop,entry) if direction==1 else min(active_stop,entry)
    raise AssertionError('hold should terminate')
