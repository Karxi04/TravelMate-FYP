# TravelMate local Windows and Android demo

This is a local-only FYP demonstration. The PC must remain on, the phone must be on the same trusted Wi-Fi, and this is not a public deployment.

1. Copy each `.env.example` to `.env` in `backend_api`, `operator_website`, and `admin_website`. Keep `APP_ENV=development`; set the existing Firebase client web API key only in the two portal files. Do not commit any `.env` file.
2. In `backend_api/.env`, set `LOCAL_LAN_DEMO=true` and `TRUSTED_LAN_CIDR` to the private Wi-Fi subnet, for example `192.168.1.0/24`. Keep provider keys empty unless you deliberately need their sandbox flow.
3. Run `powershell -ExecutionPolicy Bypass -File .\Start-TravelMate-Local.ps1 -TrustedLanCidr 192.168.1.0/24` from the repository root. It starts the backend, Operator, and Admin, then checks their health URLs.
4. Build the explicitly local debug APK, replacing the example address with the PC's active Wi-Fi IPv4 address:

```powershell
cd traveller_mobile
flutter build apk --debug --dart-define=LOCAL_DEMO=true --dart-define=API_BASE_URL=http://192.168.1.25:5000
```

5. Install `build\app\outputs\flutter-apk\app-debug.apk`. From the phone browser, open `http://192.168.1.25:5000/api/health` before opening TravelMate.

The debug manifest permits cleartext HTTP. Production release builds still require a public HTTPS API URL and reject private addresses. On a network classified as **Private**, limit any inbound TCP 5000 rule to that profile and the approved phone address.

## Two approved local networks

The Android debug app can select between the laptop's home Wi-Fi and hotspot
addresses. Set these values in the Backend's local environment before starting it:

```dotenv
LOCAL_LAN_DEMO=true
TRUSTED_LAN_CIDR=192.168.100.0/24,172.20.10.0/28
LOCAL_LAN_ORIGINS=http://192.168.100.26:5000,http://172.20.10.5:5000
LOCAL_LAN_IDENTITY_KEY=<absolute path to a private RSA PEM file>
```

Use one RSA key of at least 2048 bits for this laptop. Generate the private PEM
once, keep it outside the repository and restrict it to the Backend's Windows
account. Export its public key as base64 DER SubjectPublicKeyInfo. For example,
with OpenSSL installed and the working directory set to a private local folder:

```powershell
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out travelmate-lan.pem
$publicKey = openssl pkey -in travelmate-lan.pem -pubout -outform PEM |
  Where-Object { $_ -notmatch '^-----' }
$publicKey = $publicKey -join ''
```

Set both origins and pin that public key in the normal app's debug build. Retain
the existing Firebase and other local demo build flags for your installation.

```powershell
flutter build apk --debug --dart-define=LOCAL_DEMO=true `
  --dart-define=API_BASE_URL=http://192.168.100.26:5000 `
  --dart-define=API_BASE_URL_ALTERNATE=http://172.20.10.5:5000 `
  "--dart-define=LOCAL_LAN_PUBLIC_KEY=$publicKey"
```

If DHCP changes either laptop IP, update the matching origin in the Backend and
app build configuration, and the trusted CIDR or firewall scope if needed.
Verify both IPs and prefixes with `Get-NetIPAddress -AddressFamily IPv4`. With
the LAN mode enabled Flask listens on TCP 5000 across interfaces and enforces the
configured source CIDRs. Check Windows network profiles and the active inbound
rules. Any needed rule should cover only the two laptop/phone address pairs on
TCP 5000 and only the profiles in use. A local HTTP 403 from the phone means the
request reached Flask and the app refused it. A timeout alone cannot establish
which layer blocked the request.

The app checks the active Wi-Fi network on each API operation. It probes only
configured origins on that subnet, validates a fresh signed challenge, and then
uses the existing Firebase authorization. HTTP local mode is for trusted demo
networks. The signed probe identifies the laptop, while the HTTP API traffic
itself has no TLS encryption. The production build keeps its HTTPS requirement.

An in-flight state-changing request keeps its selected origin. If the network
changes, TravelMate does not send the request again. The next explicit action
can connect to the other verified address. Hosted Stripe return URLs stay on
the approved origin used to start that checkout. Keep that network until the
browser returns, or reopen TravelMate and check Payment History if the return
page is unreachable. A deliberate loopback checkout still needs an explicit
approved `STRIPE_CHECKOUT_RETURN_ORIGIN` fallback.
