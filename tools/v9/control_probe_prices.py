"""Deterministic synthetic price diversity, never a market realism claim."""

def validate(profile):
    if profile not in ('baseline','diverse'):
        raise ValueError('price profile must be baseline or diverse')
    return profile


def bar(asset,index,profile='baseline'):
    validate(profile)
    if profile=='baseline':
        price=100+asset*.25+(index%11)*.03
        return price,price+1,price-1,price+.02,2e6
    # Asset-offset triangular trends and integer noise vary paths and compressibility.
    phase=(index+asset*17)%192
    trend=(phase if phase<96 else 192-phase)-48
    noise=((index+1)*1103515245 ^ (asset+1)*2654435761)&0xffffffff
    opening=(100+asset*.25)*(1+trend*.001+(noise%1001-500)*.00001)
    closing=opening*(1+((noise>>10)%1301-650)*.00001)
    wick=.001+((noise>>21)%40)*.001
    high=max(opening,closing)*(1+wick)
    low=min(opening,closing)*(1-wick)
    volume=float(1600000+noise%800001)
    return opening,high,low,closing,volume
