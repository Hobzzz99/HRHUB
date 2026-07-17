"""Pure domain logic: experience calculation, skill matching, scoring, filtering.

Everything here is provider-agnostic and free of I/O, so it is fast and fully
unit-testable. Providers feed it `RawProfile` data; it returns scored results.
"""
