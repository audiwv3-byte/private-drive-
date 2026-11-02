# Registration fix for the current deployment

This directory contains a corrected copy of the **publicly served**
`/assets/pd-registration.js`, read on 2026-11-02. It is a release candidate,
not evidence that PythonAnywhere has been updated.

The live application has newer templates and trip/payment modules than the
repository snapshot. **Do not replace the live project with the repository
snapshot.** This fix is limited to the registration asset.

## Changes

- Allow the guest sign-in handler to display the Telegram launch link before
  validating signup consent or the optional signup email.
- Keep explicit consent for a new registration inside Telegram.
- Match the server's normalized name, telephone and email validation before
  saving; validate pilot names and telephone numbers too.
- Avoid overwriting an existing passenger profile from the signup form during
  sign-in. If optional-email saving fails after registration, report that the
  registration itself has already been saved.

`registration.diff` shows the exact changes relative to the public live asset.
The unmodified live asset's SHA-256 is
`21cc3f19d798e13df3de136f651f0d5f0148f9961674a240f06a5b6df17353c7`.

## Validation

```sh
npm ci --prefix ops/live-registration --ignore-scripts
npm test --prefix ops/live-registration
```

The tests use a DOM fixture and mocked registration handlers; no credentials,
network requests, account creation, legal acceptance or uploads occur. The
unmodified public asset fails the guest-sign-in regression; the corrected
asset passes. Backend registration and dispatcher checks are included in
`python test_release_validation.py` and use temporary databases and test-only
signed identities. They do not establish that the live backend matches GitHub.

## Deployment, once hosting access is authorized

1. Inspect the actual `/assets/pd-registration.js` route and locate its file.
2. Back up that file, the template serving its versioned URL and current source;
   preserve the production databases and driver documents.
3. Verify the live file still has the SHA-256 above. If it differs, review the
   current changes and rebase the fix; do not overwrite it blindly.
4. Replace only the registration asset with this corrected file. Update its
   template cache version from `20261102-reg-v9` to a new value. Reload the web
   app if the serving code requires it.
5. Read the served asset again and compare its SHA-256 with the candidate.
   Recheck guest entry, invalid input, RU/EN/LT and the driver form in browser.
6. Keep saved-registration, signed-in-role and full-trip verification pending
   until Telegram access is available.

No deployment, restart or production-data change was performed during this audit.
