"""Bounded dimensions for synthetic probes; no market-study qualification."""

def validate(signals,bars,assets,definitions,unavailable):
    for name,value,lower,upper in (
        ('signals',signals,3,100),('bars',bars,400,4000),
        ('assets',assets,61,781),('definitions',definitions,3,199)):
        if type(value) is not int or not lower<=value<=upper:
            raise ValueError('%s must be %s..%s'%(name,lower,upper))
    if type(unavailable) is not int or not 1<=unavailable<=definitions-2:
        raise ValueError('unavailable definitions must leave at least two available')
    return dict(signals_per_available_trial=signals,bars_per_asset=bars,
                assets=assets,definitions=definitions,unavailable_definitions=unavailable)


def trials(definitions,unavailable):
    validate(3,400,61,definitions,unavailable)
    # Preserve original three identities; extend with distinct fixed-width hex IDs.
    return [dict(trial_id=str(i)*64 if i<3 else format(i,'064x'),
                 archive_requirement='hourly' if i>=definitions-unavailable else '4h')
            for i in range(definitions)]
