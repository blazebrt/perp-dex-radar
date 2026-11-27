"""Fixed D5 diagnostic regimes. No market acquisition, confirmation or live gating."""
from bisect import bisect_left
from decimal import Decimal, InvalidOperation, localcontext
import re

from v9.paper_history import canonical, require, sha

DAY = 86400
FEATURES = ('btc_close', 'dvol', 'etf_net_flow', 'stablecoin_supply', 'fear_greed')
DEFINITIONS = {
    'BTC_ABOVE_SMA200': ('btc_close', 2*DAY),
    'DVOL_AT_LEAST_60': ('dvol', DAY),
    'ETF_POSITIVE_FLOW': ('etf_net_flow', 4*DAY),
    'STABLECOIN_30D_GROWTH': ('stablecoin_supply', 2*DAY),
    'FEAR_GREED_AT_LEAST_50': ('fear_greed', 2*DAY),
}


def exact_sum(values):
    # At most 100,000 <=80-character fixed-point decimals; 200 digits covers
    # mixed integer/fractional scales plus carry without ambient-context rounding.
    with localcontext() as context:
        context.prec = 200
        return sum(values, Decimal(0))


def number(value):
    require(isinstance(value, str) and re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value)
            and len(value) <= 80, 'invalid decimal')
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError('invalid decimal') from error
    require(result.is_finite(), 'nonfinite value')
    return result


class Inputs:
    """One externally source-verified, revision-aware observation inventory.

    This validates temporal mechanics, not the authenticity of source hashes or
    historical publication times. Source acceptance must occur independently.
    """
    def __init__(self, rows):
        require(isinstance(rows, list) and len(rows) <= 100000, 'observation limit')
        self.rows = {f: [] for f in FEATURES}
        keys = set()
        for row in rows:
            require(isinstance(row, dict) and set(row) ==
                    {'feature', 'period_end', 'available_at', 'value', 'source_sha256'}, 'invalid observation')
            feature, end, available = row['feature'], row['period_end'], row['available_at']
            require(feature in FEATURES and type(end) is int and type(available) is int
                    and 0 < end <= available < 8640000000000, 'invalid observation timing')
            require(isinstance(row['source_sha256'], str) and
                    re.fullmatch('[a-f0-9]{64}', row['source_sha256']), 'invalid source binding')
            key = feature, end, available
            require(key not in keys, 'ambiguous revision'); keys.add(key)
            value = number(row['value'])
            if feature in ('btc_close', 'stablecoin_supply'): require(value > 0, 'nonpositive level')
            if feature == 'dvol': require(value >= 0, 'negative volatility')
            if feature == 'fear_greed': require(0 <= value <= 100, 'sentiment range')
            if feature in ('btc_close', 'stablecoin_supply'): require(end % DAY == 0, 'daily grid required')
            self.rows[feature].append(dict(row, parsed=value))
        for rows_ in self.rows.values(): rows_.sort(key=lambda x: (x['available_at'], x['period_end']))
        self.times = {f: [x['available_at'] for x in rows_] for f, rows_ in self.rows.items()}
        self.digest = sha(canonical(rows))

    def at(self, regime, cutoff):
        require(regime in DEFINITIONS and type(cutoff) is int and cutoff > 0, 'invalid query')
        feature, age = DEFINITIONS[regime]
        # Only revisions actually available strictly before the decision can win.
        by_end = {}
        for row in self.rows[feature][:bisect_left(self.times[feature], cutoff)]:
            if row['period_end'] < cutoff: by_end[row['period_end']] = row
        def unknown(reason):
            return dict(state='UNKNOWN', reason=reason, observation_refs=[])
        if not by_end: return unknown('NO_PRIOR_AVAILABLE_OBSERVATION')
        end = max(by_end)
        if cutoff-end > age: return unknown('STALE_OBSERVATION')
        selected = [by_end[end]]
        if regime == 'BTC_ABOVE_SMA200':
            ends = [end-i*DAY for i in range(200)]
            if not all(t in by_end for t in ends): return unknown('INCOMPLETE_200_DAY_WINDOW')
            selected = [by_end[t] for t in ends]
            # Integer scaling avoids rounded division near the equality boundary.
            above = exact_sum([selected[0]['parsed']]*200) > exact_sum(x['parsed'] for x in selected)
        elif regime == 'STABLECOIN_30D_GROWTH':
            if end-30*DAY not in by_end: return unknown('MISSING_30_DAY_BASELINE')
            selected.append(by_end[end-30*DAY])
            above = selected[0]['parsed'] > selected[1]['parsed']
        else:
            threshold = {'DVOL_AT_LEAST_60': Decimal(60), 'ETF_POSITIVE_FLOW': Decimal(0),
                         'FEAR_GREED_AT_LEAST_50': Decimal(50)}[regime]
            above = selected[0]['parsed'] > threshold if regime == 'ETF_POSITIVE_FLOW' else selected[0]['parsed'] >= threshold
        return dict(state='ON' if above else 'OFF', reason='AVAILABLE_INPUTS',
                    observation_refs=[{k: x[k] for k in ('period_end', 'available_at', 'source_sha256')} for x in selected])


def report(observations, trades, *, protocol_sha256):
    """Diagnostic partition of a supplied frozen baseline, never re-simulates trades.

    Missing outcomes are not zero. This is not a portfolio backtest, significance
    test, independent qualification or permission to alter a live decision.
    """
    require(isinstance(protocol_sha256, str) and re.fullmatch('[a-f0-9]{64}', protocol_sha256), 'protocol binding required')
    require(isinstance(trades, list) and len(trades) <= 100000, 'trade limit')
    require(isinstance(observations, list) and len(observations)*len(trades) <= 5000000,
            'diagnostic join-work limit')
    inputs = Inputs(observations)
    groups = {r: {s: dict(trades=0, observed_returns=0, missing_returns=0, net_R=Decimal(0))
                  for s in ('ON', 'OFF', 'UNKNOWN')} for r in DEFINITIONS}
    identities = set()
    for trade in trades:
        require(isinstance(trade, dict) and set(trade) == {'id', 'signal_time', 'net_R'}, 'invalid baseline trade')
        identity = trade['id']
        require(isinstance(identity, str) and 0 < len(identity) <= 200 and identity not in identities, 'duplicate/invalid trade')
        identities.add(identity)
        result = None if trade['net_R'] is None else number(trade['net_R'])
        for regime in DEFINITIONS:
            state = inputs.at(regime, trade['signal_time'])['state']
            cell = groups[regime][state]; cell['trades'] += 1
            if result is None: cell['missing_returns'] += 1
            else: cell['observed_returns'] += 1; cell['net_R'] = exact_sum((cell['net_R'], result))
    for cells in groups.values():
        require(sum(x['trades'] for x in cells.values()) == len(trades), 'trade conservation failure')
        for cell in cells.values():
            cell['observed_net_R_sum'] = str(cell.pop('net_R')) if cell['observed_returns'] else None
    return dict(schema='v9.regime-diagnostic/1', protocol_sha256=protocol_sha256,
                observations_sha256=inputs.digest, baseline_sha256=sha(canonical(trades)),
                definitions=list(DEFINITIONS), baseline_trades=len(trades), groups=groups,
                status='DIAGNOSTIC_ONLY', source_authenticity_verified=False,
                statistical_confirmation=False, live_regime_gating_authorized=False,
                limitations=['Conditional trade summaries are not independent portfolio simulations.',
                             'Publication timestamps and source authenticity require independent verification.',
                             'Missing outcomes and unknown regimes remain separate; no p-values or promotion.'])
