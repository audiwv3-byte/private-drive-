# PRIVATE DRIVE — isolated iPhone Safari test publishing (no production changes)

The GitHub Actions workflow `.github/workflows/flutter-web-preview.yml`
builds the existing Flutter application for the browser. It does **not** deploy.

## Free, isolated manual preview — Netlify Drop

1. Open [Flutter Web Preview GitHub Actions runs](https://github.com/audiwv3-byte/private-drive-/actions/workflows/flutter-web-preview.yml) and select the latest successful run on `feature/flutter-independent-auth`.
2. Download its `private-drive-web-preview` ZIP artifact. Its root contains `index.html`, `main.dart.js`, `assets/`, `_redirects`, `_headers`, and `robots.txt`.
3. Open [Netlify Drop](https://app.netlify.com/drop), and upload the ZIP file into a **new** test site. Do not connect any existing production domain or Git repository. Netlify provides a separate `.netlify.app` HTTPS address.
4. Open the resulting HTTPS URL using Safari on iPhone. On Android the existing APK remains separate and unaffected.

### Security and test limitations

- The test bundle is **publicly accessible** to anyone who obtains its URL. Robots and noindex headers discourage search indexing; they are **not access control**.
- `PD_NATIVE_AUTH_API_URL` is deliberately empty. Real SMS authentication and backend account registration are **not** enabled. The application offers its offline demo UI.
- No Twilio credentials, payment keys, PostgreSQL URL, or production host secrets may be embedded in the Flutter Web bundle.
- Public OSM, OSRM, and Photon endpoints may fail browser CORS or usage policies. GPS requires HTTPS and the user's permission. Map/address behaviour must be tested on Safari before claiming ready.
- The demo must not take real bookings or payments. Do not distribute to customers for real service until API authorization and backend role checks are verified.
- The Render Free PostgreSQL database is temporary. This static preview does not connect to it.
- Uploading to Netlify is a separate user-confirmed action and does not modify PythonAnywhere, Flutter Android APK, Telegram Mini App, or the repository's main branch.
