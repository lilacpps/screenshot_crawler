"""Site-specific access policies used by the Batch Planner."""

from screenshot_crawler.site_policies.base import (
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)
from screenshot_crawler.site_policies.bookwalker import BookWalkerSitePolicy
from screenshot_crawler.site_policies.jumpplus import JumpPlusSitePolicy
from screenshot_crawler.site_policies.magapoke import MagapokeSitePolicy
from screenshot_crawler.site_policies.mangaone import MangaOneSitePolicy
from screenshot_crawler.site_policies.registry import SitePolicyRegistry

__all__ = [
    "BookWalkerSitePolicy",
    "JumpPlusSitePolicy",
    "MagapokeSitePolicy",
    "MangaOneSitePolicy",
    "PolicyDecision",
    "SitePolicy",
    "SitePolicyError",
    "SitePolicyRegistry",
]
