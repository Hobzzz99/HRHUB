"""Candidate data providers.

A `CandidateProvider` is the single, swappable seam between the app and wherever
candidates come from. LinkedIn (via Playwright) is just one implementation; the
`mock` provider runs the whole app with no external account.
"""
