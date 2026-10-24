# A6 source inventory and loading contract

The retained `research/v9/a6_source_inventory.json` is derived from existing
fixed audit artifacts, not a new strategy or market-matching run. Its separate
verification record reconciles all 94 original disputed blocks, 87 segment
identities and 189 conflict fields with the original rejected manifest.

The rejected audit is pinned at `003ddccc825b5aeaec1beab834c56f21b8baa9a8`;
its manifest SHA-256 is
`2f6af2c6ded2bca99c07b88cf9bc8d046261767a91afca4347e81da0fa613d09`.
The manifest binds the original hourly plan, which retains the broader
four-hour archive's 782 source hashes (781 candle files plus universe.json).
The quality ledger at `0859e683910a7eea7ef446b27cf9773f33d9e9f8` only
corroborates segment/block identities and four-hour source hashes. No
reconstruction or quarantine action changes which original disputes are kept.

`control_sources.py` verifies all four retained input-object hashes before
building the inventory. It rejects duplicate/missing blocks, changed archive
identity, mismatched four-hour references, unsafe paths and unexpected audit
counts. The CLI refuses to overwrite an existing output.

Before generating market signals, the archive adapter must call `load_universe`
on the exact broad archive commit `4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7`.
This checks universe bytes against the original hash, all nonexcluded segment
identities and the complete candle-file inventory. The 690-segment hourly
universe is not a substitute. Each `load_segment` call checks compressed source
bytes, ordered unique four-hour timestamps, finite nonnegative quote volumes,
first/last bars and row count before returning volumes and the segment-specific
dispute opens for `control_features.snapshot`.

The recorded independent check verifies the retained inventory and source-hash
bindings. It does **not** claim that all broad archive files were loaded or
independently validated. That application and the complete generated-signal
population audit remain pending. No result is labelled fully matched, and no
market cohort or outcome has been calculated. The feature-quality and cohort
specifications remain unchanged.
