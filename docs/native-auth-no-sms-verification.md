# PRIVATE DRIVE native-auth: no-SMS identity verification preparation

Scope: **isolated test Render service only**. This is a design and offline regression
preparation, **not** an enabled email login or identity-binding service.
Never modify Telegram Mini App, production, payments, or SMS switches here.

## Current behavior

- Render test entrypoint `isolated_sms_wsgi.py` uses PostgreSQL and accepts
  phone Twilio Verify only. With `sms_enabled=false`, the OTP endpoints
  respond `503 sms_disabled`. No actual user can verify a real phone this way.
- The separate `pd_native_auth_http.py` test adapter supports email OTP
  via **injected delivery callback**, with no network provider installed.
  It already issues a stable server-generated `user_id` after a correct
  one-time code, and defaults its account role to `passenger`.
- Flutter currently offers phone entry only. The email UX and secure mail
  delivery service are **not** yet integrated into the Render deployment.
- The current one-time owner bootstrap intentionally requires a recent
  **phone-verified** native session. Email alone does **not** meet that
  requirement and cannot grant administrator access.

## Cost-free choices evaluated

1. **Existing local fake-delivery tests:** zero cost, no mail/SMS, verifies
   logic only. Never represents proof of a real user's control of a number
   or mailbox.
2. **Resend HTTPS API:** free quota subject to provider terms; requires a
   sender domain verified at provider, server-only API key, and real mailbox
   confirmation; can verify access to an email address but not phone ownership.
3. **Brevo transactional email HTTPS API:** free daily quota subject to
   provider terms; requires sender verification and private API key.
4. **Phone OTP:** actual verification still needs a real trusted delivery
   channel; leave off until separate permission.

Render free web services block outgoing SMTP on ports 25/465/587, so use
HTTPS-based transactional email, **not** SMTP.

## Safeguards required before enabling email on the isolated Render service

- An explicit isolated email opt-in flag, default OFF; a missing provider
  key / verified sender must fail closed.
- Separate PostgreSQL email challenges and user sessions with secure
  random codes, HMAC hashes at rest, five-minute expiry, attempt limits,
  durable rate limits per address and IP, and one-time consumption.
- Deliver codes **only** to the normalized destination; never expose OTP
  in API, logs, debugging UI, Telegram, or admin tools.
- Do not derive staff roles from email, phone, Telegram ID or client-supplied
  JSON. Default all newly verified emails to `passenger`.
- Do not merge an email account with a phone account by matching usernames.
  Linking identities must itself use authenticated proof of both sides.
- Never return an access token as a public/shareable support identifier.
  Only the verified user may see their opaque `user_id` in their session.
- Admin bootstrap stays disabled for email-only sessions until a separately
  reviewed and tested owner-verification policy is authorized.
- Never enable real SMS or production payments during this work.

## Next operator action

Choose Resend or Brevo, verify a sender domain, supply credentials privately
to the **isolated Render service**, and explicitly approve real email sends.
Only then implement/test email provider delivery + Postgres email session and
Flutter email input. Do not deploy this as a user-verification mechanism until
the end-to-end live email test succeeds.

Offline regression:
`python -m unittest -v test_native_auth_http.py test_native_auth_roles.py`
