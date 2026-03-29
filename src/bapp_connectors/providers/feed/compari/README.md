# Compari.ro

Generate product feeds for Compari.ro Romanian price comparison platform.

- **Feed format:** XML or CSV
- **Auth:** None (generation-only, no API calls)
- **Upload method:** Shop hosts the feed file; Compari.ro polls it

## Credentials

No credentials required. This is a generation-only provider -- it transforms
Product DTOs into Compari.ro-compatible feed output without making any HTTP
calls.

## Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_url` | str | *(required)* | Shop base URL for product links |
| `product_url_template` | str | `{base_url}/product/{product_id}` | URL template. Placeholders: `{base_url}`, `{product_id}`, `{sku}` |
| `manufacturer_fallback` | str | | Manufacturer name when product has no brand attribute |
| `currency` | str | `RON` | Currency code for prices |
| `default_delivery_time` | str | | Default delivery time (e.g., `1-3 zile`) |
| `default_delivery_cost` | str | | Default delivery cost (e.g., `15.99`) |
| `feed_format` | select | `xml` | Output format: `xml` or `csv` |
| `include_variants` | bool | `true` | Expand product variants as separate feed items |
| `only_in_stock` | bool | `false` | Exclude out-of-stock products |
| `categories_exclude` | str | | Comma-separated category IDs to exclude |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Generate feed (`FeedPort.generate_feed`) | Yes |
| Validate products (`FeedPort.validate_products`) | Yes |
| Supported formats | XML, CSV |
| Feed upload (`FeedUploadCapability`) | No |

## Feed Fields

| Feed Field | Source | Required |
|------------|--------|----------|
| `identifier` | Product ID (or variant-expanded ID) | Yes |
| `name` | Product name (truncated to 200 chars) | Yes |
| `product_url` | Built from `product_url_template` | Yes |
| `price` | Product price (plain format, no currency symbol) | Yes |
| `category` | Categories joined with ` > ` | Yes |
| `image_url` | Primary product image | Yes |
| `description` | Product description (HTML stripped, max 5000 chars) | Recommended |
| `manufacturer` | Brand attribute or `manufacturer_fallback` | Recommended |
| `currency` | From `currency` setting | Always included |
| `ean_code` | Product barcode / EAN | Optional |
| `delivery_time` | From `default_delivery_time` setting | Optional |
| `delivery_cost` | From `default_delivery_cost` setting | Optional |

## Validation Rules

Products that fail **required** validation are skipped (not included in output).
Products that fail **recommended** validation generate warnings but are still
included.

- **Required:** identifier, name, product_url, price, category, image_url
- **Recommended:** description, manufacturer

## XML Output Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<products>
  <product>
    <identifier>123</identifier>
    <name>Product Name</name>
    <product_url>https://myshop.ro/product/123</product_url>
    <price>99.99</price>
    <category>Electronics > Phones</category>
    <image_url>https://...</image_url>
    <description>...</description>
    <currency>RON</currency>
    <manufacturer>Brand</manufacturer>
    <ean_code>1234567890123</ean_code>
  </product>
</products>
```

## API Quirks

- **Generation only:** No HTTP client is used. The adapter is a pure
  transformer from Product DTOs to feed output.
- **Connection test:** Succeeds if `base_url` is configured; fails otherwise.
- **Variant expansion:** When `include_variants` is true, each variant becomes
  a separate feed item with a `?variant=` query parameter appended to the URL.
- **Price format:** Uses plain decimal format without currency symbol (e.g.,
  `99.99`), unlike Google Merchant which uses `99.99 RON`.
- **Category path:** Categories are joined with ` > ` as a breadcrumb path.
