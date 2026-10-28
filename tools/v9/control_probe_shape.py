"""Bounded dimensions for synthetic probes; no market-study qualification."""

def validate(signals,bars,assets,definitions,unavailable):
    for name,value,lower,upper in (
        ('signals',signals,3,25000),('bars',bars,400,4000),
        ('assets',assets,61,781),('definitions',definitions,3,199)):
        if type(value) is not int or not lower<=value<=upper:
            raise ValueError('%s must be %s..%s'%(name,lower,upper))
    if type(unavailable) is not int or not 1<=unavailable<=definitions-2:
        raise ValueError('unavailable definitions must leave at least two available')
    # Every normal probe includes the eight-asset sparse case. Validate its
    # capacity before starting any case, so requests never silently repeat pairs.
    if signals>(bars-181)*8+1:
        raise ValueError('signals exceed unique sparse asset/time capacity')
    return dict(signals_per_available_trial=signals,bars_per_asset=bars,
                assets=assets,definitions=definitions,unavailable_definitions=unavailable)


def trials(definitions,unavailable):
    validate(3,400,61,definitions,unavailable)
    # Preserve original three identities; extend with distinct fixed-width hex IDs.
    return [dict(trial_id=str(i)*64 if i<3 else format(i,'064x'),
                 archive_requirement='hourly' if i>=definitions-unavailable else '4h')
            for i in range(definitions)]


def signal_coordinates(signals,bars,assets):
    """Unique pre-terminal asset/time pairs plus the original terminal attempt."""
    if type(signals) is not int or not 3<=signals<=25000:
        raise ValueError('signals must be 3..25000')
    if type(bars) is not int or not 400<=bars<=4000:
        raise ValueError('bars must be 400..4000')
    if type(assets) is not int or not 1<=assets<=781:
        raise ValueError('invalid synthetic asset count')
    span=bars-181
    if signals>span*assets+1:
        raise ValueError('signals exceed unique asset/time capacity')
    # Filling asset zero first preserves all original <=100-signal cases.
    indices=[180+n%span for n in range(signals-1)]+[bars-1]
    columns=[n//span for n in range(signals-1)]+[0]
    return indices,columns


def shard_limit(value):
    if type(value) is not int or not 1<=value<=25000:
        raise ValueError('shard rows must be 1..25000')
    return value
