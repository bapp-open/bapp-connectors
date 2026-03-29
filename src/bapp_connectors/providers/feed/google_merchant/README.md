# Google Merchant Center

Generate product feeds for Google Shopping / Google Merchant Center.

- **Feed format:** XML (RSS 2.0 with `g:` namespace, default) or CSV
- **Auth:** None (generation-only, no API calls)
- **Upload method:** Upload XML/CSV to Google Merchant Center or host as URL

## Credentials

No credentials required. This is a generation-only provider -- it transforms
Product DTOs into Google Merchant-compatible feed output without making any
HTTP calls.

## Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_url` | str | *(required)* | Shop base URL for product links |
| `product_url_template` | str | `{base_url}/product/{product_id}` | URL template. Placeholders: `{base_url}`, `{product_id}`, `{sku}` |
| `default_condition` | select | `new` | Default product condition: `new`, `refurbished`, `used` |
| `default_availability` | select | `in stock` | Default availability: `in stock`, `out of stock`, `preorder` |
| `brand_fallback` | str | | Brand name when product has no brand attribute |
| `currency` | str | `RON` | ISO 4217 currency code |
| `default_google_category` | str | | Global fallback Google taxonomy category |
| `category_mapping` | textarea | | JSON mapping of store categories to Google taxonomy |
| `feed_title` | str | `Product Feed` | Title element in the feed |
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
| `g:id` | Product ID (or variant-expanded ID) | Yes |
| `g:title` | Product name (truncated to 150 chars) | Yes |
| `g:link` | Built from `product_url_template` | Yes |
| `g:image_link` | Primary product image | Yes |
| `g:price` | Price with currency (e.g., `99.99 RON`) | Yes |
| `g:description` | Product description (HTML stripped, max 5000 chars) | Recommended |
| `g:availability` | Derived from product stock or `default_availability` | Always included |
| `g:condition` | From `default_condition` setting | Always included |
| `g:brand` | Brand attribute or `brand_fallback` | Recommended* |
| `g:gtin` | Product barcode / EAN | Recommended* |
| `g:mpn` | Product SKU | Recommended* |
| `g:google_product_category` | Category mapping (see below) | Optional |
| `g:product_type` | Store categories joined with ` > ` | Optional |
| `g:additional_image_link` | Up to 10 additional images | Optional |

*At least one of brand, GTIN, or MPN is recommended by Google.

## Google Product Category Resolution

The `google_product_category` field is resolved in priority order:

1. **Per-product override:** `product.extra["google_product_category"]`
2. **Category mapping:** `category_mapping` JSON setting maps store categories
   to Google taxonomy. Tries full category path first, then individual
   categories.
3. **Global fallback:** `default_google_category` setting.

### Category mapping example

```json
{
  "Electronics": "Electronics",
  "Clothing > T-Shirts": "Apparel & Accessories > Clothing > Shirts & Tops"
}
```

## Validation Rules

Products that fail **required** validation are skipped (not included in output).
Products that fail **recommended** validation generate warnings but are still
included.

- **Required:** id, title, link, image_link, price
- **Recommended:** description; at least one of brand/gtin/mpn

## XML Output Structure (RSS 2.0 + g: namespace)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
  <channel>
    <title>Product Feed</title>
    <description></description>
    <link>https://myshop.ro</link>
    <item>
      <g:id>123</g:id>
      <g:title>Product Name</g:title>
      <g:description>...</g:description>
      <g:link>https://myshop.ro/product/123</g:link>
      <g:image_link>https://...</g:image_link>
      <g:price>99.99 RON</g:price>
      <g:availability>in stock</g:availability>
      <g:condition>new</g:condition>
      <g:brand>Brand</g:brand>
    </item>
  </channel>
</rss>
```

## API Quirks

- **Generation only:** No HTTP client is used. The adapter is a pure
  transformer from Product DTOs to feed output. A future version may support
  upload via the Google Content API.
- **g: namespace:** XML output uses the `http://base.google.com/ns/1.0`
  namespace with the `g:` prefix, as required by Google Merchant Center.
- **Connection test:** Succeeds if `base_url` is configured; fails otherwise.
- **Variant expansion:** When `include_variants` is true, each variant becomes
  a separate feed item with a `?variant=` query parameter appended to the URL.
- **Price format:** Includes currency code (e.g., `99.99 RON`).
- **Additional images:** Up to 10 extra images are included, each as a
  separate `g:additional_image_link` element in XML or comma-separated in CSV.
- **Category mapping JSON:** The `category_mapping` setting accepts either a
  JSON string or a dict. Invalid JSON is silently ignored (empty mapping).
