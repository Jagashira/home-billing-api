# TimeTree production browser adapter

The internal adapter exposes authenticated status plus CREATE, read-only reconciliation, UPDATE, and DELETE. It accepts canonical desired/base payloads from Home Dashboard, operates only the exact configured calendar, and never reads or writes the Dashboard database.

## Authentication and write gate

Every endpoint requires `Authorization: Bearer $TIMETREE_INTERNAL_API_TOKEN`. Missing server configuration returns 503 and a wrong token returns 401. CREATE, UPDATE, and DELETE additionally require:

- `TIMETREE_ADAPTER_WRITES_ENABLED=true`
- `X-TimeTree-Write-Confirmation: WRITE_TIMETREE`

Reconciliation performs no remote write and does not require the write gate. Tokens, cookies, authorization codes, and storage state are not returned in responses.

## Browser guarantees

- The requested calendar name, ID, and canonical URL must all equal the authenticated browser result.
- Production ownership is the exact Note marker `HOME_DASHBOARD_EVENT_ID:<OrganizerEvent.id>`; titles have no marker.
- UPDATE and DELETE inspect the stored event URL and exact event ID, reconstruct the remote payload, and compare its hash with the stored base before clicking a write control.
- One `SingleWriteAttempt` guard permits at most one Save or delete-confirm click per request.
- `force=True`, JavaScript click, coordinate click, `nth-child`, partial ownership matches, and fallback to another calendar/event are not used.
- A CREATE failure at or after `save_attempted` returns `reconcile_required`. Reconciliation never creates an event.
- DELETE is verified only after TimeTree redirects away from the exact stored event route. Remaining on that route is unresolved and fails closed.

The implementation reuses the proven PoC browser/session, SPA bounded waits, observed form selectors, release-announcement-specific dismissal, event URL parsing, and artifact handling. It does not depend on PoC prefixes, HSP tokens, or JSON ownership ledgers.

## Local verification

Run unit tests with a fake backend; they do not launch Playwright or contact TimeTree:

```bash
python -m pytest -q tests/test_timetree_client.py tests/test_timetree_internal_api.py tests/test_timetree_ownership.py tests/test_timetree_selectors.py
```

Keep `TIMETREE_ADAPTER_WRITES_ENABLED` unset for read-only status checks. No production browser write was performed while implementing this adapter.
