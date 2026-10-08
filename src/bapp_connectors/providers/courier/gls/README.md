# GLS

MyGLS API (GLS Eastern Europe: RO, HU, HR, CZ, SI, SK, RS) — AWB + label, tracking (also 100 AWBs per
request), cancellation, parcel list, ParcelShop/locker list.

- **Base URL:** `https://api.mygls.{country}/ParcelService.svc/json/` — test: `https://api.test.mygls.{country}/...`
- **Source:** "MyGLS API for system integration" ver. 25.12.11 and the sample files from
  <https://api.mygls.ro/index_en.html>. **Not yet run against the live or test host**: the tests mock HTTP.
- **Test account:** none public; the test host needs a separate account from GLS (Romania: it@gls-romania.ro).
  Production logins answer `ErrorCode -1 Unauthorized` there.
- **Capabilities:** `CourierPort`, `BatchTrackingCapability`.

## Credentials / settings

| Field | Notes |
|---|---|
| `username`, `password` | MyGLS login (e-mail + password); API access may need to be enabled by GLS on the account |
| `client_number` | GLS client number |
| `country` | `RO` / `HU` / `HR` / `CZ` / `SI` / `SK` / `RS` — picks the host, the tracking language, the COD currency |
| `test` | `true` → `api.test.mygls.{country}` |
| `printer_type` (setting) | `A4_2x2`, `A4_4x1`, `Connect` (default), `Thermo`, `ThermoZPL`, `ThermoZPL_300DPI`, `ShipItThermoPdf`, `ShipItThermoZpl`. The ZPL ones return ZPL in `label_pdf`, not PDF |
| `hide_phone_on_label` (setting) | `HidePhoneNumberOnLabels` |
| `service_sm1` + `service_sm1_text` (settings) | SM1: SMS at hand-over; text variables `#ParcelNr#`, `#COD#`, `#PickupDate#`, `#From_Name#`, `#ClientRef#` |
| `service_sm2` (setting) | SM2: SMS on the delivery day |
| `service_fds` (setting) | FDS FlexDelivery: e-mail with the delivery window |
| `service_fss` (setting) | FSS FlexDelivery by SMS; only with FDS (otherwise GLS error 30) |

## Shipment mapping

- `shipment.extra`: `reference` (→ `ClientReference`, also the default `CODReference`; `client_reference` is
  accepted too), `content` (→ `Content`; defaults to the reference), `cod_amount`, `cod_reference`,
  `cod_currency` (default: the destination country's currency), `pickup_date` (date/datetime or `/Date(..)/`),
  `service_list` (raw GLS services, e.g. `[{"Code": "SAT"}]`), `sender_email`.
- `recipient.extra` / `sender.extra`: `company` or `name` (→ `Name`), `contact_name`, `phone` (sent in
  international format, `0722…` → `+40722…`), `email`, `number` (→ `HouseNumber`, digits only),
  `house_number_info`, `pickup_point_id` (recipient: ParcelShop/locker `Id` from `get_delivery_points()` or a
  matchcode → service `PSD`; then name, phone and e-mail are mandatory).
- `shipment.parcels` → `Count` (max 99) and `ParcelPropertyList` (weight; length/width/height when set).
- With `cod_amount` the `COD` service is added. SM1/SM2/FDS/FSS come from the settings, each only when the
  recipient has the phone / e-mail it needs.
- `AWBLabel.extra`: `parcel_id` (first `ParcelId`), `parcels` (`PrintLabelsInfoList`), `parcel_numbers`, `errors`.

## Quirks

- JSON-RPC style: every call is a `POST` with `Username` and `Password` in the body; the password is the
  SHA-512 digest **as a list of byte values**, not hex.
- The host depends on the credentials, so the client calls absolute URLs: the registry's HTTP client is bound to
  the RO manifest URL.
- Errors come with HTTP 200, in `PrintLabelsErrorList` / `DeleteLabelsErrorList` / `GetParcelStatusErrors` /
  `GetParcelListStatusesErrors` (`ErrorInfo`: code + description, Appendix A). `-1` → `AuthenticationError`,
  `31` (same request 5× in 5 min) → `RateLimitError`, `1000`/`1001` → `ProviderError`, the rest →
  `ValidationError`. If `PrintLabels` returns a parcel number **and** errors, the AWB is kept and the errors are
  logged (the parcel exists at GLS).
- Tracking: `get_tracking` logs GLS errors (unknown number, not scanned yet, even a bad login) and returns no
  events, so a status poller walking every tenant's AWBs is not stopped by one of them. `get_tracking_batch`
  raises on a bad login.
- `PrintLabels` and `DeleteLabels` are sent once (`retry=False`): a retry after a timeout would create a second
  parcel. GLS itself refuses the 5th identical request in 5 minutes (error 31).
- Cancel (`DeleteLabels`) takes the **ParcelId**, not the AWB number, and works only before hand-over; the first
  ParcelId of a multi-parcel shipment deletes all of them.
- Dates are WCF `/Date(ms+hhmm)/`; the milliseconds are UTC, the offset is kept on the parsed datetime.
- `Labels` is a byte array serialized as a list of ints.
- GLS lists statuses newest first; `get_tracking` returns them oldest first, like the other couriers.
- `GetParcelListStatuses` takes at most 100 parcel numbers (`get_tracking_batch` chunks).
- `GetDeliveryPoints` (MasterDataService) returns the points as GZIP-compressed JSON in a byte array; it is large,
  cache it.
- `LanguageIsoCode` is ISO 639-1 (`CS` for CZ, `SL` for SI), not the country code.
- Method names are unversioned (= GLS' latest). `PrintLabels_20251022` only adds the locker `PIN` to the response.
- Connection test: `GetParcelList` and look for `ErrorCode -1` (there is no dedicated auth endpoint).

## Status mapping

`01` picked up · `02`/`03`/`06`/`07`/`86` in transit · `04`/`85` out for delivery · `05`/`54`/`55`/`58`/`92`/`97`
delivered · `11`/`12`/`14`/`15`/`16`/`18`/`20` failed delivery · `17`/`23`/`40` returned · `51` created ·
`83`/`84` picked up. Unmapped codes → in transit. The raw code is in `TrackingEvent.extra["code"]`.
