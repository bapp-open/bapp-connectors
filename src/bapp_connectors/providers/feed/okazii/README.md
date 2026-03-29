# Okazii.ro

Generate product feeds for Okazii.ro Romanian marketplace.

- **Feed format:** XML (Okazii custom schema with `<OKAZII>/<AUCTION>` structure)
- **Auth:** None (generation-only, no API calls)
- **Upload method:** Shop hosts the XML file; Okazii polls it daily for automatic
  synchronization

## Credentials

No credentials required. This is a generation-only provider -- it transforms
Product DTOs into Okazii-compatible XML feed output without making any HTTP
calls.

## Settings

### Product Defaults

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `currency` | str | `RON` | Currency code for prices |
| `default_condition` | select | `1` | Product condition: `1`=New, `2`=Used |
| `brand_fallback` | str | | Brand name when product has no brand attribute |
| `invoice` | select | `1` | Products have invoice: `1`=Yes, `2`=No |
| `warranty` | select | `1` | Products have warranty: `1`=Yes, `2`=No |

### Payment

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `payment_personal` | bool | `false` | Accept cash on pickup |
| `payment_ramburs` | bool | `true` | Accept cash on delivery (ramburs) |
| `payment_avans` | bool | `true` | Accept bank transfer / prepayment |

### Delivery

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `delivery_time` | int | `3` | Default delivery time in days |
| `courier_name` | str | | Default courier name (e.g., Fan Courier, Sameday) |
| `courier_price` | str | | Default shipping cost (e.g., `15.99`) |

### Return Policy

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `return_accept` | bool | `true` | Accept product returns |
| `return_days` | int | `14` | Number of days for returns |

### Variants and Filters

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `include_variants` | bool | `true` | Map product variants to Okazii STOCKS section (Size/Color) |
| `only_in_stock` | bool | `false` | Exclude out-of-stock products |
| `categories_exclude` | str | | Comma-separated category IDs to exclude |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Generate feed (`FeedPort.generate_feed`) | Yes |
| Validate products (`FeedPort.validate_products`) | Yes |
| Supported formats | XML only |
| Feed upload (`FeedUploadCapability`) | No |

## Feed Fields

| XML Element | Source | Required |
|-------------|--------|----------|
| `UNIQUEID` | Product ID | Yes |
| `TITLE` | Product name | Yes |
| `CATEGORY` | Categories joined with ` > ` | Yes |
| `DESCRIPTION` | Product description (HTML stripped, wrapped in CDATA) | Recommended |
| `PRICE` | Product price (plain format) | Yes |
| `DISCOUNT_PRICE` | Sale price from `product.extra` | Optional |
| `CURRENCY` | From `currency` setting | Always included |
| `AMOUNT` | Total stock (sum of variant stocks if applicable) | Always included |
| `BRAND` | Brand attribute or `brand_fallback` | Recommended |
| `SKU` | Product SKU | Optional |
| `GTIN` | Product barcode / EAN | Optional |
| `IN_STOCK` | `1` if stock > 0 and active, else `0` | Always included |
| `STATE` | From `default_condition` setting | Always included |
| `INVOICE` | From `invoice` setting | Always included |
| `WARRANTY` | From `warranty` setting | Always included |
| `PHOTOS/URL` | All product photo URLs | Yes (at least one) |

### Payment Section

| XML Element | Source |
|-------------|--------|
| `PAYMENT/PERSONAL` | From `payment_personal` setting (0/1) |
| `PAYMENT/RAMBURS` | From `payment_ramburs` setting (0/1) |
| `PAYMENT/AVANS` | From `payment_avans` setting (0/1) |

### Delivery Section

| XML Element | Source |
|-------------|--------|
| `DELIVERY/PERSONAL` | Always `0` |
| `DELIVERY/DELIVERY_TIME` | From `delivery_time` setting |
| `DELIVERY/COURIERS/*` | From `courier_name` and `courier_price` settings |

### Return Section

| XML Element | Source |
|-------------|--------|
| `RETURN/ACCEPT` | From `return_accept` setting (0/1) |
| `RETURN/DAYS` | From `return_days` setting |
| `RETURN/METHOD` | Always `2` (seller pays return shipping) |
| `RETURN/COST` | Always `0` (free returns) |

### Attributes Section

Non-variant product attributes are emitted as:
```xml
<ATTRIBUTES>
  <ATTRIBUTE NAME="Material">Cotton</ATTRIBUTE>
</ATTRIBUTES>
```

### Stocks Section (Variants)

When `include_variants` is enabled, active product variants are mapped to:
```xml
<STOCKS>
  <STOCK>
    <AMOUNT>5</AMOUNT>
    <MARIME>XL</MARIME>
    <CULOARE>Rosu</CULOARE>
    <GTIN>1234567890123</GTIN>
  </STOCK>
</STOCKS>
```

Size and color are extracted from variant attributes matching Romanian and
English names: `size`/`marime`/`mărime`/`dimensiune` and
`color`/`colour`/`culoare`.

## Validation Rules

Products that fail **required** validation are skipped (not included in output).
Products that fail **recommended** validation generate warnings but are still
included.

- **Required:** unique_id, title, price, category, at least one photo
- **Recommended:** description, brand

## API Quirks

- **Generation only:** No HTTP client is used. No upload API exists for
  Okazii -- the shop must host the XML file and configure the URL in the
  Okazii seller panel.
- **No base_url required:** Unlike other feed providers, the Okazii adapter
  does not require a `base_url` setting since product links are not part of the
  Okazii feed schema.
- **Custom XML schema:** Okazii uses its own XML format with uppercase element
  names (`OKAZII`, `AUCTION`, `UNIQUEID`, etc.), not RSS or Atom.
- **CDATA descriptions:** The `DESCRIPTION` element content is wrapped in
  `<![CDATA[...]]>` sections via post-processing, since Python's ElementTree
  does not natively support CDATA.
- **Variant handling:** Unlike Google/Facebook/Compari (which expand variants
  as separate items), Okazii represents variants as `STOCKS` entries within a
  single `AUCTION` element. Total stock is the sum of all active variant stocks.
- **Price format:** Uses plain decimal format without currency symbol (e.g.,
  `99.99`). Currency is a separate XML element.
- **Boolean settings:** Boolean config values are converted to `0`/`1` integers
  for the XML output.
- **Discount price:** Sale/discount price is read from
  `product.extra["sale_price"]` or `product.extra["discount_price"]`.
- **Connection test:** Always succeeds (no external dependencies).
