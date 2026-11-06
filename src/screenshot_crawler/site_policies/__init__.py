"""Site-specific access policies used by the Batch Planner."""

from screenshot_crawler.site_policies.base import (
    BatchOrdering,
    PolicyDecision,
    SitePolicy,
    SitePolicyError,
)
from screenshot_crawler.site_policies.bookwalker import BookWalkerSitePolicy
from screenshot_crawler.site_policies.comicdays import ComicDaysSitePolicy
from screenshot_crawler.site_policies.comicfuz import ComicFuzSitePolicy
from screenshot_crawler.site_policies.hanayume import HanayumeSitePolicy
from screenshot_crawler.site_policies.jumpplus import JumpPlusSitePolicy
from screenshot_crawler.site_policies.kadocomi import KadocomiSitePolicy
from screenshot_crawler.site_policies.magapoke import MagapokeSitePolicy
from screenshot_crawler.site_policies.mangaone import MangaOneSitePolicy
from screenshot_crawler.site_policies.piccoma import PiccomaSitePolicy
from screenshot_crawler.site_policies.registry import SitePolicyRegistry
from screenshot_crawler.site_policies.yanmaga import YanmagaSitePolicy
from screenshot_crawler.site_policies.younganimal import YounganimalSitePolicy
from screenshot_crawler.site_policies.zeblack import ZeblackSitePolicy

__all__ = [
    "BatchOrdering",
    "BookWalkerSitePolicy",
    "ComicDaysSitePolicy",
    "ComicFuzSitePolicy",
    "HanayumeSitePolicy",
    "JumpPlusSitePolicy",
    "KadocomiSitePolicy",
    "MagapokeSitePolicy",
    "MangaOneSitePolicy",
    "PiccomaSitePolicy",
    "PolicyDecision",
    "SitePolicy",
    "SitePolicyError",
    "SitePolicyRegistry",
    "YanmagaSitePolicy",
    "YounganimalSitePolicy",
    "ZeblackSitePolicy",
]
