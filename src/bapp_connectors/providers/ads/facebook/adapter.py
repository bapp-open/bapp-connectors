"""
Facebook/Meta Ads adapter — implements AdsPort against the Marketing API v19.0.

Normalization: a Meta "ad set" is the framework's AdGroup. Budgets and bid
amounts cross the boundary as Decimals in currency units and are converted
to/from Meta's minor units (cents) by the mappers.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import CreativeUploadCapability, OAuthCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdCreative,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
    AdMediaAsset,
    AdMediaType,
    UploadedAdMedia,
)
from bapp_connectors.core.errors import ConfigurationError, ValidationError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.providers.ads.facebook.client import MetaAdsClient
from bapp_connectors.providers.ads.facebook.errors import check_payload
from bapp_connectors.providers.ads.facebook.manifest import manifest
from bapp_connectors.providers.ads.facebook.mappers import (
    ad_from_meta,
    ad_group_from_meta,
    ad_group_to_meta_payload,
    ad_to_meta_payload,
    campaign_from_meta,
    campaign_to_meta_payload,
    creative_to_meta_payload,
    insights_from_meta,
)

INSIGHTS_LEVEL_TO_META: dict[AdInsightsLevel, str] = {
    AdInsightsLevel.ACCOUNT: "account",
    AdInsightsLevel.CAMPAIGN: "campaign",
    AdInsightsLevel.AD_GROUP: "adset",
    AdInsightsLevel.AD: "ad",
}

_FB_OAUTH_DIALOG_URL = "https://www.facebook.com/v19.0/dialog/oauth"


class MetaAdsAdapter(AdsPort, CreativeUploadCapability, OAuthCapability):
    """
    Meta Marketing API adapter.

    Implements AdsPort: campaigns, ad groups (Meta ad sets), ads, and the
    universal insights interface. Also implements CreativeUploadCapability:
    media upload (adimages/advideos) and creative creation (adcreatives).

    Implements OAuthCapability: Meta OAuth2 authorization code flow plus the
    ``fb_exchange_token`` long-lived token exchange (Meta has no refresh tokens).
    """

    manifest = manifest

    CAMPAIGN_FIELDS = "id,name,status,effective_status,objective,daily_budget,lifetime_budget,start_time,stop_time"
    ADSET_FIELDS = (
        "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,bid_amount,"
        "targeting,start_time,end_time"
    )
    AD_FIELDS = "id,name,adset_id,campaign_id,status,effective_status,creative{id,title,body,image_url,thumbnail_url}"
    INSIGHTS_FIELDS = (
        "impressions,clicks,spend,ctr,cpc,cpm,reach,frequency,actions,action_values,"
        "video_play_actions,account_currency,date_start,date_stop"
    )

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        config = config or {}
        self.config = config
        self._optimization_goal = config.get("default_optimization_goal", "LINK_CLICKS")
        self._billing_event = config.get("default_billing_event", "IMPRESSIONS")
        self._app_id = credentials.get("app_id", "")
        self._app_secret = credentials.get("app_secret", "")

        self.ad_account_id = str(credentials.get("ad_account_id", "")).removeprefix("act_")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(token=credentials.get("token", "")),
                provider_name=manifest.name,
            )

        self.client = MetaAdsClient(http_client=http_client, ad_account_id=self.ad_account_id)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        if self._app_id and self._app_secret:
            # OAuth-flow-only adapter: app credentials alone are enough to run the flow.
            return True
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0 and bool(self.credentials.get("token"))

    def test_connection(self) -> ConnectionTestResult:
        try:
            account = self.client.get_object(f"act_{self.ad_account_id}", fields="id,name,account_status,currency")
            name = account.get("name", "")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to ad account '{name}' (act_{self.ad_account_id})",
                details=account,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_id": self._app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ",".join(scopes),
        }
        return f"{_FB_OAUTH_DIALOG_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        """Exchange the authorization code for a short-lived user access token."""
        response = self.client.http.call(
            "GET",
            "oauth/access_token",
            params={
                "client_id": self._app_id,
                "redirect_uri": redirect_uri,
                "client_secret": self._app_secret,
                "code": code,
            },
        )
        data = response if isinstance(response, dict) else {}
        check_payload(data)
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token="",  # Meta issues no refresh tokens
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "app_id": self._app_id,
                    "app_secret": self._app_secret,
                },
            },
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """Exchange the CURRENT ACCESS TOKEN for a long-lived one (~60 days).

        Meta has no refresh tokens — its "refresh" equivalent is the
        ``fb_exchange_token`` grant, which trades a valid (short- or long-lived)
        access token for a fresh long-lived token. Therefore ``refresh_token``
        here must be the current access token, and the returned
        ``OAuthTokens.refresh_token`` is always ``""``.
        """
        response = self.client.http.call(
            "GET",
            "oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "fb_exchange_token": refresh_token,
            },
        )
        data = response if isinstance(response, dict) else {}
        check_payload(data)
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token="",  # Meta issues no refresh tokens
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "app_id": self._app_id,
                    "app_secret": self._app_secret,
                },
            },
        )

    def list_ad_accounts(self, user_token: str) -> list[dict]:
        """List the ad accounts the user can manage, for the connect-flow account picker.

        Helper for completing the OAuth flow (not part of OAuthCapability):
        call this with the user token returned by ``exchange_code_for_token``
        (or ``refresh_token``), let the user pick an account, and store its
        ``ad_account_id`` as the ``ad_account_id`` credential (the token
        itself goes in the ``token`` credential).

        Returns a list of ``{"ad_account_id", "name", "currency", "status"}``
        dicts, where ``ad_account_id`` is the numeric account id (no ``act_``
        prefix) and ``status`` is Meta's raw ``account_status`` code.
        """
        response = self.client.http.call(
            "GET",
            "me/adaccounts",
            params={
                "fields": "id,account_id,name,currency,account_status",
                "access_token": user_token,
            },
        )
        data = response if isinstance(response, dict) else {}
        check_payload(data)
        return [
            {
                "ad_account_id": str(account.get("account_id", "")),
                "name": account.get("name", ""),
                "currency": account.get("currency", ""),
                "status": account.get("account_status"),
            }
            for account in data.get("data", [])
        ]

    # ── Shared helpers ──

    def _paginate(self, response: dict, mapper: Callable[[dict], object]) -> PaginatedResult:
        items = [mapper(row) for row in response.get("data", [])]
        paging = response.get("paging") or {}
        cursor = (paging.get("cursors") or {}).get("after")
        return PaginatedResult(items=items, cursor=cursor, has_more=bool(paging.get("next")))

    # ── Campaigns ──

    def list_campaigns(self, cursor: str | None = None) -> PaginatedResult[AdCampaign]:
        response = self.client.list_edge(
            self.client.account_path("campaigns"), fields=self.CAMPAIGN_FIELDS, after=cursor
        )
        return self._paginate(response, campaign_from_meta)

    def get_campaign(self, campaign_id: str) -> AdCampaign:
        return campaign_from_meta(self.client.get_object(campaign_id, fields=self.CAMPAIGN_FIELDS))

    def create_campaign(self, campaign: AdCampaign) -> AdCampaign:
        payload = campaign_to_meta_payload(campaign, for_create=True)
        created = self.client.create(self.client.account_path("campaigns"), payload)
        return self.get_campaign(str(created["id"]))

    def update_campaign(self, campaign_id: str, changes: dict) -> AdCampaign:
        self.client.update(campaign_id, campaign_to_meta_payload(changes))
        return self.get_campaign(campaign_id)

    def set_campaign_status(self, campaign_id: str, status: AdEntityStatus) -> AdCampaign:
        return self.update_campaign(campaign_id, {"status": status})

    # ── Ad groups (Meta ad sets) ──

    def list_ad_groups(self, campaign_id: str | None = None, cursor: str | None = None) -> PaginatedResult[AdGroup]:
        filtering = None
        if campaign_id:
            filtering = [{"field": "campaign.id", "operator": "EQUAL", "value": campaign_id}]
        response = self.client.list_edge(
            self.client.account_path("adsets"), fields=self.ADSET_FIELDS, after=cursor, filtering=filtering
        )
        return self._paginate(response, ad_group_from_meta)

    def get_ad_group(self, ad_group_id: str) -> AdGroup:
        return ad_group_from_meta(self.client.get_object(ad_group_id, fields=self.ADSET_FIELDS))

    def create_ad_group(self, ad_group: AdGroup) -> AdGroup:
        payload = ad_group_to_meta_payload(
            ad_group,
            for_create=True,
            billing_event=self._billing_event,
            optimization_goal=self._optimization_goal,
        )
        created = self.client.create(self.client.account_path("adsets"), payload)
        return self.get_ad_group(str(created["id"]))

    def update_ad_group(self, ad_group_id: str, changes: dict) -> AdGroup:
        self.client.update(ad_group_id, ad_group_to_meta_payload(changes))
        return self.get_ad_group(ad_group_id)

    def set_ad_group_status(self, ad_group_id: str, status: AdEntityStatus) -> AdGroup:
        return self.update_ad_group(ad_group_id, {"status": status})

    # ── Ads ──

    def list_ads(self, ad_group_id: str | None = None, cursor: str | None = None) -> PaginatedResult[Ad]:
        filtering = None
        if ad_group_id:
            filtering = [{"field": "adset.id", "operator": "EQUAL", "value": ad_group_id}]
        response = self.client.list_edge(
            self.client.account_path("ads"), fields=self.AD_FIELDS, after=cursor, filtering=filtering
        )
        return self._paginate(response, ad_from_meta)

    def get_ad(self, ad_id: str) -> Ad:
        return ad_from_meta(self.client.get_object(ad_id, fields=self.AD_FIELDS))

    def create_ad(self, ad: Ad) -> Ad:
        payload = ad_to_meta_payload(ad, for_create=True)
        created = self.client.create(self.client.account_path("ads"), payload)
        return self.get_ad(str(created["id"]))

    def update_ad(self, ad_id: str, changes: dict) -> Ad:
        self.client.update(ad_id, ad_to_meta_payload(changes))
        return self.get_ad(ad_id)

    def set_ad_status(self, ad_id: str, status: AdEntityStatus) -> Ad:
        return self.update_ad(ad_id, {"status": status})

    # ── CreativeUploadCapability ──

    @staticmethod
    def _read_asset(asset: AdMediaAsset, default_filename: str) -> tuple[bytes, str]:
        """Resolve the raw bytes and filename for a local media asset."""
        if asset.content is not None:
            return asset.content, asset.filename or default_filename
        if asset.file_path:
            path = Path(asset.file_path)
            return path.read_bytes(), asset.filename or path.name
        raise ValidationError("Media asset has no usable source: provide content bytes or file_path.")

    def upload_media(self, asset: AdMediaAsset) -> UploadedAdMedia:
        if asset.media_type == AdMediaType.IMAGE:
            if asset.url:
                raise ValidationError(
                    "Meta adimages cannot fetch a remote URL; download the image and "
                    "provide it as content bytes or a file_path."
                )
            content, filename = self._read_asset(asset, default_filename="image.jpg")
            response = self.client.upload_image(files={"filename": (filename, content)})
            images = response.get("images") or {}
            if not images:
                raise ValidationError("Meta adimages response contained no images.")
            image = next(iter(images.values()))
            return UploadedAdMedia(
                id=str(image.get("hash", "")),
                media_type=AdMediaType.IMAGE,
                url=image.get("url", ""),
            )

        if asset.url:
            response = self.client.upload_video(payload={"file_url": asset.url})
        else:
            content, filename = self._read_asset(asset, default_filename="video.mp4")
            response = self.client.upload_video(files={"source": (filename, content)})
        return UploadedAdMedia(id=str(response.get("id", "")), media_type=AdMediaType.VIDEO)

    def create_creative(self, creative: AdCreative, media: UploadedAdMedia | None = None) -> AdCreative:
        page_id = self.config.get("page_id")
        if not page_id:
            raise ConfigurationError(
                "Meta creative creation requires the page_id setting "
                "(the Facebook Page the creative publishes as)."
            )
        payload = creative_to_meta_payload(creative, media, str(page_id))
        created = self.client.create_creative_object(payload)
        return creative.model_copy(update={"id": str(created["id"])})

    # ── Universal insights ──

    def get_insights(
        self,
        level: AdInsightsLevel,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AdInsights]:
        object_id = entity_id or f"act_{self.ad_account_id}"
        params: dict = {
            "level": INSIGHTS_LEVEL_TO_META[level],
            "fields": self.INSIGHTS_FIELDS,
        }
        if since or until:
            time_range = {}
            if since:
                time_range["since"] = since.strftime("%Y-%m-%d")
            if until:
                time_range["until"] = until.strftime("%Y-%m-%d")
            params["time_range"] = json.dumps(time_range)

        response = self.client.get_insights(object_id, params)
        return [insights_from_meta(row, level) for row in response.get("data", [])]
