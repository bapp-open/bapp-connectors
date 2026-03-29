# Facebook Commerce

Generate product feeds for Facebook Marketplace / Meta Commerce catalog.

- **Feed format:** CSV (default) or XML (RSS 2.0)
- **Auth:** None (generation-only, no API calls)
- **Upload method:** Upload CSV/XML to Meta Commerce Manager or host as URL

## Credentials

No credentials required. This is a generation-only provider -- it transforms
Product DTOs into Facebook-compatible feed output without making any HTTP calls.

## Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_url` | str | *(required)* | Shop base URL for product links |
| `product_url_template` | str | `{base_url}/product/{product_id}` | URL template. Placeholders: `{base_url}`, `{product_id}`, `{sku}` |
| `default_condition` | select | `new` | Default product condition: `new`, `refurbished`, `used` |
| `brand_fallback` | str | | Brand name when product has no brand attribute |
| `currency` | str | `RON` | ISO 4217 currency code |
| `feed_format` | select | `csv` | Output format: `csv` or `xml` |
| `include_variants` | bool | `true` | Expand product variants as separate feed items |
| `apparel_mode` | bool | `false` | Include gender, age_group, color, size fields for apparel |
| `only_in_stock` | bool | `false` | Exclude out-of-stock products |
| `categories_exclude` | str | | Comma-separated category IDs to exclude |

## Capabilities

| Capability | Supported |
|------------|-----------|
| Generate feed (`FeedPort.generate_feed`) | Yes |
| Validate products (`FeedPort.validate_products`) | Yes |
| Supported formats | CSV, XML |
| Feed upload (`FeedUploadCapability`) | No |

## Feed Fields

| Feed Field | Source | Required |
|------------|--------|----------|
| `id` | Product ID (or variant-expanded ID) | Yes |
| `title` | Product name (truncated to 150 chars) | Yes |
| `description` | Product description (HTML stripped, max 5000 chars) | Yes |
| `availability` | Derived from product stock (`in stock` / `out of stock`) | Yes |
| `condition` | From `default_condition` setting | Yes |
| `price` | Price with currency (e.g., `99.99 RON`) | Yes |
| `link` | Built from `product_url_template` | Yes |
| `image_link` | Primary product image | Yes |
| `additional_image_link` | Up to 10 additional images (comma-separated) | Optional |
| `brand` | Brand attribute or `brand_fallback` | Recommended |
| `gtin` | Product barcode / EAN | Optional |
| `mpn` | Product SKU | Optional |
| `product_type` | Categories joined with ` > ` | Optional |

### Apparel Mode Fields

When `apparel_mode` is enabled, these additional fields are included:

| Feed Field | Source | Notes |
|------------|--------|-------|
| `gender` | Variant attrs or product attrs (`gender`, `gen`, `sex`) | |
| `age_group` | Variant attrs or product attrs (`age_group`, `varsta`, `vârstă`) | |
| `color` | Variant attrs or product attrs (`color`, `colour`, `culoare`) | |
| `size` | Variant attrs or product attrs (`size`, `marime`, `mărime`) | |

Apparel attributes are resolved from variant attributes first, falling back to
product-level attributes. Both English and Romanian attribute names are recognized.

## Validation Rules

Products that fail **required** validation are skipped (not included in output).
Products that fail **recommended** validation generate warnings but are still
included.

- **Required:** id, title, description, link, image_link, price
- **Recommended:** brand

## XML Output Structure (RSS 2.0)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Product Feed</title>
    <link>https://myshop.ro</link>
    <item>
      <id>123</id>
      <title>Product Name</title>
      <description>...</description>
      <availability>in stock</availability>
      <condition>new</condition>
      <price>99.99 RON</price>
      <link>https://myshop.ro/product/123</link>
      <image_link>https://...</image_link>
      <brand>Brand</brand>
    </item>
  </channel>
</rss>
```

## API Quirks

- **Generation only:** No HTTP client is used. The adapter is a pure
  transformer from Product DTOs to feed output. A future version may support
  upload via the Facebook Catalog API.
- **CSV is default:** Unlike Google Merchant (XML default), Facebook Commerce
  defaults to CSV output format.
- **Connection test:** Succeeds if `base_url` is configured; fails otherwise.
- **Variant expansion:** When `include_variants` is true, each variant becomes
  a separate feed item with a `?variant=` query parameter appended to the URL.
- **Price format:** Includes currency code (e.g., `99.99 RON`).
- **Additional images:** Up to 10 extra images from the product photos are
  included as a comma-separated string.
- **Apparel mode toggle:** Apparel fields (gender, age_group, color, size) are
  only included in the CSV when `apparel_mode` is enabled, keeping the feed
  compact for non-apparel shops.
