"""Resolve Windows account names to stable SIDs for user-scope task identity."""

from __future__ import annotations


def account_sid(account: str) -> str:
    """Return the string SID for a local or domain account."""

    import win32security

    sid, _domain, _account_type = win32security.LookupAccountName(None, account)
    return str(win32security.ConvertSidToStringSid(sid))

