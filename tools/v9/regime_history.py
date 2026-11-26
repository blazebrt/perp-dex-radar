"""Adapt retained market observations for offline D5 diagnostics, never backfill timing."""
from decimal import Decimal, localcontext

from v9.paper_history import decode, require, sha
from tools.v9.regime_research import Inputs, DAY, FEATURES, number

SOURCES = {'fear_greed': 'alt.fng', 'stablecoin_supply': 'llama.stable', 'etf_net_flow': 'farside.etf'}


def stamp(value):
    return type(value) is int and 0 < value < 8640000000000


def numeric(value, multiplier=1):
    require(type(value) in (int, float), 'invalid retained number')
    with localcontext() as context:
        context.prec = 200
        value = Decimal(str(value))*multiplier
    require(value.is_finite() and abs(value) <= Decimal('1e18'), 'invalid retained magnitude')
    text = format(value, 'f')
    number(text)
    return text


def adapt(raw):
    require(isinstance(raw, bytes) and len(raw) <= 8*1024*1024, 'history size limit')
    doc = decode(raw)
    require(isinstance(doc, dict) and doc.get('schema') == 'v9.market-history/1', 'invalid history schema')
    capture, scan = doc.get('captured_at'), doc.get('as_of')
    digest = sha(raw)
    unavailable = {'btc_close': 'NO_DAILY_CLOSE_HISTORY',
                   'dvol': 'COMPLETED_CANDLE_NOT_ESTABLISHED'}
    observations = []
    if not stamp(capture) or not stamp(scan) or capture < scan:
        unavailable.update({f: 'CAPTURE_TIME_UNAVAILABLE_OR_INVALID' for f in SOURCES})
    else:
        sources, fetched, regime = doc.get('source_status'), doc.get('source_fetched_at'), doc.get('regime')
        require(all(isinstance(x, dict) for x in (sources, fetched, regime)), 'missing history timing/context')
        for feature, source in SOURCES.items():
            if sources.get(source) != 'OK':
                unavailable[feature] = 'SOURCE_NOT_OK'; continue
            received = fetched.get(source)
            if not stamp(received) or not scan <= received <= capture:
                unavailable[feature] = 'FETCH_TIME_UNAVAILABLE_OR_INVALID'; continue
            try:
                if feature == 'fear_greed':
                    data = regime.get('sentiment')
                    require(isinstance(data, dict), 'missing sentiment')
                    end, value = data.get('as_of'), numeric(data.get('value'))
                elif feature == 'stablecoin_supply':
                    data = regime.get('stablecoins')
                    require(isinstance(data, dict), 'missing supply')
                    end, value = data.get('as_of'), numeric(data.get('total_usd'))
                else:
                    data = regime.get('etf_flows')
                    require(isinstance(data, dict) and data.get('unit') == 'USD millions', 'invalid flow units')
                    date = data.get('last_date')
                    require(stamp(date) and date % DAY == 0, 'invalid flow date')
                    end, value = date+DAY, numeric(data.get('last_total_musd'), 1000000)
                require(stamp(end) and end <= received, 'observation postdates fetch')
                row = dict(feature=feature, period_end=end, available_at=capture,
                           value=value, source_sha256=digest)
                Inputs([row])
                observations.append(row)
            except (ValueError, ArithmeticError):
                unavailable[feature] = 'INVALID_OR_UNTIMED_OBSERVATION'
    require(set(x['feature'] for x in observations) | set(unavailable) == set(FEATURES), 'feature conservation')
    return dict(schema='v9.regime-history-adapter/1', history_sha256=digest,
                observations=observations, unavailable=unavailable,
                source_authenticity_verified=False, dataset_accepted=False,
                live_regime_gating_authorized=False,
                limitations=['Values preserve the rounded public context projection, not original upstream bytes.',
                             'Availability is conservative capture time, never inferred historical publication.',
                             'Existing records without retained timing remain unavailable.',
                             'BTC daily closes and completed DVOL candles are not established by this history.'])
